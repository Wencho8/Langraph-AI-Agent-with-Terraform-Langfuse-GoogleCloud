import logging
from time import monotonic
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from chatbot.adapters.inbound.http.routes import application_error, router
from chatbot.adapters.inbound.http.auth_routes import AuthBodyLimit, router as auth_router
from chatbot.adapters.outbound.identity.passwords import Argon2Passwords
from chatbot.adapters.outbound.postgres.auth import PostgresAuthRepository
from chatbot.adapters.outbound.rate_limit.auth import MemoryAuthLimiter
from chatbot.application.auth import AuthService
from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.adapters.outbound.models.factory import create_model
from chatbot.adapters.outbound.identity.development import DevelopmentIdentity
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
from chatbot.adapters.outbound.postgres.repository import PostgresConversationRepository
from chatbot.adapters.outbound.rate_limit.memory import MemoryRateLimiter
from chatbot.application.orchestrator import ChatOrchestrator, log_event
from chatbot.application.tools import ToolRegistry
from chatbot.config import Settings
from chatbot.domain.errors import ChatError
from chatbot.prompts.loader import load_prompt


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.database_url, settings.max_active_turns)
        model = None
        try:
            prompt = load_prompt()
            repository = PostgresConversationRepository(database)
            identity = (DevelopmentIdentity(repository, enabled=True, environment=settings.app_env)
                        if settings.auth_mode == "development" else None)
            try:
                await repository.ready()
            except ChatError as exc:
                raise RuntimeError("Database is not ready. Check the connection and run make migrate.") from exc
            model = create_model(settings)
            auth = AuthService(PostgresAuthRepository(database), Argon2Passwords(), MemoryAuthLimiter(),
                               ttl=settings.session_ttl_seconds, login_limit=settings.auth_login_limit,
                               registration_limit=settings.auth_registration_limit)
            await auth.initialize()
            app.state.auth = auth
            app.state.settings = settings
            agent = LangGraphAgent(
                model, prompt=prompt, tools=ToolRegistry(),
                max_model_calls=settings.max_model_calls, max_tool_calls=settings.max_tool_calls,
                recursion_limit=settings.graph_recursion_limit, model_timeout=settings.model_timeout_seconds,
                tool_timeout=settings.tool_timeout_seconds,
            )
            app.state.repository = repository
            app.state.identity = identity
            app.state.orchestrator = ChatOrchestrator(
                repository, PostgresConversationLock(database), agent,
                MemoryRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds),
                capacity=settings.max_active_turns, turn_timeout=settings.turn_timeout_seconds,
            )
            yield
        finally:
            try:
                if model is not None:
                    await model.close()
            finally:
                await database.close()

    app = FastAPI(title="Agent Chatbot — Local Backend", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(ChatError, application_error)
    app.add_middleware(AuthBodyLimit)

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request, exc):
        # FastAPI's default 422 includes input values, including passwords on model errors.
        errors = [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
        return JSONResponse({"code": "validation_error", "detail": errors}, status_code=422)

    @app.middleware("http")
    async def private_responses(request, call_next):
        started = monotonic()
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith('/v1/auth/'):
            log_event('auth_request', action=request.url.path.rsplit('/', 1)[-1], http_status=response.status_code,
                      duration_ms=round((monotonic() - started) * 1000, 2))
        return response

    app.include_router(router)
    app.include_router(auth_router)
    return app
