# Iteration 01 — Initial Backend Setup

Status: implemented and locally verified. See the repository README and Makefile for executable commands.

Project-wide decisions: [Definitions](../doc/definitions.md).

## Goal

Deliver a local backend that accepts a chat message, loads the user's complete conversation history, executes an async LangGraph with a deterministic simulated model, streams the response, and persists the completed exchange in PostgreSQL.

The backend must be understandable as one small application with ports and adapters. Docker Compose must provide a reproducible local environment, and pytest must verify the main behaviors.

## Scope

- Python, FastAPI, and Uvicorn with one worker process.
- PostgreSQL, async SQLAlchemy/asyncpg, and Alembic.
- A minimal user record and one conversation per user.
- A small application orchestrator and adapters for HTTP, persistence, identity, and agent execution.
- An async LangGraph and a deterministic simulated model.
- HTTP response streaming.
- Conversation locking and bounded execution.
- A local rate limiter, with an explicit replacement requirement before cloud deployment.
- Docker Compose, local configuration, and automated backend tests.
- Basic structured execution logs.

## Out of scope

- Frontend implementation.
- Registration, login screens, real Firebase Authentication, and password storage.
- Real LLM credentials or provider calls.
- Concrete tools, RAG, embeddings, and vector indexes.
- Google Cloud resources, Terraform implementation, and GitHub Actions workflows.
- Staging, backups, and restoration workflows.
- LangGraph checkpoints, resuming a graph after a process restart, and background jobs.

The simulated model and development identity are local adapters, not the eventual production authentication or model implementation.

## Initial data model

Create the user table in the first migration. Conversation ownership should be represented from the start, even though real registration and authentication come later.

The following schema is the proposed baseline for review. Exact SQLAlchemy mappings and migration details belong to implementation.

| Table | Purpose | Initial fields and constraints |
| --- | --- | --- |
| `users` | Application identity and ownership | UUID primary key; optional unique external authentication subject for future Firebase integration; creation timestamp. No password fields. |
| `conversations` | One persistent conversation per user | UUID primary key; user foreign key with a unique constraint; creation timestamp. |
| `turns` | Execution of one submitted user message | UUID primary key; conversation foreign key; ordered sequence number unique within the conversation; status; start/finish timestamps; optional safe error code. |
| `messages` | Canonical conversation history | UUID primary key; turn foreign key; position unique within the turn; role; content; creation timestamp. Initially support user and assistant roles. |

Use timezone-aware timestamps and deterministic ordering. Keep execution status on `turns`, separate from message text.

Turn statuses are `in_progress`, `completed`, `failed`, and `cancelled`. A process crash may leave a turn marked `in_progress`; the initial version must document this limitation rather than imply automatic recovery.

Tool-call persistence is deferred until tools are specified. The model should be extendable without creating unused tool or RAG tables now.

## Development identity

- Resolve the current user through an injectable identity boundary.
- For local development, use an explicitly enabled development adapter and documented fixture users.
- A development-only header such as `X-Dev-User-Id` may select a fixture user. This is a local convenience, not proof of authentication.
- Reject unknown users. Provision development users through an explicit local seed command or fixtures, not through an unauthenticated public registration endpoint.
- Refuse to enable this adapter outside the local/test environments.
- Resolve conversation ownership from the selected principal; do not accept an arbitrary conversation owner in the chat payload.
- Production Firebase token verification and user provisioning will replace this adapter in a later iteration.

## Architecture and responsibilities

Proposed logical organization:

| Component | Responsibility |
| --- | --- |
| Domain | Conversation, message, and turn concepts; statuses; application errors. No FastAPI or SQLAlchemy dependencies. |
| Application | Chat orchestrator and required port contracts. Coordinates one turn without constructing concrete adapters. |
| HTTP adapter | FastAPI routes, input validation, identity resolution, HTTP errors, and streaming serialization. |
| PostgreSQL adapters | Persistence, transaction handling, and conversation locking. |
| Agent adapter | Builds/invokes LangGraph and translates graph output into application streaming events. |
| Simulated model adapter | Produces deterministic async output without network calls or real credentials. |
| Composition root | Builds shared resources and injects adapters at startup; closes resources at shutdown. |

