"""粒度声明交接副本路由：出档、签收待办、补正与离线材料下载。

路由层只做参数装配和 HTTP 适配，所有状态流转与冲突规则都在
``app.services.grain_handoff`` 领域服务内，遵守「路由层不做业务判断」约定。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import (
    ActionResult,
    CorrectionConfirmPayload,
    CorrectionStartPayload,
    GrainEditPayload,
    HandoffDecisionPayload,
    HandoffIssuePayload,
    HandoffReturnPayload,
)
from app.services.grain_declare import GrainDeclareService
from app.services.grain_handoff import handoff_service

router = APIRouter(prefix="/api/grain-handoff", tags=["粒度声明交接副本"])


def _result(ok: bool, message: str, entry: dict | None = None) -> ActionResult:
    return ActionResult(ok=ok, message=message, entry=entry)


# ---------------------------------------------------------------------------
# 汇总层派生侧：跨模块派生的签收待办
# ---------------------------------------------------------------------------
@router.get("/todos")
def list_todos(
    declare_id: str | None = Query(default=None),
    open_only: bool = Query(default=False),
) -> dict:
    """汇总员的签收待办：每个出档件派生一笔，按声明号可筛选。"""
    items = handoff_service.list_todos(declare_id=declare_id, open_only=open_only)
    return {"items": items, "total": len(items)}


@router.post("/dispatches/{handoff_no}/adopt", response_model=ActionResult)
def adopt_dispatch(handoff_no: str, payload: HandoffDecisionPayload) -> ActionResult:
    """采用当前待签收副本（无冲突时）。"""
    ok, message, entry = handoff_service.adopt_dispatch(
        handoff_no, operator=payload.operator or "汇总员")
    return _result(ok, message, entry)


@router.post("/dispatches/{handoff_no}/adopt-legacy", response_model=ActionResult)
def adopt_legacy(handoff_no: str, payload: HandoffDecisionPayload) -> ActionResult:
    """冲突待决：采用旧口径，新待办登记去向后关闭。"""
    ok, message, entry = handoff_service.adopt_conflicted_legacy(
        handoff_no, operator=payload.operator or "汇总员")
    return _result(ok, message, entry)


@router.post("/dispatches/{handoff_no}/switch-newer", response_model=ActionResult)
def switch_newer(handoff_no: str, payload: HandoffDecisionPayload) -> ActionResult:
    """冲突待决：回到新副本，旧待办登记去向后关闭。"""
    ok, message, entry = handoff_service.switch_to_newer(
        handoff_no, operator=payload.operator or "汇总员")
    return _result(ok, message, entry)


@router.post("/dispatches/{handoff_no}/return", response_model=ActionResult)
def return_dispatch(handoff_no: str, payload: HandoffReturnPayload) -> ActionResult:
    """退回副本并登记具体原因。"""
    ok, message, entry = handoff_service.return_dispatch(
        handoff_no, reason=payload.reason, operator=payload.operator or "汇总员")
    return _result(ok, message, entry)


# ---------------------------------------------------------------------------
# 粒度声明侧：制单员出档、补正、按出档号下载
# ---------------------------------------------------------------------------
@router.get("/dispatches")
def list_dispatches(
    declare_id: str | None = Query(default=None),
    todo_status: str | None = Query(default=None),
) -> dict:
    """声明页查看交接副本（出档件）清单。"""
    items = handoff_service.list_dispatches(declare_id=declare_id, todo_status=todo_status)
    return {"items": items, "total": len(items)}


@router.get("/dispatches/{handoff_no}")
def get_dispatch(handoff_no: str) -> dict:
    entry = handoff_service.get_dispatch(handoff_no)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"出档号 {handoff_no} 不存在")
    return entry


@router.post("/dispatches", response_model=ActionResult)
def issue_dispatch(payload: HandoffIssuePayload) -> ActionResult:
    """制单员出档：冻结当日声明快照并跨模块派生签收待办。"""
    ok, message, entry = handoff_service.issue_dispatch(
        payload.declare_id.strip(), remark=payload.remark or "",
        operator=payload.operator or "制单员")
    return _result(ok, message, entry)


@router.get("/dispatches/{handoff_no}/material")
def download_material(handoff_no: str) -> Response:
    """凭出档号下载同一份离线 HTML 材料，声明页与汇总页拿到的字节一致。"""
    loaded = handoff_service.download_material(handoff_no)
    if loaded is None:
        raise HTTPException(status_code=404, detail=f"出档号 {handoff_no} 不存在")
    content, filename = loaded
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/corrections")
def list_corrections(handoff_no: str | None = Query(default=None)) -> dict:
    items = handoff_service.list_corrections(handoff_no=handoff_no)
    return {"items": items, "total": len(items)}


@router.post("/corrections/start", response_model=ActionResult)
def start_correction(payload: CorrectionStartPayload) -> ActionResult:
    """制单员按被退回的出档号发起补正。"""
    ok, message, entry = handoff_service.start_correction(
        payload.handoff_no.strip(), note=payload.note,
        operator=payload.operator or "制单员")
    return _result(ok, message, entry)


@router.post("/corrections/{correction_no}/confirm", response_model=ActionResult)
def confirm_correction(correction_no: str, payload: CorrectionConfirmPayload) -> ActionResult:
    """确认补正：另发新件并保留父出档号。"""
    ok, message, entry = handoff_service.confirm_correction(
        correction_no, operator=payload.operator or "制单员")
    return _result(ok, message, entry)


# ---------------------------------------------------------------------------
# 粒度声明修订（与出档共用锁，防止两个修订拼接）
# ---------------------------------------------------------------------------
@router.post("/declarations/{declare_id}/edit", response_model=ActionResult)
def edit_declaration(declare_id: str, payload: GrainEditPayload) -> ActionResult:
    service = GrainDeclareService()
    ok, message, entry = service.edit_declaration(declare_id, payload.changes)
    return _result(ok, message, entry)
