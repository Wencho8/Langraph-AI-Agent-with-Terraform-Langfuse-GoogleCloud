# Agent Chatbot on Google Cloud — Definitions

Status: evolving project decisions. Iterations 01–03 implement the local backend, OpenAI integration, username authentication, and React chat UI. Iteration 04 deployed the backend and PostgreSQL with successful live/ready checks. Iteration 05 is functionally complete: Firebase Hosting is published and the user confirmed browser acceptance. Operational RAM/log/cost and rollback/teardown review remains pending. GitHub Actions is defined in 06. Iteration 07 adds IOL market tools and inline charts; staging remains optional later work.

## Purpose

Build a small AI chatbot to learn how to provision, deploy, and operate an application on Google Cloud. The main focus is DevOps: Terraform, Docker, GitHub Actions, cloud permissions, secrets, deployments, and observability.

The application should remain small enough to understand while providing a practical setting for these operational concerns.

The chatbot's initial domain is personal finance and financial education. It should keep answers within that scope and briefly redirect unrelated requests, such as general football questions, toward financial topics. Greetings and conversational follow-ups are allowed.

## Repository and scope

- Repository name: `agent-chatbot-gcloud`.
- Keep the Python backend, frontend, infrastructure definitions, and CI/CD workflows in the same repository.
- Maintain project-wide decisions in this document and iteration specifications in `specs/`.
- Iteration 01 covers the local backend; iteration 02 adds OpenAI; iteration 03 defines users and the frontend. Cloud infrastructure and deployment workflows remain deferred.
- Implement one backend application. Use internal modules and clear boundaries rather than separate microservices.

## Technology decisions

| Area | Decision |
| --- | --- |
| Backend | Python and FastAPI |
| HTTP server | Uvicorn, initially with one worker process per container |
| Agent execution | LangGraph |
| First real model provider | OpenAI Responses via the async SDK; configurable model, initially `gpt-6.1-terra` |
| Frontend | React + TypeScript + Vite + Tailwind CSS in `frontend/`; minimal auth/chat screens titled "Chatbot de finanzas" |
| Frontend hosting | Firebase Hosting |
| Authentication | Username/password verified in FastAPI; Argon2id password hashes and revocable PostgreSQL sessions in HttpOnly cookies; no email or Firebase Authentication |
| Database | PostgreSQL; local PostgreSQL during development and Cloud SQL for PostgreSQL in Google Cloud |
| Database access and migrations | Async SQLAlchemy with asyncpg, and Alembic migrations |
| Local environment | Docker Compose |
| Backend hosting | Cloud Run |
| Infrastructure | Terraform |
| CI/CD | GitHub Actions |
| Runtime secrets | Google Cloud Secret Manager |
| Backend tests | pytest, including support for async tests |

The backend uses Python 3.13 with dependencies pinned in `backend/uv.lock`. The frontend uses Node 24 with `frontend/package-lock.json`. Vite/Tailwind are development/build tooling; Firebase Hosting will serve the compiled static assets.

## Environments and cost

- Start with a single deployed environment named `production`.
- Add `staging` later by reusing the same Terraform modules and application artifacts, with separate environment configuration, data, and secrets.
- Configure the initial Cloud Run backend with a maximum of one instance and one Uvicorn worker per container.
- Initial Cloud Run configuration: `us-central1`, request-based billing, 1 vCPU, 512 MiB RAM, minimum zero and maximum one instance at service level, request concurrency eight, and request timeout 60 seconds. The application independently limits active chat turns to four. Verify actual RAM usage after deployment.
- Iteration 04 deployed Cloud SQL for PostgreSQL 17, Enterprise edition, `db-g1-small` (shared CPU, approximately 1.7 GiB RAM), 10 GiB SSD, and a single zone. Use public IP through a Cloud SQL connector without unrestricted direct database access.
- With minimum zero instances, Cloud Run can scale the backend to zero after inactivity and start it again on the next request; this can add cold-start latency. Database data and sessions persist in PostgreSQL. Cloud SQL does not automatically stop when Cloud Run scales to zero.
- Initially fund eligible Google Cloud usage with the available trial credit. The trial's remaining balance and expiration must be checked before deployment; it is not unlimited free usage for 90 days.
- Configure billing visibility and spending alerts. Do not treat alerts as an immediate spending cutoff.
- Backups and restoration workflows are outside the initial scope.

