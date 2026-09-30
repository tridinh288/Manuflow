from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.access import require
from app.api.deps import get_request_context, get_user_service
from app.core.permissions import Permission
from app.schemas.common import DEFAULT_LIMIT, Limit, Offset, Page
from app.schemas.users import UserCreateRequest, UserResponse, UserUpdateRequest
from app.services.auth_service import AuthenticatedUser
from app.services.context import RequestContext
from app.services.user_service import NewUser, UserService, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

UserManager = Annotated[AuthenticatedUser, Depends(require(Permission.USERS_MANAGE))]
Service = Annotated[UserService, Depends(get_user_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.get("")
def list_users(
    _: UserManager, service: Service, limit: Limit = DEFAULT_LIMIT, offset: Offset = 0
) -> Page[UserResponse]:
    users, total = service.list_users(limit, offset)
    return Page(items=[UserResponse.model_validate(u) for u in users], total=total)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateRequest, admin: UserManager, service: Service, context: Context
) -> UserResponse:
    user = service.create_user(
        NewUser(
            username=body.username,
            password=body.password,
            full_name=body.full_name,
            role=body.role,
            work_center_id=body.work_center_id,
        ),
        admin.actor,
        context,
    )
    return UserResponse.model_validate(user)


@router.patch("/{user_id}")
def update_user(
    user_id: int, body: UserUpdateRequest, admin: UserManager, service: Service, context: Context
) -> UserResponse:
    update = UserUpdate(provided=frozenset(body.model_fields_set), **body.model_dump())
    return UserResponse.model_validate(service.update_user(user_id, update, admin.actor, context))
