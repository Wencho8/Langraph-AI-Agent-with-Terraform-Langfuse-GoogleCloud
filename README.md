# Agent Chatbot on Google Cloud

A small learning project: FastAPI, PostgreSQL/Alembic, ports and adapters, and an async LangGraph. The current iteration runs locally with a **simulated model**. It has no frontend, real authentication, real LLM calls, or cloud resources yet.

## Start locally

Requirements: Docker with Compose, and Make. Host Python is not required.

```sh
make start
make health
make chat MESSAGE='Hello'
make chat MESSAGE='Do you have my previous message?'
make history
make chat DEV_USER=bob MESSAGE='This is a different conversation'
```

`make start` creates an untracked `.env` from `.env.example` if missing, builds the image, starts PostgreSQL, explicitly applies Alembic migrations, seeds two local users, and starts the API. Migration/seed commands use temporary invocations of the backend image; only PostgreSQL and the backend remain running. Repeating startup preserves existing data.

API: [http://localhost:8088](http://localhost:8088). Interactive API documentation: [http://localhost:8088/docs](http://localhost:8088/docs).

If the port is occupied, change `API_PORT` in `.env` and run `make start` again. The Make chat/history commands work inside the backend container and do not depend on the host port.

## Commands

| Command | Action |
| --- | --- |
| `make start` | Build and start the complete local backend, including migrations and seed |
| `make build` | Build the backend image |
| `make stop` | Stop/remove service containers; keep the database volume |
| `make status` | Show service status |
| `make logs` | Follow backend logs |
| `make migrate` | Explicitly upgrade the database schema; PostgreSQL must be running |
| `make seed` | Ensure the local users exist; PostgreSQL must be running |
| `make chat MESSAGE='Hello'` | Send a message and print the SSE stream |
| `make history DEV_USER=bob` | Read a user's stored history |
| `make test` | Run tests in the running backend, using isolated databases in the existing PostgreSQL |

## Manual request

```sh
curl -N http://localhost:8088/v1/chat/messages \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User-Id: alice' \
  -d '{"message":"Hello from curl"}'
```

Events: `started`, one or more `delta` events, then `completed` after the final response is committed. A failure after streaming starts produces `error`; HTTP 200 alone does not mean the turn succeeded. Failures before streaming use HTTP error statuses.

Use `GET /v1/chat/messages` with the same header for history. The payload cannot select someone else's conversation. Each user has one conversation, and every saved message is passed to the graph on subsequent turns.

## Local identity

`X-Dev-User-Id` accepts `alice`, `bob`, or a seeded user's UUID:

- Alice: `11111111-1111-4111-8111-111111111111`
- Bob: `22222222-2222-4222-8222-222222222222`

**This header is not authentication.** The local adapter deliberately lets you act as either fixture user for manual testing. It requires explicit enablement and refuses production configuration. The API binds only to localhost; PostgreSQL has no published host port. Firebase authentication comes later.

## Structure

```text
backend/src/chatbot/
├── app.py                       # Composition and resource lifecycle
├── config.py                    # Validated environment configuration
├── domain/                      # Plain messages, turns, events, errors
├── application/                 # Ports and turn orchestration
└── adapters/
    ├── inbound/http/            # Routes, API schemas, SSE framing
    └── outbound/
        ├── postgres/            # Tables, repository, locks, local seed
        ├── agent/               # LangGraph and async simulated model
        ├── identity/            # Local principal resolution
        └── rate_limit/          # Local rolling-window limiter
```

`app.py` connects implementations. The orchestrator consumes ports and never imports FastAPI, SQLAlchemy, or LangGraph. The compiled graph is shared, but invocation state is isolated. Its current shape is `START -> model -> END` with native async incremental output; tools are deferred.

Alembic migrations live in `backend/migrations/`. Python 3.13 dependencies are managed by uv and pinned in `backend/uv.lock`. To update dependencies intentionally, run `uv lock` from `backend/` and rebuild. Tests are included in this development image; a cloud production image will be addressed later.

## Controls and limitations

- Four active turns per process by default; additional submissions receive HTTP 503.
- PostgreSQL advisory locks are keyed by user so even overlapping first messages are protected. A busy conversation receives HTTP 409. Dedicated lock connections remain outside long-running database transactions.
- The lock is checked during generation, and graph tasks are cancelled before releasing it. A lost database connection aborts the execution when detected; detection is not instantaneous, so future tools with side effects will need their own idempotency/fencing design.
- Local rate limit: 20 submissions per user per rolling minute, including rejected busy/saturated submissions. It resets on restart and must become shared before cloud deployment.
- Total turn timeout: 30 seconds. Model timeout: 20 seconds. One model call and graph recursion limit four. Values are configurable; history is never silently truncated.
- Complete assistant messages are persisted; partial streamed chunks are not. The user message and failed/cancelled turn remain recorded.
- A hard process crash can leave an `in_progress` record; automatic recovery and idempotent request retries are deferred. Retrying a message can create another turn.
- Logs include safe execution identifiers, status, timings, and call counts. Simulated token usage is reported as unavailable, not fabricated.
- Tests create/drop uniquely named databases in the **same PostgreSQL container**, with Alembic migrations. They do not truncate local chat data or create test containers. The local PostgreSQL role has the database-creation permission needed by these tests.

## Specifications

- [Project definitions](doc/definitions.md)
- [Iteration 01](specs/01-initial-backend-setup.md)
