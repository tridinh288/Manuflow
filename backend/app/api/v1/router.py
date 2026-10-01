"""Aggregates every ``/api/v1`` router; feature routers are added per phase."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    bom,
    inventory,
    materials,
    products,
    routing,
    users,
    work_centers,
)

api_router = APIRouter()
for module in (auth, users, products, materials, work_centers, bom, routing, inventory, admin):
    api_router.include_router(module.router)
