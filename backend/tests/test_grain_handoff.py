"""粒度声明交接副本领域测试。

覆盖：出档派生签收待办、离线材料恒定、采用/退回、冲突待决的一致规则、
退回补正父子出档链路、编辑与出档并发不拼接两个修订、旧出档号内容恒定，
以及两个版本不能共享一笔采用决定。
"""
from __future__ import annotations

import threading

import pytest

from app.services.grain_declare import GrainDeclareService
from app.services.grain_handoff import (
    HANDOFF_LOCK,
    GrainHandoffService,
    TODO_ADOPTED,
    TODO_CONFLICT,
    TODO_PENDING,
    TODO_RETURNED,
    TODO_SUPERSEDED,
)


@pytest.fixture()
def services():
    return GrainHandoffService(), GrainDeclareService()


def _declare(gd: GrainDeclareService, declare_id: str, *, version: str = "v1",
             dims: str = "客户+产品+时间"):
    ok, _, entry = gd.declare_grain(
        declare_id, "销售事实表", "客户每笔销售", dims,
        "半可加", "customer_id+product_code+date", version)
    assert ok
    return entry


class TestIssueAndTodo:
    def test_issue_creates_one_dispatch_and_one_todo(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-001")
        ok, msg, dispatch = hs.issue_dispatch("GRN-UT-001")
        assert ok
        assert dispatch["出档号"] == "HD-GRN-UT-001-01"
        assert dispatch["待办状态"] == TODO_PENDING

        dispatches = hs.list_dispatches(declare_id="GRN-UT-001")
        todos = hs.list_todos(declare_id="GRN-UT-001")
        open_todos = hs.list_todos(declare_id="GRN-UT-001", open_only=True)
        # 一个出档件只派生一笔签收待办
        assert len(dispatches) == 1
        assert len(todos) == 1
        assert len(open_todos) == 1
        assert todos[0]["出档号"] == "HD-GRN-UT-001-01"

    def test_issue_unknown_declaration_rejected(self, services):
        hs, _ = services
        ok, msg, dispatch = hs.issue_dispatch("GRN-UT-NOPE")
        assert not ok
        assert dispatch is None
        assert "不存在" in msg


class TestOfflineMaterial:
    def test_material_is_offline_html_and_content_frozen(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-002", dims="客户+产品+时间")
        ok, _, dispatch = hs.issue_dispatch("GRN-UT-002")
        handoff_no = dispatch["出档号"]

        first = hs.download_material(handoff_no)
        assert first is not None
        content_a, filename = first
        assert filename == f"{handoff_no}.html"
        assert content_a.startswith(b"<!DOCTYPE html>")
        # 自包含：不引用任何外部资源
        assert b"http://" not in content_a and b"https://" not in content_a
        assert handoff_no.encode() in content_a
        assert "GRN-UT-002".encode() in content_a

        # 出档后再修订声明，旧出档号下载到的仍是出档当日同一份材料
        gd.edit_declaration("GRN-UT-002", {"维度组合": "客户+产品+时间+渠道"})
        content_b, _ = hs.download_material(handoff_no)
        assert content_a == content_b

    def test_old_and_new_dispatch_material_differ_but_each_stable(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-003", dims="组合-旧", version="v1")
        _, _, old = hs.issue_dispatch("GRN-UT-003")
        old_no = old["出档号"]
        old_bytes, _ = hs.download_material(old_no)

        gd.edit_declaration("GRN-UT-003", {"维度组合": "组合-新", "声明版本": "v2"})
        _, _, new = hs.issue_dispatch("GRN-UT-003")
        new_no = new["出档号"]
        assert new_no != old_no
        new_bytes, _ = hs.download_material(new_no)

        assert new_bytes != old_bytes
        assert "组合-新".encode() in new_bytes
        # 凭旧出档号仍能下载当日（旧）内容
        assert hs.download_material(old_no)[0] == old_bytes
        assert "组合-旧".encode() in old_bytes


class TestAdoptAndConflict:
    def _two_conflicting(self, hs, gd, declare_id):
        _declare(gd, declare_id)
        hs.issue_dispatch(declare_id)
        gd.edit_declaration(declare_id, {"维度组合": "客户+产品+时间+渠道"})
        hs.issue_dispatch(declare_id)
        first = f"HD-{declare_id}-01"
        second = f"HD-{declare_id}-02"
        return first, second

    def test_newer_issue_marks_old_todo_conflict(self, services):
        hs, gd = services
        first, second = self._two_conflicting(hs, gd, "GRN-UT-004")
        old = hs.get_dispatch(first)
        new = hs.get_dispatch(second)
        assert old["待办状态"] == TODO_CONFLICT
        assert old["冲突于"] == second
        assert new["待办状态"] == TODO_PENDING

    def test_plain_adopt_blocked_while_conflict(self, services):
        hs, gd = services
        first, _ = self._two_conflicting(hs, gd, "GRN-UT-005")
        ok, msg, _ = hs.adopt_dispatch(first)
        assert not ok
        assert "冲突待决" in msg

    def test_adopt_legacy_binds_decision_to_old_only(self, services):
        hs, gd = services
        first, second = self._two_conflicting(hs, gd, "GRN-UT-006")
        ok, msg, entry = hs.adopt_conflicted_legacy(first)
        assert ok
        assert entry["待办状态"] == TODO_ADOPTED

        old = hs.get_dispatch(first)
        new = hs.get_dispatch(second)
        # 旧口径被采用；新待办有明确去向并关闭，且没有共享这笔采用决定
        assert old["待办状态"] == TODO_ADOPTED
        assert new["待办状态"] == TODO_SUPERSEDED
        assert new["dispatch_status"] == "已作废"
        assert first in new["去向说明"]
        # 采用决定只挂在旧出档号上：新件签收人必须为空，两个版本不共享一笔决定
        assert old["签收人"] and old["决定时间"]
        assert new["签收人"] == ""
        # 不能重复采用，两个版本不会落到同一笔决定上
        ok2, _, _ = hs.adopt_conflicted_legacy(first)
        assert not ok2

    def test_switch_to_newer_then_adopt_new(self, services):
        hs, gd = services
        first, second = self._two_conflicting(hs, gd, "GRN-UT-007")
        ok, msg, entry = hs.switch_to_newer(first)
        assert ok
        old = hs.get_dispatch(first)
        new = hs.get_dispatch(second)
        # 旧待办有明确去向；新待办恢复办理
        assert old["待办状态"] == TODO_SUPERSEDED
        assert second in old["去向说明"]
        assert new["待办状态"] == TODO_PENDING

        ok2, _, adopted = hs.adopt_dispatch(second)
        assert ok2
        assert adopted["待办状态"] == TODO_ADOPTED
        # 旧件保持作废去向，不会被新决定连带采用
        assert hs.get_dispatch(first)["待办状态"] == TODO_SUPERSEDED

    def test_both_sides_show_same_conflict_rule(self, services):
        hs, gd = services
        first, second = self._two_conflicting(hs, gd, "GRN-UT-008")
        grain_side = {d["出档号"]: d for d in hs.list_dispatches()}
        summary_side = {t["出档号"]: t for t in hs.list_todos()}
        # 声明页与汇总页读的是同一份状态与同一冲突指向
        for no in (first, second):
            assert grain_side[no]["待办状态"] == summary_side[no]["待办状态"]
            assert grain_side[no]["冲突于"] == summary_side[no]["冲突于"]

    def test_adopted_result_remains_queryable(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-009")
        _, _, dispatch = hs.issue_dispatch("GRN-UT-009")
        hs.adopt_dispatch(dispatch["出档号"])
        adopted = hs.get_dispatch(dispatch["出档号"])
        assert adopted["待办状态"] == TODO_ADOPTED
        # 已采用结果回查时仍带完整快照与签收留痕
        assert adopted["快照"]["声明编号"] == "GRN-UT-009"
        assert adopted["签收人"] and adopted["决定时间"]
        # 已采用后不能再退回
        ok, _, _ = hs.return_dispatch(dispatch["出档号"], "迟来的退回")
        assert not ok


class TestReturnAndCorrection:
    def test_return_requires_reason(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-010")
        _, _, dispatch = hs.issue_dispatch("GRN-UT-010")
        ok, msg, _ = hs.return_dispatch(dispatch["出档号"], "  ")
        assert not ok
        assert "原因" in msg

    def test_return_then_correction_emits_new_with_parent(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-011", dims="组合-待退回")
        _, _, dispatch = hs.issue_dispatch("GRN-UT-011")
        parent_no = dispatch["出档号"]
        old_bytes, _ = hs.download_material(parent_no)

        ok, _, returned = hs.return_dispatch(parent_no, "维度组合缺少渠道维度")
        assert ok
        assert returned["待办状态"] == TODO_RETURNED
        assert returned["退回原因"] == "维度组合缺少渠道维度"

        # 未退回的出档件不能发起补正
        ok_other, _, _ = hs.start_correction("HD-GRN-UT-001-01", "误发起")
        assert not ok_other

        ok, msg, correction = hs.start_correction(parent_no, "补充渠道维度")
        assert ok
        correction_no = correction["补正编号"]
        # 同一退回件只允许一笔进行中的补正
        ok_dup, _, _ = hs.start_correction(parent_no, "重复补正")
        assert not ok_dup

        # 制单员在声明页落实补正内容
        gd.edit_declaration("GRN-UT-011", {"维度组合": "组合-已补正", "声明版本": "v2"})
        ok, msg, new_dispatch = hs.confirm_correction(correction_no)
        assert ok
        new_no = new_dispatch["出档号"]
        assert new_no != parent_no
        # 确认后的补正另发新件并保留父出档号
        assert new_dispatch["父出档号"] == parent_no
        assert new_dispatch["快照"]["维度组合"] == "组合-已补正"

        stored = next(c for c in hs.list_corrections(handoff_no=parent_no)
                      if c["补正编号"] == correction_no)
        assert stored["status"] == "已发新件"
        assert stored["新出档号"] == new_no
        # 补正单不能重复确认发件
        ok_again, _, _ = hs.confirm_correction(correction_no)
        assert not ok_again
        # 同一退回件确认发新件后不能再挂第二笔补正
        ok_second, second_msg, _ = hs.start_correction(parent_no, "再次补正")
        assert not ok_second
        assert "已发新件" in second_msg
        # 父出档号材料保持退回当日内容，父子链路可回查
        assert hs.download_material(parent_no)[0] == old_bytes
        parent = hs.get_dispatch(parent_no)
        assert parent["补正编号"] == correction_no

    def test_return_blocked_during_conflict(self, services):
        hs, gd = services
        _declare(gd, "GRN-UT-012")
        hs.issue_dispatch("GRN-UT-012")
        gd.edit_declaration("GRN-UT-012", {"维度组合": "变更"})
        hs.issue_dispatch("GRN-UT-012")
        ok, msg, _ = hs.return_dispatch("HD-GRN-UT-012-01", "冲突中退回")
        assert not ok
        assert "回到新副本" in msg


class TestConcurrentEditAndIssue:
    def test_no_splice_between_two_revisions(self, services):
        """编辑与出档并发：每个出档快照必须来自一个完整修订，不能跨修订拼接。"""
        hs, gd = services
        declare_id = "GRN-UT-013"
        _declare(gd, declare_id, dims="组合-0", version="v0")

        rounds = 40
        valid_pairs = {("组合-0", "v0")}
        errors: list[Exception] = []

        def edit_worker() -> None:
            try:
                for k in range(1, rounds + 1):
                    dims, version = f"组合-{k}", f"v{k}"
                    valid_pairs.add((dims, version))
                    ok, _, _ = gd.edit_declaration(declare_id, {
                        "维度组合": dims, "声明版本": version})
                    assert ok
            except Exception as exc:  # pragma: no cover - 并发异常记录
                errors.append(exc)

        def issue_worker() -> None:
            try:
                for _ in range(rounds):
                    ok, _, dispatch = hs.issue_dispatch(declare_id)
                    assert ok and dispatch is not None
            except Exception as exc:  # pragma: no cover - 并发异常记录
                errors.append(exc)

        t1 = threading.Thread(target=edit_worker)
        t2 = threading.Thread(target=issue_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors

        import hashlib
        import json

        dispatches = hs.list_dispatches(declare_id=declare_id)
        # 出档轮次全部落库，且每个快照都是某个完整修订（两个字段成对），
        # 出现「维度组合来自修订 A、声明版本来自修订 B」即判定为拼接。
        assert len(dispatches) == rounds
        for dispatch in dispatches:
            snapshot = dispatch["快照"]
            assert (snapshot["维度组合"], snapshot["声明版本"]) in valid_pairs
            expected_hash = hashlib.sha256(
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()[:16]
            assert dispatch["内容哈希"] == expected_hash

    def test_lock_is_reentrant_and_shared(self):
        # 出档服务与声明编辑导入的是同一把锁：这是「不拼接两个修订」的结构保证
        from app.services import grain_declare as gd_module

        assert gd_module.HANDOFF_LOCK is HANDOFF_LOCK
        # RLock 允许同线程重入且不死锁
        HANDOFF_LOCK.acquire()
        try:
            HANDOFF_LOCK.acquire()  # 同线程重入，非 RLock 会自死锁
            HANDOFF_LOCK.release()
        finally:
            HANDOFF_LOCK.release()


class TestSeedDemo:
    def test_seed_includes_returned_dispatch_and_correction(self, services):
        hs, _ = services
        todos = {t["出档号"]: t for t in hs.list_todos()}
        assert "HD-GRN-001-01" in todos
        seed = todos["HD-GRN-001-01"]
        assert seed["待办状态"] == TODO_RETURNED
        assert seed["退回原因"]
        corrections = hs.list_corrections(handoff_no="HD-GRN-001-01")
        assert any(c["status"] == "补正中" for c in corrections)
