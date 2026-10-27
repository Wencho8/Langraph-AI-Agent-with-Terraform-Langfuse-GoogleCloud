import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chatbot.adapters.inbound.http.routes import application_error, router
from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.adapters.outbound.models.factory import create_model
from chatbot.adapters.outbound.identity.development import DevelopmentIdentity
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
from chatbot.adapters.outbound.postgres.repository import PostgresConversationRepository
from chatbot.adapters.outbound.rate_limit.memory import MemoryRateLimiter
from chatbot.application.orchestrator import ChatOrchestrator
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
            identity = DevelopmentIdentity(
                repository, enabled=settings.dev_identity_enabled, environment=settings.app_env
            )
            try:
                await repository.ready()
            except ChatError as exc:
                raise RuntimeError("Database is not ready. Check the connection and run make migrate.") from exc
            model = create_model(settings)
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
    app.include_router(router)
    return app