Create only the interfaces required by these boundaries. Avoid an abstract base class for every internal function or separate services for users, sessions, and agents.

## LangGraph behavior

- Start with `START -> model -> END` and an async model node.
- Inject the simulated model. It must expose enough deterministic behavior for tests to verify that prior messages reach the graph.
- Stream response chunks while the model node is executing; do not generate the full response and only then split it to imitate live streaming.
- Give each invocation its own state. Do not retain a user's messages in mutable graph or model instance fields shared with other users.
- Prefer a compiled graph reusable across invocations if the selected integration supports isolated concurrent state; otherwise construct it per invocation and document that choice.
- Use PostgreSQL conversation history as the source of truth. No LangGraph checkpointer is required in this iteration.
- Use async operations throughout the graph's I/O path. Do not create an event loop or dedicated thread for each message.
- Add the model/tools cycle in a later iteration once actual tools are defined. Do not create placeholder business tools now.

## Planned HTTP surface

| Endpoint | Behavior |
| --- | --- |
| `GET /health/live` | Confirms the process is running; does not query external dependencies. |
| `GET /health/ready` | Confirms startup and database readiness; returns an unavailable status if the backend cannot serve requests. |
| `GET /v1/chat/messages` | Returns the current user's saved messages in conversation order. Returns an empty list before their first turn. |
| `POST /v1/chat/messages` | Accepts a non-empty message for the current user and streams its response. |

Use a POST response with Server-Sent Events framing. Document how to consume it with an HTTP client; a browser frontend is not required.

The initial stream contract contains:

- `started`: the request has been accepted and identifies the conversation and turn.
- `delta`: a response text chunk.
- `completed`: the final assistant message and successful turn status have been committed.
- `error`: a terminal execution failure after streaming has started, with a safe error code and identifiers.

Errors detected before streaming starts use an appropriate HTTP status: validation errors, unknown development identity, `409` for a busy conversation, `429` for a rate limit, and `503` for admission saturation or unavailable dependencies. Once streaming has started, communicate execution failure through the stream rather than implying that HTTP `200` guarantees success.

## Turn lifecycle and persistence

1. Validate the payload and resolve the local identity.
2. Apply per-user rate limiting and execution admission control.
3. Acquire the conversation lock without waiting for another turn to finish.
4. Resolve or create that user's single conversation under the same coordination guarantee; concurrent first messages must not create two conversations or bypass locking.
5. Load all saved messages in order. Do not truncate, summarize, or introduce a history window.
6. Persist the new user message and an `in_progress` turn in a short transaction.
7. Invoke LangGraph with the complete history, the new message exactly once, and system instructions. Stream its response.
8. On success, persist the final assistant message and mark the turn `completed` in a short transaction before emitting `completed`.
9. On a handled failure or cancellation, mark the turn accordingly where storage is available. Never fabricate a successful assistant message.
10. Release the lock and admission slot on every handled exit path.

Streamed chunks are transient in this iteration. Store the canonical assistant message only when it is complete. On failure, retain the submitted user message and turn status; partial assistant text need not be persisted. All canonical messages remain part of subsequent history.

Do not keep a database transaction open while waiting for the model. Request retries are not automatically idempotent in this iteration; document that retrying a submitted message can create a new turn.

## Coordination and execution limits

- Use a shared PostgreSQL conversation lock, including stable coordination for a user's first message. A session-level advisory lock on a dedicated connection is the initial proposal; hold it for the turn and release it safely before returning the connection to its pool.
- Never perform a lock acquire/release through unrelated pooled connections. If connection or ownership is lost, stop the execution; do not continue as though exclusion were still guaranteed.
- Bound locking connections and database pools consistently with admitted execution capacity.
- Use a local in-memory per-user rate limiter behind a replaceable boundary. Its limits reset on restart and apply to one process only; replace it with shared coordination before cloud exposure.
- Configure maximum active turns, total turn timeout, simulated-model call timeout, and graph/model call limits. Numeric defaults must be selected before coding and tested; do not inherit the value 100 from the reference repository.
- Reject overlapping turns in the same conversation immediately. Different users must be able to progress concurrently.
- Cancel async work and clean up resources when the streaming client disconnects or the turn deadline expires.
- Verify cancellation before releasing coordination so an old model task cannot continue alongside a newly accepted turn.
- Define actual tool-call budgets when tools are introduced; this iteration has no executable tools.