## User experience

1. A user registers with a display name, username, password, and matching password confirmation; no email.
2. New accounts have `blocked=true` and `is_admin=false`. An approved administrator approves accounts in a minimal user dashboard; pending login stays in the access form with an inline approval message. The first administrator is promoted manually through SQL. See [user approval](user-approval.md).
3. The user opens their single persistent conversation.
4. The user sends a message and receives a streamed response.
5. Previous messages remain available when the user returns.
6. The user signs out; the backend revokes the current login session and the UI clears its user/chat state.

The frontend should be intentionally simple. Authentication is a supporting feature, not the focus of the project.

The backend derives identity from a validated, unexpired, unrevoked session cookie. The username identifies the login account; the existing display name is what the LLM receives as profile context. Every conversation read, write, and execution must be authorized for that user. Cookie-based mutations require origin/CSRF protection; development identity never acts as a fallback in session mode.

During generation the composer/send action is disabled, and terminal events/errors release it. Server-side conversation locks remain authoritative across tabs/devices. Session restore loads the signed-in user's history; user switching must never retain the previous user's messages.

## Conversations and history

- The implemented tables are `users`, `conversations`, `turns`, `messages`, and `auth_sessions`. A conversation belongs to one user; it has many turns, and each turn has its user/final assistant messages.
- `auth_sessions` is for login lifecycle only. Authentication sessions do not replace conversations, turns, or their transcripts/metadata. Multiple login sessions can access one user's conversation; logout revokes only the current session.
- `turns.agent_transcript` stores that turn's internal model/tool sequence for future context reconstruction. `turns.execution_metadata` stores that turn's provider/model, prompt revision, usage, timings, and call counts. Both belong to an individual execution; user and conversation records do not aggregate or overwrite them.
- Maintain one persistent conversation per user.
- Store user and assistant messages in PostgreSQL.
- Load and send the entire stored conversation history to the model on each turn, together with the new message and system instructions.
- Do not introduce history windows, automatic summarization, or token-based history truncation in the initial version.
- Provider context limits still apply. If a request exceeds a provider limit, report the failure clearly rather than silently dropping history.
- Keep execution status separate from message text so an interrupted or failed response can be distinguished from a completed response.
- Once tools are implemented, preserve the tool calls and results required to reconstruct a valid model conversation.

## Application architecture

Use ports and adapters with a small application orchestrator and clear separation of responsibilities.

- **Inbound adapters:** expose application capabilities to callers. The HTTP adapter uses FastAPI routes for request validation, authentication integration, and streaming responses.
- **Application orchestrator:** coordinates conversation access, admission limits, locking, history loading, agent execution, and persistence.
- **Ports:** describe the capabilities the application needs, such as conversation persistence, agent execution, coordination, and rate limiting.
- **Outbound adapters:** implement the capabilities the application calls through its ports, such as PostgreSQL persistence, locks, agent execution, identity verification, and rate limiting.
- **Composition root:** creates and connects the concrete dependencies at application startup.

Keep the core application independent of concrete database and model-provider implementations. Add abstractions where there is an actual external boundary; keep the framework and service structure focused on this application's needs.

### Planned folder structure

Organize adapters by the direction in which the application is called or calls a dependency: `inbound/` receives calls into the application, while `outbound/` implements dependencies called by the application. Direction describes who initiates the operation, not whether data is being read or written.

