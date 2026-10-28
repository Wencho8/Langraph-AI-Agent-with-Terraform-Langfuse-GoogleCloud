# Agent Chatbot on Google Cloud

A small learning project: FastAPI, PostgreSQL/Alembic, ports and adapters, async LangGraph, and a React + TypeScript + Vite + Tailwind chat UI. Username authentication uses Argon2id and revocable database sessions. Models can be simulated or OpenAI Responses. Cloud provisioning comes later.

## Start locally

Requirements: Docker with Compose, Make, and Python 3 for the small local configuration/CLI helpers. Node and Python backend dependencies run inside Docker.

```sh
make start
make health
make test
```

Open [http://localhost:5173](http://localhost:5173), create an account with name/username/password/repeated password, and chat. Passwords require 15–128 characters; usernames use 3–32 letters, digits, dots, underscores or hyphens. Reload to check history; logout/login to check session handling. The name is LLM profile context; the username identifies login.

`make start` initializes separate ignored env files, builds both images, starts PostgreSQL, explicitly migrates the schema, seeds optional development users, and starts backend/frontend. Migration/seed commands reuse the backend image; only the three normal application services remain running. Data survives ordinary restarts. A legacy root `.env` is moved into the new locations with its model key preserved; values are never printed.

API: [http://localhost:8088](http://localhost:8088). Interactive API documentation: [http://localhost:8088/docs](http://localhost:8088/docs).

If a local port is occupied, change `API_PORT` in `backend/.env` or `FRONTEND_PORT` in `frontend/.env`. When changing the frontend port, also update backend `APP_ORIGIN` to its exact browser URL and run `make start`.

## Configuration by component and environment

- `backend/.env` / `backend/.env.example`: authentication, session policy, model/key, database and local API/Compose configuration. The real file is ignored and excluded from the Docker build.
- `frontend/.env` / `frontend/.env.example`: local frontend port. API requests use the same-origin `/v1` path. Frontend configuration must never contain server secrets; any future `VITE_*` values are public build inputs.
- Make passes both files explicitly to Compose; the root `.env` is no longer used.

| Setting | Local development | Future staging/production |
| --- | --- | --- |
| `FRONTEND_PORT` | Local Vite port, default `5173` | Not used by Firebase Hosting |
| `API_PORT` | Host mapping to backend container, default `8088` | Not used as a host port; Cloud Run routes to the container port (currently `8080`) |
| `APP_ORIGIN` | Backend validates `http://localhost:5173` | Set the actual frontend HTTPS origin separately for each environment |
| `APP_ENV` / `AUTH_MODE` | `local` / `session` | `production` / `session`; development identity is refused |
| `SESSION_COOKIE_SECURE` | `false` only for local HTTP | Must be `true` |
| Session lifetime/auth limits | Defaults work; override only when needed | Configurable policy; no need to redeclare unchanged defaults |
| Model/database credentials | Ignored backend env file | Secret Manager/runtime configuration, never frontend files |

Production configuration rejects an HTTP origin, insecure cookie, or development identity. Cloud resources and deployment configuration are not provisioned by this iteration.

## Commands

| Command | Action |
| --- | --- |
| `make start` | Build/start frontend, backend and PostgreSQL, including migrations |
| `make build` | Build frontend and backend images |
| `make stop` | Stop/remove service containers; keep the database volume |
| `make status` | Show service status |
| `make logs` | Follow frontend/backend logs |
| `make migrate` | Explicitly upgrade the database schema; PostgreSQL must be running |
| `make seed` | Ensure the local users exist; PostgreSQL must be running |
| `make login` / `make logout` | Interactive CLI login / server-side revocation of its session |
| `make chat MESSAGE='Hello'` | Send a message using your CLI session and print SSE |
| `make history` | Read history for the CLI session's user |
| `make test` | Backend/frontend tests and frontend typecheck/production build |
| `make backend-test` / `make frontend-test` | Run one component's tests |
| `make frontend-build` | Typecheck and build static assets in `frontend/dist` inside the container |

## CLI sessions and API

```sh
make login  # Prompts for credentials of an account created in the UI
make chat MESSAGE='How can I organize my expenses?'
make history
make logout
```

Events: `started`, one or more `delta` events, then `completed` after the final response is committed. A failure after streaming starts produces `error`; HTTP 200 alone does not mean the turn succeeded. Failures before streaming use HTTP error statuses.

The CLI keeps a private, ignored `.local/cookies.txt` file; passwords are prompted, not passed in command arguments. Browser and CLI login sessions are independent. Auth endpoints are `/v1/auth/register`, `/login`, `/session`, `/logout`. Session restore returns the public user and a CSRF token; the HttpOnly authentication cookie is never returned in JSON. Mutations require the exact configured Origin, JSON, and the active session's CSRF header.

`GET /v1/chat/messages` reads only the session user's history. Request bodies cannot select ownership. Every saved message is passed to the graph on subsequent turns. Session mode never falls back to development headers.

## Use OpenAI

The default provider is `simulated`: no key or model spending is needed. This mode checks streaming/history; it does not enforce the finance prompt semantically.

When ready, edit the **untracked** `backend/.env` locally:

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
make history
```

`MODEL` selects both provider and model: `simulated` for offline development or `openai:<model-id>` for a model available to your API project. The shorthand `MODEL=openai` selects `openai:gpt-6.1-terra`. Other non-empty model IDs are accepted without a code change; unsupported providers or empty IDs fail configuration validation. There is no automatic fallback after a provider error. Missing keys fail startup; model access, quotas, and prompt behavior are checked only when you send a real message. Startup, readiness, and `make test` make **no paid model requests**.

`MODEL` and `MODEL_MAX_OUTPUT_TOKENS` are normal configuration. `OPENAI_API_KEY` is a secret. Apply env changes with `make start`. Automated tests always select simulated/mocked providers. To manually test the UI without model spending while keeping your saved provider settings, use `MODEL=simulated make start`; a normal `make start` restores the saved selection.

The XML lives in `backend/src/chatbot/prompts/finance.xml`. It is loaded from the installed package and validated at startup. Instructions are sent separately from the user's display name and conversation. No financial profile or memory is inferred. The normal tool registry is empty, and OpenAI receives no tool definitions or hosted tools.

`completed` includes provider/model, the prompt hash, actual call counts, and reported token usage. Missing usage stays unknown. A provider error after streaming starts is an SSE `error`, even if earlier deltas were shown. Partial answers never enter canonical assistant history.

## Sessions and development identity

Normal mode is `AUTH_MODE=session`: Argon2id password verification, a 24-hour absolute session by default, and an opaque `__session` HttpOnly/SameSite cookie with only its verifier stored in PostgreSQL. Logout revokes that session on the server; other devices' sessions remain valid. Session validity is checked during generation on the existing 0.5-second watchdog with a bounded two-second database check. Detection includes scheduling/I/O delay; upstream cancellation is not instantaneous. Password work runs off the event loop with at most two admitted operations.

Login is limited to 10 attempts per minute per IP and username; registration to 5 per minute per IP. Limits are process-local and reset on restart. The local frontend proxy shares one source IP, so those IP limits are shared by local browser clients. Forwarded IP headers are not trusted; configure trusted ingress and shared limits before cloud deployment. Recovery/MFA/password changes and automatic expired-session cleanup are deferred.

For explicit local-only development, set `AUTH_MODE=development` in `backend/.env`, restart, then use `make chat/history DEV_USER=alice` or `bob`. The browser registration/chat flow requires session mode. `X-Dev-User-Id` accepts these optional fixtures or a known UUID:

- Alice: `11111111-1111-4111-8111-111111111111`
- Bob: `22222222-2222-4222-8222-222222222222`

**This header is not authentication.** The development adapter deliberately lets you act as fixture users and refuses production configuration. Fixtures have no default passwords; registered users receive new UUIDs and do not inherit fixture histories. APIs bind only to localhost; PostgreSQL has no published host port. Firebase Hosting is the future static frontend host; authentication remains in Python.

## Structure

```text
backend/src/chatbot/
├── app.py                       # Composition and resource lifecycle
├── config.py                    # Validated environment configuration
├── domain/                      # Plain messages, turns, events, errors
├── application/                 # Ports, auth/turn orchestration, tool registry
├── prompts/                     # Packaged finance.xml and validation/loader
└── adapters/
    ├── inbound/http/            # Routes, API schemas, SSE framing
    └── outbound/
        ├── postgres/            # Tables, auth/chat repositories, locks, local seed
        ├── agent/               # Async LangGraph model/tools loop
        ├── models/              # OpenAI, simulated model, provider factory
        ├── identity/            # Bounded Argon2 operations, development identity
        └── rate_limit/          # Local rolling-window limiter
```

`app.py` connects implementations and closes the shared async model client at shutdown. The orchestrator consumes ports and never imports FastAPI, SQLAlchemy, or LangGraph. The compiled graph is shared, but invocation state is isolated. Its shape is `START -> model -> END`, with a conditional `model -> tools -> model` loop ready for future tools. Tools execute sequentially after name/schema validation; test handlers exist only in tests.

One OpenAI adapter call performs one Responses request. LangGraph owns repeated model/tool rounds. Successful turns preserve an ordered provider transcript alongside canonical user/assistant text, including tool IDs and opaque continuation items. Loading history replays those items as model context without executing historical handlers or duplicating assistant text. Requests send full history with `store=false` and no provider-side conversation ID. This setting does not describe all provider retention policies.

The React/Tailwind UI lives in `frontend/src/{auth,chat,api}`. Vite proxies `/v1` to the backend locally; `npm run build` creates static assets without a production Vite server. Assistant messages render Markdown during streaming and from history, including emphasis, lists, code, and tables. Raw HTML and images are disabled; links retain safe URL handling. User messages remain escaped text. No authentication tokens are stored in browser local/session storage. The planned Hosting rewrite forwards the specially named `__session` cookie; private API responses use `Cache-Control: no-store`.

Alembic migrations live in `backend/migrations/`, including `0003_auth_sessions`. Python 3.13 dependencies are managed by uv; frontend dependencies use Node 24 and `package-lock.json`. Tests are included in these development images; production images and cloud configuration come later.

## Controls and limitations

- Four active turns per process by default; additional submissions receive HTTP 503.
- PostgreSQL advisory locks are keyed by user so even overlapping first messages are protected. A busy conversation receives HTTP 409. Dedicated lock connections remain outside long-running database transactions.
- The lock is checked during generation, and graph tasks are cancelled before releasing it. A lost database connection aborts the execution when detected; detection is not instantaneous, so future tools with side effects will need their own idempotency/fencing design.
- Local rate limit: 20 submissions per user per rolling minute, including rejected busy/saturated submissions. It resets on restart and must become shared before cloud deployment.
- Defaults: total turn deadline 30 seconds, each model request 20 seconds, each future tool 5 seconds, at most 4 model calls, 8 tool calls, and graph recursion limit 12. Each OpenAI response allows at most 2048 output tokens, including reasoning tokens where applicable. SDK retries are disabled. Values are configurable; history is never silently truncated.
- Existing component env files are preserved by `make start`. If your backend settings came from iteration 01, update `MAX_MODEL_CALLS=4` and `GRAPH_RECURSION_LIMIT=12` to adopt the newer defaults.
- Complete assistant messages are persisted; partial streamed chunks are not. The user message and failed/cancelled turn remain recorded.
- A hard process crash can leave an `in_progress` record; automatic recovery and idempotent request retries are deferred. Retrying a message can create another turn.
- Logs include safe execution identifiers, provider/model, status, timings, call counts, request IDs, and actual token usage where reported. Prompts, profile names, tool payloads, API keys, and opaque reasoning items are not logged. Simulated usage is unavailable.
- Tests create/drop uniquely named databases in the **same PostgreSQL container**, with Alembic migrations. They do not truncate local chat data or create test containers. The local PostgreSQL role has the database-creation permission needed by these tests.
- Provider tests run the real async OpenAI SDK over mocked HTTP/SSE streams. They verify protocol handling, failures, cancellation, and continuation; they do not prove live model availability or finance-scope compliance.

## Specifications

- [Project definitions](doc/definitions.md)
- [Iteration 01](specs/01-initial-backend-setup.md)
- [Iteration 02](specs/02-openai-finance-agent.md)
- [Iteration 03](specs/03-users-and-chat-ui.md)
- [Short request/concurrency flow](doc/request-flow.md)
