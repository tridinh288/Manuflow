"""Aggregates every ``/api/v1`` router; feature routers are added per phase."""

from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter()
api_router.include_router(auth.router)
