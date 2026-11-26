"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class HandoffIssuePayload(BaseModel):
    declare_id: str
    remark: str | None = None
    operator: str | None = None


class HandoffReturnPayload(BaseModel):
    reason: str
    operator: str | None = None


class HandoffDecisionPayload(BaseModel):
    operator: str | None = None


class CorrectionStartPayload(BaseModel):
    handoff_no: str
    note: str
    operator: str | None = None


class CorrectionConfirmPayload(BaseModel):
    operator: str | None = None


class GrainEditPayload(BaseModel):
    changes: dict[str, Any] = Field(default_factory=dict)