## Local runtime and migrations

- Docker Compose runs the backend and PostgreSQL. No frontend service is required.
- PostgreSQL has a health check and a named volume. Data survives an ordinary Compose restart.
- Provide an explicit one-shot migration command/service for `alembic upgrade head`; application startup must not implicitly create tables with ORM metadata.
- Document the sequence for a clean database: start PostgreSQL, run migrations, seed development users, and start the backend.
- Provide untracked local configuration and a committed example with non-secret development placeholders.
- A missing configuration value or database schema must produce a clear startup/readiness failure.
- No personal Google Cloud account or model API key is required to run this iteration.

## Logging

- Emit structured logs with request/turn identifiers, result status, total duration, model-call duration, and time to first response chunk.
- Identify the model as simulated. Report token usage as unavailable or explicitly synthetic; do not label fabricated token counts as provider usage.
- Record lock contention, rate-limit rejections, timeouts, and admission saturation.
- Do not log conversation content, credentials, or authorization headers by default.

## Tests and acceptance criteria

Use pytest with async support. Tests that validate PostgreSQL behavior must run against a disposable test database, not SQLite or the developer's persistent database.

- A fresh database can be migrated to the current Alembic revision and receives the required tables and constraints. Re-running the upgrade is safe.
- Liveness and readiness distinguish a running process from a backend that cannot access its database.
- A fixture user can submit a message and receive ordered streaming events, including incremental deltas and a terminal completion.
- The saved history contains the user message and exactly one final assistant message for a successful turn.
- A second turn receives every prior canonical message and the new user message once.
- Users cannot read or modify another user's conversation through the HTTP interface.
- Concurrent users have isolated histories and can progress independently.
- Overlapping submissions for the same user/conversation receive a busy response, including concurrent first messages. Lock release works after success, error, timeout, and cancellation.
- Rate limiting, admission control, and execution limits produce the documented outcome and do not leak execution slots or locks.
- A persistence failure never produces a `completed` event. Partial output followed by an error is not presented as a committed assistant message.
- Restarting the application preserves committed messages in PostgreSQL.
- The development identity adapter cannot run in a non-local/non-test environment.

Document commands for running Compose, migrations, seed data, automated tests, and a manual streamed request. Tests must not require Google Cloud or a real model provider.

## Initial implementation decisions

- Four tables: `users`, `conversations`, `turns`, and `messages`.
- Explicitly enabled local identity with seeded Alice/Bob users; no real registration yet.
- Python 3.13, PostgreSQL 17, uv-managed dependencies and a committed lockfile.
- Four admitted turns per process, 20 submissions per user per rolling minute, 30-second total turn timeout, 20-second model timeout, one model call, and graph recursion limit four. These are conservative initial settings, not a measured capacity claim.
- PostgreSQL session-level advisory locks keyed by user, including concurrent first messages. Dedicated lock connections and short persistence transactions.
- Tests run in the existing backend container against separate temporary databases in the existing PostgreSQL service. No additional test containers.
- Make targets provide startup, builds, migrations, seed data, tests, chat, history, health, logs, and shutdown.

This iteration is complete when the local workflow and acceptance criteria above pass. Its output is a tested local backend; cloud provisioning and frontend work belong to later iterations.

## Local verification

- `make start`: image built, migrations applied, fixture users seeded, and both services healthy.
- `make test`: 12 tests passed against deterministic graph execution and isolated PostgreSQL test databases.
- Manual HTTP check: incremental streaming, same-session `409`, another user progressing concurrently, and lock release after a client disconnect.
- `make chat`, `make history`, and `make health`: exercised against the running backend.
- OpenAPI schema generation and persisted history after application recreation are covered by the test suite.

These checks validate the local iteration, not production capacity, real authentication, or a real model provider.
