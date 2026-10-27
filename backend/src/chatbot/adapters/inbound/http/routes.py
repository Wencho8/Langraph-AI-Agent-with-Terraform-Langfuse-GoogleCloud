from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse

from chatbot.domain.errors import ChatError, Unavailable
from chatbot.domain.models import UserProfile
from .schemas import MessageResponse, SendMessage
from .streaming import ChatStreamingResponse

router = APIRouter()


async def current_user(request: Request, x_dev_user_id: str | None = Header(default=None)) -> UserProfile:
    return await request.app.state.identity.resolve(x_dev_user_id)


@router.get("/health/live")
async def live():
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(request: Request):
    try:
        await request.app.state.repository.ready()
    except Unavailable:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}


@router.get("/v1/chat/messages", response_model=list[MessageResponse])
async def history(request: Request, user: UserProfile = Depends(current_user)):
    return await request.app.state.orchestrator.history(user.id)


@router.post(
    "/v1/chat/messages", response_class=ChatStreamingResponse, status_code=200,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE chat response"}},
)
async def send_message(payload: SendMessage, request: Request, user: UserProfile = Depends(current_user)):
    execution = await request.app.state.orchestrator.open(user, payload.message, str(uuid4()))
    return ChatStreamingResponse(execution)


async def application_error(request: Request, error: ChatError):
    from chatbot.application.orchestrator import log_event

    status = {
        "unknown_user": 401, "session_busy": 409, "rate_limited": 429,
        "runtime_saturated": 503, "dependency_unavailable": 503,
        "turn_timeout": 504,
        "provider_authentication": 502, "provider_rate_limited": 503,
        "provider_unavailable": 503, "provider_rejected": 502,
        "context_limit": 422, "output_limit": 502,
    }.get(error.code, 500)
    log_event("request_rejected", code=error.code, http_status=status)
    return JSONResponse({"code": error.code, "message": error.message}, status_code=status)
