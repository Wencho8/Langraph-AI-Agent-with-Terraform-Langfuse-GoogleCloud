# Agent Chatbot on Google Cloud

A small learning project: FastAPI, PostgreSQL/Alembic, ports and adapters, and an async LangGraph. The local backend supports a simulated model and **OpenAI Responses** with a finance-focused XML prompt. Frontend, real authentication, and cloud resources come later.

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

## Use OpenAI

The default provider is `simulated`: no key or model spending is needed. This mode checks streaming/history; it does not enforce the finance prompt semantically.

When ready, edit the **untracked** `.env` locally:

```dotenv
MODEL=openai:gpt-6.1-terra
OPENAI_API_KEY=your-key-here
MODEL_MAX_OUTPUT_TOKENS=2048
```

Run `make start` to apply the configuration, then try:

```sh
make chat MESSAGE='How can I build an emergency fund?'
make chat MESSAGE='What is my name?'
make chat MESSAGE='Who won the football match?'
make chat MESSAGE='Help me budget for football tickets'
make chat DEV_USER=bob MESSAGE='Hello! What is my name?'
make history
```

`MODEL` selects both provider and model: `simulated` for offline development or `openai:<model-id>` for a model available to your API project. The shorthand `MODEL=openai` selects `openai:gpt-6.1-terra`. Other non-empty model IDs are accepted without a code change; unsupported providers or empty IDs fail configuration validation. There is no automatic fallback after a provider error. Missing keys fail startup; model access, quotas, and prompt behavior are checked only when you send a real message. Startup, readiness, and `make test` make **no paid model requests**.

`MODEL` and `MODEL_MAX_OUTPUT_TOKENS` are normal configuration. Only `OPENAI_API_KEY` is a secret. Apply `.env` changes with `make start`.

The XML lives in `backend/src/chatbot/prompts/finance.xml`. It is loaded from the installed package and validated at startup. Instructions are sent separately from the user's name and conversation. Alice/Bob names come from PostgreSQL; no financial profile or memory is inferred. The normal tool registry is empty, and OpenAI receives no tool definitions or hosted tools.

`completed` includes provider/model, the prompt hash, actual call counts, and reported token usage. Missing usage stays unknown. A provider error after streaming starts is an SSE `error`, even if earlier deltas were shown. Partial answers never enter canonical assistant history.

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
├── application/                 # Ports, turn orchestration, tool registry
├── prompts/                     # Packaged finance.xml and validation/loader
└── adapters/
    ├── inbound/http/            # Routes, API schemas, SSE framing
    └── outbound/
        ├── postgres/            # Tables, repository, locks, local seed
        ├── agent/               # Async LangGraph model/tools loop
        ├── models/              # OpenAI, simulated model, provider factory
        ├── identity/            # Local principal resolution
        └── rate_limit/          # Local rolling-window limiter
```

`app.py` connects implementations and closes the shared async model client at shutdown. The orchestrator consumes ports and never imports FastAPI, SQLAlchemy, or LangGraph. The compiled graph is shared, but invocation state is isolated. Its shape is `START -> model -> END`, with a conditional `model -> tools -> model` loop ready for future tools. Tools execute sequentially after name/schema validation; test handlers exist only in tests.

One OpenAI adapter call performs one Responses request. LangGraph owns repeated model/tool rounds. Successful turns preserve an ordered provider transcript alongside canonical user/assistant text, including tool IDs and opaque continuation items. Loading history replays those items as model context without executing historical handlers or duplicating assistant text. Requests send full history with `store=false` and no provider-side conversation ID. This setting does not describe all provider retention policies.

Alembic migrations live in `backend/migrations/`. Python 3.13 dependencies are managed by uv and pinned in `backend/uv.lock`. To update dependencies intentionally, run `uv lock` from `backend/` and rebuild. Tests are included in this development image; a cloud production image will be addressed later.

## Controls and limitations

- Four active turns per process by default; additional submissions receive HTTP 503.
- PostgreSQL advisory locks are keyed by user so even overlapping first messages are protected. A busy conversation receives HTTP 409. Dedicated lock connections remain outside long-running database transactions.
- The lock is checked during generation, and graph tasks are cancelled before releasing it. A lost database connection aborts the execution when detected; detection is not instantaneous, so future tools with side effects will need their own idempotency/fencing design.
- Local rate limit: 20 submissions per user per rolling minute, including rejected busy/saturated submissions. It resets on restart and must become shared before cloud deployment.
- Defaults: total turn deadline 30 seconds, each model request 20 seconds, each future tool 5 seconds, at most 4 model calls, 8 tool calls, and graph recursion limit 12. Each OpenAI response allows at most 2048 output tokens, including reasoning tokens where applicable. SDK retries are disabled. Values are configurable; history is never silently truncated.
- Existing `.env` files are preserved by `make start`. If yours came from iteration 01, update `MAX_MODEL_CALLS=4` and `GRAPH_RECURSION_LIMIT=12` to adopt the new defaults. Smaller old limits still allow the normal one-model/no-tools flow.
- Complete assistant messages are persisted; partial streamed chunks are not. The user message and failed/cancelled turn remain recorded.
- A hard process crash can leave an `in_progress` record; automatic recovery and idempotent request retries are deferred. Retrying a message can create another turn.
- Logs include safe execution identifiers, provider/model, status, timings, call counts, request IDs, and actual token usage where reported. Prompts, profile names, tool payloads, API keys, and opaque reasoning items are not logged. Simulated usage is unavailable.
- Tests create/drop uniquely named databases in the **same PostgreSQL container**, with Alembic migrations. They do not truncate local chat data or create test containers. The local PostgreSQL role has the database-creation permission needed by these tests.
- Provider tests run the real async OpenAI SDK over mocked HTTP/SSE streams. They verify protocol handling, failures, cancellation, and continuation; they do not prove live model availability or finance-scope compliance.

## Specifications

- [Project definitions](doc/definitions.md)
- [Iteration 01](specs/01-initial-backend-setup.md)
- [Iteration 02](specs/02-openai-finance-agent.md)
- [Short request/concurrency flow](doc/request-flow.md)