```text
agent-chatbot-gcloud/
├── doc/
│   ├── definitions.md
│   └── request-flow.md
├── specs/
│   ├── 01-initial-backend-setup.md
│   ├── 02-openai-finance-agent.md
│   └── 03-users-and-chat-ui.md
├── frontend/
│   ├── .env.example
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
├── backend/
│   ├── .env.example
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   ├── src/
│   │   └── chatbot/
│   │       ├── app.py
│   │       ├── config.py
│   │       ├── domain/
│   │       │   ├── models.py
│   │       │   ├── agent.py
│   │       │   └── errors.py
│   │       ├── application/
│   │       │   ├── ports.py
│   │       │   ├── tools.py
│   │       │   └── orchestrator.py
│   │       ├── prompts/
│   │       │   ├── finance.xml
│   │       │   └── loader.py
│   │       └── adapters/
│   │           ├── inbound/
│   │           │   └── http/
│   │           │       ├── routes.py
│   │           │       ├── schemas.py
│   │           │       └── streaming.py
│   │           └── outbound/
│   │               ├── postgres/
│   │               │   ├── database.py
│   │               │   ├── models.py
│   │               │   ├── repository.py
│   │               │   └── locks.py
│   │               ├── agent/
│   │               │   └── graph.py
│   │               ├── models/
│   │               │   ├── factory.py
│   │               │   ├── openai.py
│   │               │   └── simulated.py
│   │               ├── identity/
│   │               │   └── development.py
│   │               └── rate_limit/
│   │                   └── memory.py
│   └── tests/
│       ├── test_orchestrator.py
│       ├── test_api.py
│       └── test_postgres.py
├── compose.yaml
├── .gitignore
├── Makefile
└── README.md
```

This is a target layout, not an instruction to scaffold every file immediately. Add files as their behavior is implemented. The frontend's small internal layout is defined in iteration 03; Terraform's layout remains deferred.

| Location | Responsibility |
| --- | --- |
| `app.py` | Composition root: construct the application, connect adapters, and manage resource startup/shutdown. |
| `config.py` | Parse and validate environment-specific configuration. |
| `domain/` | Plain application concepts and errors, without HTTP, ORM, or LangGraph dependencies. |
| `application/` | Port contracts and orchestration of a complete turn. Depends on the domain and contracts, not concrete adapters. |
| `adapters/inbound/http/routes.py` | Receive HTTP requests, resolve the caller through dependencies, call application use cases, and map application errors to HTTP responses. |
| `adapters/inbound/http/schemas.py` | Pydantic request/response models for the HTTP contract. These are distinct from domain objects and database tables. |
| `adapters/inbound/http/streaming.py` | Translate application response events into HTTP/SSE framing. The application does not construct FastAPI responses. |
| `adapters/outbound/postgres/` | SQLAlchemy mappings, database connections, repository implementation, and the candidate PostgreSQL lock implementation. |
| `adapters/outbound/agent/` | Implement the agent execution port with the async LangGraph model/tools loop. LangGraph is an outbound adapter because the application invokes it as a dependency, even though it runs inside the backend process. |
| `adapters/outbound/models/` | Implement one model request through the OpenAI or simulated adapter; the factory selects the provider. |
| `application/tools.py` | Allowlisted tool definitions, schema validation, sequential async execution and structured chart results. Market registries are created per invocation. |
| `prompts/` | Packaged static finance XML, validation/loading, revision hash, and separate escaped name context. |
| `adapters/outbound/identity/` | Resolve identity through PostgreSQL-backed sessions in iteration 03. The initial development adapter remains an explicit local/test-only alternative. |
| `frontend/` | React/TypeScript forms, session state, history, and streamed chat UI. Vite proxies same-origin API paths locally and builds static production assets. |
| `adapters/outbound/rate_limit/` | Implement the rate-limit contract. The memory adapter is retained for local use and the initial personal cloud trial; strict shared enforcement is deferred by explicit user decision. |
| `migrations/` | Alembic environment and versioned database migrations. |
| `tests/` | Focused application, HTTP, and PostgreSQL behavior tests. |

A future Valkey lock adapter belongs under `adapters/outbound/`, alongside PostgreSQL rather than in `inbound/`. The shared locking backend remains an open choice.

## LangGraph and model integration

- Use LangGraph to express agent execution as a graph.
- Support a model/tool loop: call the model, execute requested tools, return their results to the model, and repeat until a final response or execution limit is reached.
- Allow the same tool to be called multiple times within a single user turn.
- A turn may finish without any tool call when the model can answer directly.
- Keep graph execution state separate between requests and users.
- Treat graph structure and conversation state as separate concerns. Different messages do not inherently require rebuilding the graph.
- Compile one graph at startup and reuse it. Each invocation carries its own history, user profile, transcript, and counters; the shared client stores no current user context.
- Select provider and model through a single `MODEL` setting: `simulated` or `openai:<model-id>`. OpenAI is the first real provider for iteration 02, using the user's available API credits. The shorthand `MODEL=openai` selects `openai:gpt-6.1-terra`; explicit identifiers such as `openai:gpt-6.1-sol` override it. Use `MODEL_MAX_OUTPUT_TOKENS` for the output limit. These settings are normal configuration; the API key is a separate provider-specific secret. Keep the simulated provider available for local tests.
- Supporting a new provider may require another adapter and capability checks; do not assume every provider has identical tool-calling or streaming behavior.
- Iteration 07 defines read-only IOL search/quote/history tools and an inline chart tool. IOL uses native async HTTP, per-process token renewal, per-invocation series references and no fabricated fallback. See [market tools](market-tools.md). RAG remains deferred.

