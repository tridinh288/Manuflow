"""Phase 9 assistant (B17). Any signed-in user may ask; each tool then checks the same
permission as the matching REST endpoint (BR-AI-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.access import require_authenticated
from app.api.deps import get_assistant_service
from app.core.config import Settings
from app.schemas.assistant import AskRequest, AskResponse, AssistantStatusResponse
from app.services.assistant_service import AssistantService
from app.services.auth_service import AuthenticatedUser

router = APIRouter(prefix="/assistant", tags=["assistant"])

User = Annotated[AuthenticatedUser, Depends(require_authenticated)]
Service = Annotated[AssistantService, Depends(get_assistant_service)]


@router.get("/status")
def assistant_status(_: User, request: Request, service: Service) -> AssistantStatusResponse:
    """Whether the assistant is configured; the UI hides it otherwise."""
    settings: Settings = request.app.state.settings
    enabled = request.app.state.chat_model is not None
    return AssistantStatusResponse(
        enabled=enabled,
        provider=settings.assistant_provider,
        model=settings.assistant_model if enabled else None,
        tools=[spec["name"] for spec in service.tool_specs()],
    )


@router.post("/ask")
def ask(body: AskRequest, user: User, service: Service) -> AskResponse:
    """Answer from read-only tools run as the caller; 503 ASSISTANT_DISABLED without a key."""
    return AskResponse.of(service.ask(body.question, user))
