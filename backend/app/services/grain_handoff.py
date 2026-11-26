"""粒度声明交接副本领域服务。

制单员在「粒度声明」侧把声明当日内容冻结成不可变的出档件（出档号 HD-*），
跨模块在「汇总层派生」侧派生一单一笔的签收待办，汇总员按声明号 + 出档号
采用或退回。核心不变量：

1. 出档件是出档当时的快照（含内容哈希），出档与声明编辑共用一把锁，
   两个修订不可能拼接进同一份出档；凭旧出档号永远下载得到出档当日的内容。
2. 每个出档件只派生一笔签收待办，采用决定只绑定该出档号，两个版本绝不
   共享一笔采用决定。
3. 同一声明出现更新的出档件时，旧的未决待办进入「冲突待决」而不是被静默
   关闭：汇总员要么采用旧口径（新待办登记去向后关闭），要么回到新副本
   （旧待办登记去向后关闭，新待办继续办理）。两边界面与执行共用同一规则。
4. 退回必须登记原因；补正按被退回的出档号发起，确认后另发新件并保留
   父出档号链路。
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.services.handoff_material import (
    CORRECTION_CONFIRMED,
    CORRECTION_DRAFT,
    DISPATCH_ADOPTED,
    DISPATCH_DRAFT,
    DISPATCH_RETURNED,
    DISPATCH_SUPERSEDED,
    OPEN_TODO_STATUSES,
    SNAPSHOT_FIELDS,
    TODO_ADOPTED,
    TODO_CONFLICT,
    TODO_PENDING,
    TODO_RETURNED,
    TODO_SUPERSEDED,
    build_dispatch_record,
    build_snapshot,
)
from app.store import store

# 出档与声明编辑共用同一把锁：保证「编辑修订」和「出档快照」串行化，
# 不会把两次修订的字段拼接进同一份出档件。
HANDOFF_LOCK = threading.RLock()

HANDOFF_MODULE = "grain_handoff"
CORRECTION_MODULE = "grain_correction"

DISPATCH_STATUSES = [DISPATCH_DRAFT, DISPATCH_ADOPTED, DISPATCH_RETURNED, DISPATCH_SUPERSEDED]

__all__ = [
    "HANDOFF_LOCK", "HANDOFF_MODULE", "CORRECTION_MODULE",
    "DISPATCH_DRAFT", "DISPATCH_ADOPTED", "DISPATCH_RETURNED",
    "DISPATCH_SUPERSEDED", "DISPATCH_STATUSES",
    "TODO_PENDING", "TODO_CONFLICT", "TODO_ADOPTED", "TODO_RETURNED",
    "TODO_SUPERSEDED", "OPEN_TODO_STATUSES",
    "CORRECTION_DRAFT", "CORRECTION_CONFIRMED", "SNAPSHOT_FIELDS",
    "GrainHandoffService", "handoff_service",
]


class GrainHandoffService:
    """粒度声明交接副本与汇总层签收待办的领域服务（独立于通用资源骨架）。"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _dispatches(self) -> list[dict[str, Any]]:
        return store.rows(HANDOFF_MODULE)

    def _corrections(self) -> list[dict[str, Any]]:
        return store.rows(CORRECTION_MODULE)

    def _find_declaration(self, declare_id: str) -> dict[str, Any] | None:
        for row in store.rows("grain_declare"):
            if row.get("声明编号") == declare_id:
                return row
        return None

    def _find_dispatch(self, handoff_no: str) -> dict[str, Any] | None:
        for row in self._dispatches():
            if row.get("出档号") == handoff_no:
                return row
        return None

    def _set_todo_status(self, row: dict[str, Any], todo_status: str) -> None:
        """统一更新待办状态，并同步通用资源骨架依赖的 status/pending/abnormal。"""
        row["todo_status"] = todo_status
        row["status"] = todo_status
        row["pending"] = todo_status in OPEN_TODO_STATUSES
        row["abnormal"] = todo_status in (TODO_CONFLICT, TODO_RETURNED)

    def _snapshot(self, declaration: dict[str, Any]) -> dict[str, str]:
        return build_snapshot(declaration)

    def _next_serial(self, declare_id: str) -> int:
        prefix = f"HD-{declare_id}-"
        serials = [
            int(str(row["出档号"])[len(prefix):])
            for row in self._dispatches()
            if str(row.get("出档号", "")).startswith(prefix)
            and str(row["出档号"])[len(prefix):].isdigit()
        ]
        return max(serials, default=0) + 1

    def _build_dispatch(
        self, *, handoff_no: str, declare_id: str, revision: int,
        snapshot: dict[str, str], parent_no: str, issued_at: str,
    ) -> dict[str, Any]:
        next_id = max((int(r.get("id", 0)) for r in self._dispatches()), default=0) + 1
        return build_dispatch_record(
            handoff_no=handoff_no, declare_id=declare_id, revision=revision,
            snapshot=snapshot, parent_no=parent_no, issued_at=issued_at,
            next_id=next_id,
        )

    # ------------------------------------------------------------------
    # 出档（制单员，粒度声明侧）
    # ------------------------------------------------------------------
    def issue_dispatch(
        self, declare_id: str, remark: str = "", operator: str = "制单员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """把声明当日内容冻结成交接副本，并跨模块派生汇总层签收待办。"""
        with HANDOFF_LOCK:
            declaration = self._find_declaration(declare_id)
            if declaration is None:
                return False, f"粒度声明 {declare_id} 不存在，无法出档", None

            serial = self._next_serial(declare_id)
            handoff_no = f"HD-{declare_id}-{serial:02d}"
            revision = sum(
                1 for row in self._dispatches() if row.get("声明编号") == declare_id
            ) + 1
            snapshot = self._snapshot(declaration)
            dispatch = self._build_dispatch(
                handoff_no=handoff_no, declare_id=declare_id, revision=revision,
                snapshot=snapshot, parent_no="",
                issued_at=date.today().isoformat(),
            )
            if remark:
                dispatch["出档备注"] = remark
            dispatch["制单员"] = operator

            # 同一声明此前仍未决的待办统一进入「冲突待决」，记录冲突指向；
            # 已终结（已采用/已退回/已作废）的历史待办原样保留可回查。
            for older in self._dispatches():
                if older.get("声明编号") != declare_id:
                    continue
                if older.get("todo_status") in OPEN_TODO_STATUSES:
                    self._set_todo_status(older, TODO_CONFLICT)
                    older["冲突于"] = handoff_no
            self._dispatches().append(dispatch)
            return True, (
                f"交接副本 {handoff_no} 已出档并派生汇总层签收待办，"
                f"快照版本 {dispatch['快照版本']}，内容哈希 {dispatch['内容哈希']}"
            ), self.public_view(dispatch)

    def list_dispatches(
        self, *, declare_id: str | None = None, todo_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """出档件清单（粒度声明页查看），默认按出档时间倒序。"""
        with HANDOFF_LOCK:
            rows = list(self._dispatches())
            if declare_id:
                rows = [r for r in rows if r.get("声明编号") == declare_id]
            if todo_status:
                rows = [r for r in rows if r.get("todo_status") == todo_status]
            rows.sort(key=lambda r: str(r.get("出档号", "")), reverse=True)
            return [self.public_view(r) for r in rows]

    def get_dispatch(self, handoff_no: str) -> dict[str, Any] | None:
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            return self.public_view(row) if row else None

    def download_material(self, handoff_no: str) -> tuple[bytes, str] | None:
        """凭出档号取同一份离线材料；快照在出档时渲染，内容恒定。"""
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return None
            filename = f"{handoff_no}.html"
            return str(row["离线材料"]).encode("utf-8"), filename

    # ------------------------------------------------------------------
    # 签收待办（汇总员，汇总层派生侧）
    # ------------------------------------------------------------------
    def list_todos(
        self, *, declare_id: str | None = None, open_only: bool = False,
    ) -> list[dict[str, Any]]:
        """汇总层派生侧的签收待办：每个出档件派生一笔，一单一笔。"""
        with HANDOFF_LOCK:
            rows = list(self._dispatches())
            if declare_id:
                rows = [r for r in rows if r.get("声明编号") == declare_id]
            if open_only:
                rows = [r for r in rows if r.get("todo_status") in OPEN_TODO_STATUSES]
            rows.sort(key=lambda r: str(r.get("出档号", "")))
            return [self.todo_view(r) for r in rows]

    def adopt_dispatch(
        self, handoff_no: str, operator: str = "汇总员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """采用当前（无冲突）待签收副本：采用决定只绑定该出档号。"""
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return False, f"出档号 {handoff_no} 不存在", None
            status = row.get("todo_status")
            if status == TODO_ADOPTED:
                return False, f"出档号 {handoff_no} 已采用，不能重复采用", None
            if status not in OPEN_TODO_STATUSES:
                return False, f"出档号 {handoff_no} 当前为「{status}」，不能采用", None
            if status == TODO_CONFLICT:
                return False, (
                    f"出档号 {handoff_no} 与新出档 {row.get('冲突于')} 冲突待决，"
                    "须显式选择「采用旧口径」或「回到新副本」"
                ), None
            self._mark_adopted(row, operator)
            return True, f"已采用出档号 {handoff_no}（声明 {row['声明编号']}）", self.todo_view(row)

    def adopt_conflicted_legacy(
        self, handoff_no: str, operator: str = "汇总员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """冲突待决时采用旧口径：旧件采用，与之冲突的新待办登记去向后关闭。"""
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return False, f"出档号 {handoff_no} 不存在", None
            if row.get("todo_status") != TODO_CONFLICT:
                return False, f"出档号 {handoff_no} 不在冲突待决状态", None
            newer_no = row.get("冲突于", "")
            self._mark_adopted(row, operator)
            newer = self._find_dispatch(newer_no) if newer_no else None
            if newer is not None and newer.get("todo_status") in OPEN_TODO_STATUSES:
                self._set_todo_status(newer, TODO_SUPERSEDED)
                newer["dispatch_status"] = DISPATCH_SUPERSEDED
                # 新件不是被「采用」，只是登记去向后关闭：采用决定仍只挂在旧件上，
                # 操作人写进去向说明而不占用签收人字段，避免两版本共享一笔采用决定。
                newer["去向说明"] = (
                    f"{operator} 采用旧口径 {handoff_no}，本新件待办作废"
                )
                newer["决定时间"] = date.today().isoformat()
                newer["签收人"] = ""
            return True, (
                f"已按旧口径采用 {handoff_no}；新出档 {newer_no} 的待办已登记去向并作废"
            ), self.todo_view(row)

    def switch_to_newer(
        self, handoff_no: str, operator: str = "汇总员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """冲突待决时回到新副本：旧待办登记去向后作废，新待办恢复办理。"""
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return False, f"出档号 {handoff_no} 不存在", None
            if row.get("todo_status") != TODO_CONFLICT:
                return False, f"出档号 {handoff_no} 不在冲突待决状态", None
            newer_no = row.get("冲突于", "")
            newer = self._find_dispatch(newer_no) if newer_no else None
            if newer is None:
                return False, f"出档号 {handoff_no} 未找到对应的新出档件", None
            self._set_todo_status(row, TODO_SUPERSEDED)
            row["dispatch_status"] = DISPATCH_SUPERSEDED
            # 旧件是「回到新副本」的去向后作废，不是采用：签收人留空，
            # 操作人写进去向说明，避免与后续新件的采用决定混淆。
            row["去向说明"] = f"{operator} 回到新副本 {newer_no}，本旧件待办作废"
            row["决定时间"] = date.today().isoformat()
            row["签收人"] = ""
            if newer.get("todo_status") == TODO_CONFLICT:
                self._set_todo_status(newer, TODO_PENDING)
            return True, (
                f"旧出档 {handoff_no} 待办已登记去向并作废，请在新副本 {newer_no} 上继续签收"
            ), self.todo_view(newer)

    def return_dispatch(
        self, handoff_no: str, reason: str, operator: str = "汇总员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """退回当前待签收副本，必须登记具体原因，制单员据此发起补正。"""
        reason = (reason or "").strip()
        if not reason:
            return False, "退回必须登记具体原因", None
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return False, f"出档号 {handoff_no} 不存在", None
            status = row.get("todo_status")
            if status == TODO_CONFLICT:
                return False, (
                    f"出档号 {handoff_no} 冲突待决，须先「回到新副本」再退回新件"
                ), None
            if status != TODO_PENDING:
                return False, f"出档号 {handoff_no} 当前为「{status}」，不能退回", None
            today = date.today().isoformat()
            self._set_todo_status(row, TODO_RETURNED)
            row["dispatch_status"] = DISPATCH_RETURNED
            row["退回原因"] = reason
            row["签收人"] = operator
            row["决定时间"] = today
            return True, f"出档号 {handoff_no} 已退回并登记原因，待制单员补正", self.todo_view(row)

    def _mark_adopted(self, row: dict[str, Any], operator: str) -> None:
        self._set_todo_status(row, TODO_ADOPTED)
        row["dispatch_status"] = DISPATCH_ADOPTED
        row["签收人"] = operator
        row["决定时间"] = date.today().isoformat()
        row["去向说明"] = row.get("去向说明") or "汇总员签收采用，结果可回查"

    # ------------------------------------------------------------------
    # 补正（制单员，粒度声明侧）
    # ------------------------------------------------------------------
    def start_correction(
        self, handoff_no: str, note: str, operator: str = "制单员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """按被退回的出档号发起补正；同一退回件只允许一笔进行中的补正。"""
        note = (note or "").strip()
        if not note:
            return False, "发起补正必须填写补正说明", None
        with HANDOFF_LOCK:
            row = self._find_dispatch(handoff_no)
            if row is None:
                return False, f"出档号 {handoff_no} 不存在", None
            if row.get("todo_status") != TODO_RETURNED:
                return False, f"出档号 {handoff_no} 未被退回，不能发起补正", None
            # 一个被退回的出档号只允许一条补正链：进行中的补正拦截重复发起，
            # 已确认发新件的也不再受理，避免同一退回件挂多笔补正。
            existing = next(
                (c for c in self._corrections() if c.get("父出档号") == handoff_no),
                None,
            )
            if existing is not None:
                if existing.get("status") == CORRECTION_DRAFT:
                    return False, (
                        f"出档号 {handoff_no} 已有进行中的补正 {existing['补正编号']}"
                    ), None
                return False, (
                    f"出档号 {handoff_no} 的补正 {existing['补正编号']} 已发新件，"
                    "不能重复发起；如需继续修订请对新出档件走签收流程"
                ), None
            declare_id = str(row["声明编号"])
            # 补正编号按声明号独立编号（FX-<声明号>-NN），与出档号口径一致；
            # 内部 id 仍取全表最大值保证主键唯一。
            serial = self._next_correction_serial(declare_id)
            correction_no = f"FX-{declare_id}-{serial:02d}"
            correction = {
                "id": max((int(c.get("id", 0)) for c in self._corrections()), default=0) + 1,
                "补正编号": correction_no,
                "父出档号": handoff_no,
                "声明编号": declare_id,
                "补正说明": note,
                "status": CORRECTION_DRAFT,
                "pending": True,
                "abnormal": False,
                "新出档号": "",
                "制单员": operator,
                "创建时间": date.today().isoformat(),
            }
            self._corrections().append(correction)
            return True, f"补正 {correction_no} 已发起，确认后将另发新件并保留父出档号 {handoff_no}", correction

    def _next_correction_serial(self, declare_id: str) -> int:
        prefix = f"FX-{declare_id}-"
        serials = [
            int(str(c["补正编号"])[len(prefix):])
            for c in self._corrections()
            if str(c.get("补正编号", "")).startswith(prefix)
            and str(c["补正编号"])[len(prefix):].isdigit()
        ]
        return max(serials, default=0) + 1

    def confirm_correction(
        self, correction_no: str, operator: str = "制单员",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """确认补正：按声明最新内容另发新件，新件保留父出档号链路。"""
        with HANDOFF_LOCK:
            correction = next(
                (c for c in self._corrections() if c.get("补正编号") == correction_no), None,
            )
            if correction is None:
                return False, f"补正单 {correction_no} 不存在", None
            if correction.get("status") != CORRECTION_DRAFT:
                return False, f"补正单 {correction_no} 已确认，不能重复发件", None
            parent_no = str(correction["父出档号"])
            parent = self._find_dispatch(parent_no)
            declare_id = str(correction["声明编号"])
            declaration = self._find_declaration(declare_id)
            if parent is None or declaration is None:
                return False, "补正关联的出档件或粒度声明缺失", None

            serial = self._next_serial(declare_id)
            new_no = f"HD-{declare_id}-{serial:02d}"
            revision = sum(
                1 for r in self._dispatches() if r.get("声明编号") == declare_id
            ) + 1
            new_dispatch = self._build_dispatch(
                handoff_no=new_no, declare_id=declare_id, revision=revision,
                snapshot=self._snapshot(declaration), parent_no=parent_no,
                issued_at=date.today().isoformat(),
            )
            new_dispatch["制单员"] = operator
            new_dispatch["补正编号"] = correction_no
            for older in self._dispatches():
                if older.get("声明编号") != declare_id:
                    continue
                if older.get("todo_status") in OPEN_TODO_STATUSES:
                    self._set_todo_status(older, TODO_CONFLICT)
                    older["冲突于"] = new_no
            self._dispatches().append(new_dispatch)

            correction["status"] = CORRECTION_CONFIRMED
            correction["pending"] = False
            correction["新出档号"] = new_no
            parent["补正编号"] = correction_no
            return True, (
                f"补正 {correction_no} 已确认，另发新件 {new_no}，"
                f"父出档号 {parent_no} 已保留"
            ), self.public_view(new_dispatch)

    def list_corrections(self, *, handoff_no: str | None = None) -> list[dict[str, Any]]:
        with HANDOFF_LOCK:
            rows = list(self._corrections())
            if handoff_no:
                rows = [c for c in rows if c.get("父出档号") == handoff_no]
            rows.sort(key=lambda c: str(c.get("补正编号", "")), reverse=True)
            return [dict(c) for c in rows]

    # ------------------------------------------------------------------
    # 视图与离线材料
    # ------------------------------------------------------------------
    def todo_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """汇总层签收待办视图：一单一笔，冲突与去向两侧同源同规则。"""
        return {
            "出档号": row.get("出档号", ""),
            "声明编号": row.get("声明编号", ""),
            "快照版本": row.get("快照版本", ""),
            "出档修订": row.get("出档修订", ""),
            "父出档号": row.get("父出档号", ""),
            "待办状态": row.get("todo_status", ""),
            "冲突于": row.get("冲突于", ""),
            "退回原因": row.get("退回原因", ""),
            "签收人": row.get("签收人", ""),
            "去向说明": row.get("去向说明", ""),
            "出档时间": row.get("出档时间", ""),
            "决定时间": row.get("决定时间", ""),
            "内容哈希": row.get("内容哈希", ""),
        }

    def public_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """粒度声明页出档件视图（不含大块离线材料文本）。"""
        view = self.todo_view(row)
        view.update({
            "dispatch_status": row.get("dispatch_status", ""),
            "快照": dict(row.get("快照", {})),
            "补正编号": row.get("补正编号", ""),
            "制单员": row.get("制单员", ""),
        })
        return view


handoff_service = GrainHandoffService()
