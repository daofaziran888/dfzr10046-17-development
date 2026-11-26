"""粒度声明交接副本的纯函数：快照、内容哈希与离线凭据渲染。

刻意不依赖 ``app.store`` 或领域服务，避免 seed → store → service → store
的循环导入；种子数据与运行时出档共用同一份构造逻辑，保证结构一致。
"""
from __future__ import annotations

import hashlib
import html
import json
from typing import Any

# 出档件 / 签收待办生命周期
DISPATCH_DRAFT = "待签收"
DISPATCH_ADOPTED = "已采用"
DISPATCH_RETURNED = "已退回"
DISPATCH_SUPERSEDED = "已作废"

TODO_PENDING = "待签收"
TODO_CONFLICT = "冲突待决"
TODO_ADOPTED = "已采用"
TODO_RETURNED = "已退回"
TODO_SUPERSEDED = "已作废"
OPEN_TODO_STATUSES = {TODO_PENDING, TODO_CONFLICT}

# 补正单生命周期
CORRECTION_DRAFT = "补正中"
CORRECTION_CONFIRMED = "已发新件"

# 快照固定采集的声明字段，保证出档内容不随后续编辑漂移
SNAPSHOT_FIELDS = [
    "声明编号", "所属事实表", "一行代表", "维度组合", "度量可加性",
    "重复判定键", "声明版本", "最近核对",
]


def build_snapshot(declaration: dict[str, Any]) -> dict[str, str]:
    """从粒度声明行抽取固定字段，形成不可变快照。"""
    return {field: str(declaration.get(field, "")) for field in SNAPSHOT_FIELDS}


def content_hash_of(snapshot: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def render_material(handoff_no: str, snapshot: dict[str, str], issued_at: str) -> str:
    """渲染自包含 HTML 交接凭据：内联样式、无外部依赖，可离线打开。"""
    rows_html = "\n".join(
        "<tr><th>{label}</th><td>{value}</td></tr>".format(
            label=html.escape(label),
            value=html.escape(str(snapshot.get(label, "—")) or "—"),
        )
        for label in SNAPSHOT_FIELDS
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>粒度声明交接副本 {html.escape(handoff_no)}</title>
<style>
  body {{ font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; margin: 32px; color: #1f2937; }}
  .seal {{ border: 2px solid #1f6feb; border-radius: 10px; padding: 24px; max-width: 820px; margin: 0 auto; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: #64748b; font-size: 13px; margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ border: 1px solid #d8dee6; padding: 8px 10px; font-size: 13px; text-align: left; }}
  th {{ width: 160px; background: #f6f8fb; }}
  .sign {{ margin-top: 24px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .sign div {{ border-top: 1px dashed #94a3b8; padding-top: 8px; font-size: 13px; }}
  .foot {{ margin-top: 20px; color: #b42318; font-size: 12px; }}
</style>
</head>
<body>
  <section class="seal">
    <h1>粒度声明交接副本（交付凭据）</h1>
    <p class="meta">
      出档号：{html.escape(handoff_no)}　|　出档日期：{html.escape(issued_at)}　|
      凭据性质：离线自包含文件，无需联网即可打开核对
    </p>
    <table>
      <tbody>
{rows_html}
      </tbody>
    </table>
    <div class="sign">
      <div>汇总员签收：________________</div>
      <div>签收日期：________________</div>
      <div>处理结论：□ 采用　□ 退回（原因另附）</div>
      <div>核对声明号 / 出档号：{html.escape(str(snapshot.get('声明编号', '')))} / {html.escape(handoff_no)}</div>
    </div>
    <p class="foot">
      本副本为出档当日冻结快照，后续声明修订不改变本文件内容；凭出档号
      {html.escape(handoff_no)} 在系统内下载到的始终是同一份材料。
    </p>
  </section>
</body>
</html>
"""


def build_dispatch_record(
    *, handoff_no: str, declare_id: str, revision: int,
    snapshot: dict[str, str], parent_no: str, issued_at: str,
    next_id: int,
) -> dict[str, Any]:
    """构造一条出档件记录（不含 store 依赖），供领域服务与种子数据共用。"""
    return {
        "id": next_id,
        "出档号": handoff_no,
        "声明编号": declare_id,
        "出档修订": revision,
        "父出档号": parent_no,
        "快照版本": snapshot.get("声明版本", ""),
        "快照": snapshot,
        "内容哈希": content_hash_of(snapshot),
        "离线材料": render_material(handoff_no, snapshot, issued_at),
        "签收人": "",
        "退回原因": "",
        "去向说明": "",
        "冲突于": "",
        "dispatch_status": DISPATCH_DRAFT,
        "todo_status": TODO_PENDING,
        "status": TODO_PENDING,
        "pending": True,
        "abnormal": False,
        "出档时间": issued_at,
        "决定时间": "",
    }