## Async execution

- Use async FastAPI endpoints, async LangGraph nodes, and async database and HTTP clients where supported.
- Prefer native async operations for model requests and tool network calls.
- Do not call blocking I/O directly from an async node or endpoint.
- Use a bounded thread executor when a dependency only offers a synchronous interface. An async method name alone does not prove that its implementation is native async.
- Do not create an event loop, process, or dedicated thread for each user or message.
- Keep application admission limits separate from Cloud Run concurrency and any thread-pool limits.

## Execution controls

Include the following controls from the initial implementation. Local defaults are four active turns, 20 submissions per user per rolling minute, a 30-second total deadline, 20 seconds per model request, 5 seconds per future tool, at most four model calls/eight tool calls, graph recursion limit 12, and 2048 output tokens per OpenAI response. Environment configuration can override these values.

- **Conversation/session lock:** acquire a lock before starting a turn and hold it throughout response generation, any tool execution, streaming, and final persistence. Reject a second turn for the same session as busy while the lock is held. Different users may execute concurrently.
- **Shared coordination:** the local implementation uses PostgreSQL session advisory locks on dedicated connections. A future Valkey adapter can implement the same port. Confirm the deployed choice before provisioning; process-local locks alone are insufficient.
- **Safe lock lifecycle:** define acquisition, ownership, release, expiration or recovery, and behavior when lock storage is unavailable. Coordinate cancellation and lock release so a previous execution cannot continue concurrently with a new turn in the same conversation.
- **Per-user rate limiting:** restrict message submission frequency independently of the conversation lock.
- **Initial cloud rate-limit scope:** keep bounded process-local chat/auth limits for the personal trial with one worker and maximum one instance. The user explicitly accepted counter resets on restart and independent counters during revision overlap. Shared rate limiting is deferred; PostgreSQL conversation locks remain required and shared.
- **Admission control:** bound the number of active executions admitted by the backend.
- **Timeouts:** define a total turn deadline and appropriate model/tool operation timeouts.
- **Agent limits:** cap model calls, tool calls, and graph execution steps. Count these separately because one model response can request several tools.
- **Output limits:** configure a maximum model response size where the provider supports it.
- **Streaming lifecycle:** define behavior for client disconnects, cancellation, partial output, and errors after streaming has started.

Choose active-execution limits based on this application's resources and measured behavior.

## Secrets and permissions

- Use Secret Manager for runtime secrets such as external model API keys. It is the selected managed secret store for this Google Cloud deployment.
- Grant the runtime service account access only to the secrets and resources it needs.
- Use IAM database authentication for the cloud runtime, migration job, and the personal human SQL administrator. Administrative SQL privileges belong only to the human account; initialize schema/default data privileges with the explicit operator helper, not a built-in database password or API startup side effect.
- Prefer workload identity and short-lived credentials for GitHub Actions access to Google Cloud.
- Keep runtime and deployment permissions separate.
- Keep secrets out of source control, frontend bundles, application logs, and committed configuration.
- Define local secret handling during implementation using untracked local configuration or an appropriate development identity.
- Terraform provisions secret resources and access policies; decide the secret-value injection process before implementation and avoid unnecessarily placing secret values in Terraform state.

## Observability

Use structured logs and Google Cloud logging/monitoring capabilities to understand behavior and cost.

Iteration 05 carries the pending operational review from iteration 04: document how to inspect Cloud SQL memory usage and memory components in the Google Cloud console / Cloud Monitoring, together with CPU utilization and database connections. Also document Cloud Run container memory utilization separately. Use these metrics to evaluate the initial sizing; distinguish database memory usage from reclaimable cache rather than treating all allocated memory as pressure.

Record, where available:

