import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chatbot.adapters.inbound.http.routes import application_error, router
from chatbot.adapters.outbound.agent.graph import LangGraphAgent
from chatbot.adapters.outbound.agent.simulated_model import SimulatedModel
from chatbot.adapters.outbound.identity.development import DevelopmentIdentity
from chatbot.adapters.outbound.postgres.database import Database
from chatbot.adapters.outbound.postgres.locks import PostgresConversationLock
from chatbot.adapters.outbound.postgres.repository import PostgresConversationRepository
from chatbot.adapters.outbound.rate_limit.memory import MemoryRateLimiter
from chatbot.application.orchestrator import ChatOrchestrator
from chatbot.config import Settings
from chatbot.domain.errors import ChatError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(settings.database_url, settings.max_active_turns)
        try:
            repository = PostgresConversationRepository(database)
            identity = DevelopmentIdentity(
                repository, enabled=settings.dev_identity_enabled, environment=settings.app_env
            )
            try:
                await repository.ready()
            except ChatError as exc:
                raise RuntimeError("Database is not ready. Check the connection and run make migrate.") from exc
            agent = LangGraphAgent(
                SimulatedModel(settings.simulated_chunk_delay_seconds),
                max_model_calls=settings.max_model_calls, recursion_limit=settings.graph_recursion_limit,
            )
            app.state.repository = repository
            app.state.identity = identity
            app.state.orchestrator = ChatOrchestrator(
                repository, PostgresConversationLock(database), agent,
                MemoryRateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds),
                capacity=settings.max_active_turns, turn_timeout=settings.turn_timeout_seconds,
                model_timeout=settings.model_timeout_seconds,
            )
            yield
        finally:
            await database.close()

    app = FastAPI(title="Agent Chatbot — Local Backend", version="0.1.0", lifespan=lifespan)
    app.add_exception_handler(ChatError, application_error)
    app.include_router(router)
    return app
