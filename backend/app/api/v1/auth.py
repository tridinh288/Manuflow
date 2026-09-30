from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, get_auth_service, get_request_context
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse
from app.services.auth_service import AuthService
from app.services.context import RequestContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    body: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> TokenResponse:
    token = auth_service.login(body.username, body.password, context)
    return TokenResponse(access_token=token.access_token, expires_in=token.expires_in)


@router.get("/me")
def me(user: CurrentUser) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        work_center_id=user.work_center_id,
        permissions=sorted(user.permissions),
    )
