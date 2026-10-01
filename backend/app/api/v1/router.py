"""Aggregates every ``/api/v1`` router; feature routers are added per phase."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    assistant,
    audit,
    auth,
    bom,
    dashboard,
    inventory,
    materials,
    operations,
    production_orders,
    products,
    routing,
    users,
    work_centers,
)

FEATURE_ROUTERS = (
    auth,
    users,
    products,
    materials,
    work_centers,
    bom,
    routing,
    inventory,
    production_orders,
    operations,
    dashboard,
    admin,
    audit,
    assistant,
)

api_router = APIRouter()
for module in FEATURE_ROUTERS:
    api_router.include_router(module.router)
