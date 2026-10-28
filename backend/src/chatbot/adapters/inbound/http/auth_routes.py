import secrets

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from chatbot.domain.errors import Forbidden, Unauthorized
from .auth_schemas import Login, Register

router = APIRouter(prefix="/v1/auth", tags=["authentication"])
COOKIE = "__session"


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
    session = await request.app.state.auth.optional(request.cookies.get(COOKIE))
    if session is None and request.app.state.settings.auth_mode == "session" and request.url.path == "/v1/chat/messages":
        raise Unauthorized()
    if session is not None:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(csrf.encode(), session.csrf_token.encode()):
            raise Forbidden()
    request.state.auth_session = session


def session_body(session):
    return {"user": {"id": str(session.user.id), "display_name": session.user.display_name,
                     "username": session.username, "is_admin": session.is_admin}, "csrf_token": session.csrf_token,
            "expires_at": session.expires_at.isoformat()}


def set_session(response: Response, request: Request, grant):
    settings = request.app.state.settings
    response.set_cookie(COOKIE, grant.token, max_age=settings.session_ttl_seconds,
                        expires=grant.session.expires_at, httponly=True,
                        secure=settings.session_cookie_secure, samesite="lax", path="/")


def client_key(request):
    # Uvicorn's proxy-header handling is disabled; never trust arbitrary X-Forwarded-For.
    return request.client.host if request.client else "unknown"


@router.post("/register", status_code=201, dependencies=[Depends(mutation_guard)])
async def register(payload: Register, request: Request, response: Response):
    await request.app.state.auth.register(
        payload.display_name, payload.username, payload.password.get_secret_value(),
        client_key(request), request.cookies.get(COOKIE),
    )
    return {"status": "pending_approval", "message": "Cuenta creada. Un administrador debe aprobarla antes de que puedas ingresar."}


@router.post("/login", dependencies=[Depends(mutation_guard)])
async def login(payload: Login, request: Request, response: Response):
    grant = await request.app.state.auth.login(
        payload.username, payload.password.get_secret_value(), client_key(request), request.cookies.get(COOKIE),
    )
    set_session(response, request, grant)
    return session_body(grant.session)


@router.get("/session")
async def session(request: Request):
    return session_body(await request.app.state.auth.resolve(request.cookies.get(COOKIE)))


@router.post("/logout", status_code=204, dependencies=[Depends(mutation_guard)])
async def logout(request: Request):
    await request.app.state.auth.logout(request.cookies.get(COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", httponly=True,
                           secure=request.app.state.settings.session_cookie_secure, samesite="lax")
    return response


class BlockAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocked: StrictBool


@router.get("/admin/users")
async def admin_users(request: Request, offset: int = Query(default=0, ge=0, le=1000000)):
    return await request.app.state.auth.list_accounts(request.cookies.get(COOKIE), offset)


@router.post("/admin/users/{user_id}/access", status_code=204, dependencies=[Depends(mutation_guard)])
async def admin_access(user_id: UUID, payload: BlockAccount, request: Request):
    await request.app.state.auth.set_blocked(request.cookies.get(COOKIE), user_id, payload.blocked)
    return Response(status_code=204)