- Request and execution identifiers, environment, and application version.
- Model provider and model name.
- Input, output, and total token usage, including provider-specific usage categories when available.
- Total turn duration, model call duration, tool duration, and time to first streamed output.
- Number of model calls, tool calls, and agent steps.
- Completion status, failures, timeouts, cancellations, rate-limit rejections, and lock contention.
- Active execution counts and relevant resource or database connection usage.

Preserve provider-reported usage when available and distinguish estimates or unavailable values. Do not log passwords, tokens, API keys, or conversation content by default.

## Local development and delivery

- Use Docker Compose to run the backend, frontend, and local PostgreSQL together.
- Implement local username authentication in the existing Python/PostgreSQL stack; no Firebase Authentication emulator or cloud account is required for iteration 03.
- Use same-origin browser requests through the Vite proxy locally and planned Firebase Hosting-to-Cloud Run API rewrites in deployment. Use `__session` for the HttpOnly authentication cookie so Hosting can forward it; validate production HTTPS, origin, cache, and CSRF settings before exposing it.
- Keep application configuration environment-specific while reusing the same code.
- Separate local settings into ignored `backend/.env` and `frontend/.env`, each with its committed example. Backend auth policies have defaults; override only what differs. `APP_ORIGIN` is the exact public frontend origin and is required to differ between local/staging/production. Frontend/API host port mappings are local Compose concerns; Firebase Hosting does not run a Vite server. Deployed HTTPS, secure cookies, credentials, and container routing are configured separately.
- Manage infrastructure with Terraform and maintain its state securely outside the repository.
- Use GitHub Actions for validation, tests, application builds, and deployment.
- Build and publish the backend container image to Artifact Registry, then deploy it to Cloud Run.
- Build/package the frontend as needed and publish it to Firebase Hosting.
- Define database migrations and their execution in the delivery process.
- Decide deployment triggers, production approval rules, and release/rollback details before implementing the workflows.

## Backend testing

Use pytest to test meaningful FastAPI and application behavior, including:

- Authentication and conversation ownership enforcement.
- Conversation persistence and reconstruction of full history.
- Streaming success, failures, and client disconnection behavior.
- Isolation between concurrent users and exclusion of overlapping turns in one conversation.
- Rate limits, admission limits, deadlines, and model/tool call limits.
- LangGraph tool-loop behavior, including repeated calls to the same tool within a turn.
- Relevant PostgreSQL adapter and migration integration behavior.

Use deterministic fake models and tools for normal automated tests. Real model calls should be explicit, optional integration checks rather than a requirement for every test run.

## Possible plan

This is a tentative roadmap grouped by working outcomes. Refine each iteration before implementation; split an iteration only if its scope grows enough to justify it.

| Iteration | Scope | Working outcome |
| --- | --- | --- |
| 01 — Initial backend setup | FastAPI, PostgreSQL/Alembic, ports and adapters, simulated async agent, streaming, coordination, and Docker Compose. Implemented locally. | A tested local backend with persisted conversations. |
| 02 — OpenAI finance agent and tool readiness | OpenAI provider adapter, configurable model, finance-focused instructions, real streaming and usage/timing logs, and a bounded model/tools execution path. Register no concrete tools. | Local implementation; the user will perform the live provider check after adding an API key. |
| 03 — Users and frontend | Implemented locally: username/password registration, display name, backend-validated revocable sessions/logout, React + TypeScript + Vite + Tailwind, streamed chat/history, and separate component env files. | Use the local application from a browser with real user identity and enforced conversation ownership. |
| 04 — Google Cloud backend with Terraform | Complete: remote state, APIs, IAM, Artifact Registry, Secret Manager, Cloud SQL, IAM grants, migration job, and Cloud Run backend. | Backend deployed manually; the user verified live/ready HTTP 200 and PostgreSQL access. |
| 05 — Firebase Hosting | Functionally complete: frontend published with Hosting-to-Cloud Run rewrites and browser acceptance confirmed by the user. RAM/log/cost and rollback/teardown review remains a separate operational follow-up. | A working deployed browser application and recorded manual release commands. See [specification](../specs/05-firebase-hosting.md). |
| 06 — GitHub Actions | Implementation reviewed: PR updates targeting main and main pushes run real PostgreSQL/backend tests, frontend tests/build, and Terraform checks. Main deploys changed components, runs migrations, and verifies releases with bounded backend traffic rollback. Use OIDC/Workload Identity Federation to impersonate a dedicated deploy account, restricted by repo/owner IDs, main, and workflow path; no permanent deployment key. A global deployment lock remains omitted. | The user reports completing OIDC provisioning and the GitHub variable. First real workflow verification remains pending. See [specification](../specs/06-github-actions.md) and [setup guide](github-actions.md). |
| 07 — Staging | Reuse infrastructure modules with separate configuration, data, and secrets; define promotion to production. | Two environments with a clear delivery workflow. |
| Optional — RAG | Define a knowledge source, ingestion/indexing, retrieval, and evaluation when the intended data and use case are known. | Answers grounded in the selected knowledge source. |

