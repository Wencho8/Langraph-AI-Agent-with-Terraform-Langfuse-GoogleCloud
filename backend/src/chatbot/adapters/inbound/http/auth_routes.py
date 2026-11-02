from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from chatbot.domain.errors import Forbidden, Unauthorized
from .auth_schemas import Login, Register

router = APIRouter(prefix="/v1/auth", tags=["authentication"])


def request_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise Unauthorized()
    return parts[1]


class AuthBodyLimit:
    """Bound even chunked auth bodies before JSON parsing; never buffer credentials here."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/v1/auth/') or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > 8192:
                raise HTTPException(413, 'Authentication request is too large')
            return message

        await self.app(scope, bounded_receive, send)


async def mutation_guard(request: Request):
    if (request.headers.get("origin") != request.app.state.settings.app_origin
            or request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json"):
        raise Forbidden()


def session_body(session):
    return {"user": {"id": str(session.user.id), "display_name": session.user.display_name,
                     "username": session.username, "is_admin": session.is_admin},
            "expires_at": session.expires_at.isoformat()}


def client_key(request):
    # Uvicorn's proxy-header handling is disabled; never trust arbitrary X-Forwarded-For.
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=201, dependencies=[Depends(mutation_guard)])
async def register(payload: Register, request: Request):
    await request.app.state.auth.register(
        payload.display_name, payload.username, payload.password.get_secret_value(),
        client_key(request), request_token(request),
    )
    return {"status": "pending_approval", "message": "Cuenta creada. Un administrador debe aprobarla antes de que puedas ingresar."}


@router.post("/login", dependencies=[Depends(mutation_guard)])
async def login(payload: Login, request: Request):
    grant = await request.app.state.auth.login(
        payload.username, payload.password.get_secret_value(), client_key(request), request_token(request),
    )
    return {**session_body(grant.session), "access_token": grant.token, "token_type": "Bearer"}


@router.get("/session")
async def session(request: Request):
    return session_body(await request.app.state.auth.resolve(request_token(request)))


@router.post("/logout", status_code=204, dependencies=[Depends(mutation_guard)])
async def logout(request: Request):
    token = request_token(request)
    await request.app.state.auth.resolve(token)
    await request.app.state.auth.logout(token)
    return Response(status_code=204)


class BlockAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocked: StrictBool


@router.get("/admin/users")
async def admin_users(request: Request, offset: int = Query(default=0, ge=0, le=1000000)):
    return await request.app.state.auth.list_accounts(request_token(request), offset)


@router.post("/admin/users/{user_id}/access", status_code=204, dependencies=[Depends(mutation_guard)])
async def admin_access(user_id: UUID, payload: BlockAccount, request: Request):
    await request.app.state.auth.set_blocked(request_token(request), user_id, payload.blocked)
    return Response(status_code=204)
