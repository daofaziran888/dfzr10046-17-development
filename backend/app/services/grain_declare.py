"""粒度声明领域服务：声明事实表业务粒度数据集和度量可加性，校验聚合转换规则。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.base import BaseModuleService
from app.services.grain_handoff import HANDOFF_LOCK
from app.store import store


class GrainDeclareService(BaseModuleService):
    MODULE = "grain_declare"
    ENTITY = "粒度声明"
    LIST_FIELDS = ["声明编号", "所属事实表", "一行代表", "维度组合", "度量可加性", "重复判定键", "声明版本", "最近核对"]
    REQUIRED_FIELDS = ["声明编号", "所属事实表", "一行代表"]
    STATUS_ORDER = ["草稿", "已声明", "待修订", "已作废"]
    ACTION_RULES = {"确认声明": "已声明", "提交修订": "待修订", "作废声明": "已作废"}
    NEGATIVE_ACTIONS = []

    # 允许制单员在声明页直接修订的业务字段
    EDITABLE_FIELDS = ["一行代表", "维度组合", "度量可加性", "重复判定键", "声明版本"]

    def declare_grain(
        self, declare_id: str, fact_table: str, one_row_means: str,
        dim_combo: str, additivity: str, dedup_key: str, version: str,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """声明事实表粒度：一行代表 + 维度组合 + 度量可加性。"""
        rows = store.rows(self.MODULE)
        entry = {
            "声明编号": declare_id, "所属事实表": fact_table,
            "一行代表": one_row_means, "维度组合": dim_combo,
            "度量可加性": additivity, "重复判定键": dedup_key,
            "声明版本": version, "最近核对": date.today().isoformat(),
            "status": "已声明", "pending": False, "abnormal": False,
        }
        entry["id"] = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        rows.append(entry)
        return True, f"粒度声明 {declare_id} 已生效：{one_row_means}", entry

    def revise_grain(self, declare_id: str, new_dims: str) -> tuple[bool, str]:
        """修订粒度声明：触发汇总层重算与下游引用更新。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("声明编号") == declare_id:
                r["status"] = "待修订"
                r["维度组合"] = new_dims
                r["pending"] = True
                return True, f"粒度声明 {declare_id} 已提交修订：{new_dims}"
        return False, f"粒度声明 {declare_id} 不存在"

    def edit_declaration(
        self, declare_id: str, changes: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """制单员在声明页修订声明内容。

        与出档共用 HANDOFF_LOCK：编辑与出档串行执行，出档快照要么取修订前、
        要么取修订后的完整内容，绝不会把两个修订拼接进同一份出档件。
        已作废的声明不允许再编辑。
        """
        changes = {
            key: value for key, value in (changes or {}).items()
            if key in self.EDITABLE_FIELDS and str(value or "").strip()
        }
        if not changes:
            return False, "没有可修订的有效字段", None
        with HANDOFF_LOCK:
            for row in store.rows(self.MODULE):
                if row.get("声明编号") != declare_id:
                    continue
                if row.get("status") == "已作废":
                    return False, f"粒度声明 {declare_id} 已作废，不能再修订", None
                before = {key: row.get(key, "") for key in changes}
                for key, value in changes.items():
                    row[key] = value
                row["status"] = "待修订"
                row["pending"] = True
                row["最近核对"] = date.today().isoformat()
                row["最近修订"] = "；".join(
                    f"{key}：{before[key]}→{changes[key]}" for key in changes
                )
                return True, f"粒度声明 {declare_id} 已修订 {len(changes)} 个字段", row
            return False, f"粒度声明 {declare_id} 不存在", None