Tools do not require RAG. Iteration 02 prepares the graph and OpenAI integration for future tools without adding a calculator, business tool, or hosted provider tool. Its XML finance prompt includes separate per-user name context. OpenAI defaults to `gpt-6.1-terra`, overridable through configuration. Recording this roadmap does not authorize starting later iterations automatically.

## Next decisions

- Verify live model access and finance behavior after adding the local OpenAI key; override the default model through configuration when needed.
- Concrete tools and any RAG requirements.
- Region and initial resource sizing.
- Deployed lock backend, shared rate limiter, and numeric limits after measurement.
- Deployment workflow and production configuration for the authentication design specified in iteration 03.

Keep project-wide decisions in this file. Describe the scope and acceptance criteria of each iteration in a separate document under `specs/`.

The first iteration is defined in [Iteration 01 — Initial Backend Setup](../specs/01-initial-backend-setup.md).

The second iteration is described in [Iteration 02 — OpenAI Finance Agent](../specs/02-openai-finance-agent.md). Its normal tests run offline; live provider checks are separate.

The third iteration is implemented in [Iteration 03 — Username Authentication and Chat UI](../specs/03-users-and-chat-ui.md). Deployment remains separate work.

## Iteration 07 — market data and charts

- Real local provider: IOL; credentials only in the ignored backend env. Cloud uses a Secret Manager JSON secret and conditional enablement. No broker credentials enter prompts, UI, docs or Terraform state.
- OpenAI selection: `gpt-6.1-terra` with explicit `MODEL_REASONING_EFFORT=high`. Initial current defaults: model output 8192, model timeout 120s, turn timeout 240s and tool timeout 10s, retaining four model calls/eight tool calls/graph recursion 12. Earlier defaults above describe the initial iterations. Prepared Cloud Run timeout becomes 270s when the operator applies Terraform.
- Preserve async/await throughout tools and IOL HTTP; no synchronous broker SDK or per-user threads/event loops. The compiled graph is shared; tool series/chart state is invocation-local.
- Responses support ordered Markdown/chart blocks, saved on assistant messages as JSONB through migration 0005. Recharts draws backend-owned series; models choose references and presentation, never invent points or execute chart code. User ownership protects saved charts.
- Historical comparisons use a conservative quality gate: a twofold increase or halving between consecutive observations returns `history_comparability_unverified` before a series reference/summary is exposed. Splits can invalidate comparisons of unadjusted prices; base 100 does not repair them. Never infer a split, investment loss or adjustment factor from the jump alone. Reliable adjusted histories/corporate-action data remain deferred, and existing chart snapshots are preserved.
- Three editable starter prompts appear in an empty chat; two small rounded suggestion chips appear above the composer with history. Suggestions fill the draft and are disabled during a turn or logout.
- Tool start/finish status and elapsed time stream over the existing SSE response. The UI shows an expanded, collapsible activity panel under the thinking indicator, with friendly operation labels, white/blue running/finished circles and three animated dots throughout the active turn. Tool outcomes/timings remain internal rather than displaying OK/failed or red/green states. Repeated calls use separate IDs. Activity is transient per turn; arguments, provider payloads and private reasoning are not exposed, and unfinished indicators close on disconnection. No additional migration or infrastructure is needed for this panel.
- No simulated market provider. The existing simulated LLM and mocked provider responses remain for offline tests. No cloud apply, commit or push is authorized by implementing this iteration.

See [Iteration 07](../specs/07-market-tools-and-charts.md) and [local review](market-tools.md).
