"""业务路由汇总：交接副本专用路由与模块通用资源路由。

handoff 路由的前缀是固定的 /api/grain-handoff/...，先注册可避免被
通用资源路由 /api/{module} 的动态段抢先匹配。
"""
from __future__ import annotations

from app.routers import handoff, resource

ROUTERS = [handoff, resource]
