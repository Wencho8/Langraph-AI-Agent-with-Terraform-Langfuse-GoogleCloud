# Agent Chatbot on Google Cloud — Definitions

Status: evolving project decisions. Iteration 01 implements the first local backend.

## Purpose

Build a small AI chatbot to learn how to provision, deploy, and operate an application on Google Cloud. The main focus is DevOps: Terraform, Docker, GitHub Actions, cloud permissions, secrets, deployments, and observability.

The application should remain small enough to understand while providing a practical setting for these operational concerns.

The chatbot's initial domain is personal finance and financial education. It should keep answers within that scope and briefly redirect unrelated requests, such as general football questions, toward financial topics. Greetings and conversational follow-ups are allowed.

## Repository and scope

- Repository name: `agent-chatbot-gcloud`.
- Keep the Python backend, frontend, infrastructure definitions, and CI/CD workflows in the same repository.
- Maintain project-wide decisions in this document and iteration specifications in `specs/`.
- Iteration 01 covers the local backend. Frontend, cloud infrastructure, and deployment workflows remain deferred.
- Implement one backend application. Use internal modules and clear boundaries rather than separate microservices.

## Technology decisions

| Area | Decision |
| --- | --- |
| Backend | Python and FastAPI |
| HTTP server | Uvicorn, initially with one worker process per container |
| Agent execution | LangGraph |
| First real model provider | OpenAI, using the user's available API credits; exact model remains to be selected |
| Frontend | A minimal HTML, CSS, and JavaScript interface in this repository; no Vite |
| Frontend hosting | Firebase Hosting |
| Authentication | Firebase Authentication with email and password |
| Database | PostgreSQL; local PostgreSQL during development and Cloud SQL for PostgreSQL in Google Cloud |
| Database access and migrations | Async SQLAlchemy with asyncpg, and Alembic migrations |
| Local environment | Docker Compose |
| Backend hosting | Cloud Run |
| Infrastructure | Terraform |
| CI/CD | GitHub Actions |
| Runtime secrets | Google Cloud Secret Manager |
| Backend tests | pytest, including support for async tests |

Exact language versions, dependency versions, and frontend tooling beyond the minimal interface remain to be selected.

## Environments and cost

- Start with a single deployed environment named `production`.
- Add `staging` later by reusing the same Terraform modules and application artifacts, with separate environment configuration, data, and secrets.
- Configure the initial Cloud Run backend with a maximum of one instance and one Uvicorn worker per container.
- Choose region, CPU, memory, Cloud Run request concurrency, and database sizing before provisioning.
- Initially fund eligible Google Cloud usage with the available trial credit. The trial's remaining balance and expiration must be checked before deployment; it is not unlimited free usage for 90 days.
- Configure billing visibility and spending alerts. Do not treat alerts as an immediate spending cutoff.
- Backups and restoration workflows are outside the initial scope.

## User experience

1. A user registers with email and password.
2. The user signs in.
3. The user opens their single persistent conversation.
4. The user sends a message and receives a streamed response.
5. Previous messages remain available when the user returns.

The frontend should be intentionally simple. Authentication is a supporting feature, not the focus of the project.

The backend must verify the authentication token and derive the user identity from it. Every conversation read, write, and execution must be authorized for that user.

## Conversations and history

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
│   └── definitions.md
├── specs/
│   └── 01-initial-backend-setup.md
├── backend/
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
│   │       │   └── errors.py
│   │       ├── application/
│   │       │   ├── ports.py
│   │       │   └── orchestrator.py
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
│   │               │   ├── graph.py
│   │               │   └── simulated_model.py
│   │               ├── identity/
│   │               │   └── development.py
│   │               └── rate_limit/
│   │                   └── memory.py
│   └── tests/
│       ├── test_orchestrator.py
│       ├── test_api.py
│       └── test_postgres.py
├── compose.yaml
├── .env.example
├── .gitignore
├── Makefile
└── README.md
```

This is a target layout, not an instruction to scaffold every file immediately. Add files as their behavior is implemented. Keep the frontend and Terraform in this same repository when their iterations begin; their detailed layouts are deferred.

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
| `adapters/outbound/agent/` | Implement the agent execution port with LangGraph and the initial simulated model. LangGraph is an outbound adapter because the application invokes it as a dependency, even though it runs inside the backend process. |
| `adapters/outbound/identity/` | Resolve/verify identity through a replaceable implementation. The initial development adapter is local-only; Firebase verification can be added later. |
| `adapters/outbound/rate_limit/` | Implement the rate-limit contract. The initial memory adapter is local-only. |
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
- The graph construction and reuse strategy will be selected during implementation, based on isolation and concurrency requirements.
- Select the model through an adapter and configuration. OpenAI is the first real provider for iteration 02, using the user's available API credits. Default to `gpt-6.1-terra` when OpenAI is selected; allow a different non-empty model identifier through `OPENAI_MODEL`, including `gpt-6.1-sol`. Keep the simulated provider available for local tests.
- Supporting a new provider may require another adapter and capability checks; do not assume every provider has identical tool-calling or streaming behavior.
- Concrete tools, their permissions, and RAG data sources remain undefined.

## Async execution

- Use async FastAPI endpoints, async LangGraph nodes, and async database and HTTP clients where supported.
- Prefer native async operations for model requests and tool network calls.
- Do not call blocking I/O directly from an async node or endpoint.
- Use a bounded thread executor when a dependency only offers a synchronous interface. An async method name alone does not prove that its implementation is native async.
- Do not create an event loop, process, or dedicated thread for each user or message.
- Keep application admission limits separate from Cloud Run concurrency and any thread-pool limits.

## Execution controls

Include the following controls from the initial implementation; exact values and algorithms remain to be defined:

- **Conversation/session lock:** acquire a lock before starting a turn and hold it throughout response generation, any tool execution, streaming, and final persistence. Reject a second turn for the same session as busy while the lock is held. Different users may execute concurrently.
- **Shared coordination:** do not rely solely on process-local locks for deployed correctness. PostgreSQL and Valkey are candidate shared locking backends; the choice remains open. A Valkey adapter may implement the session lock through the same port without changing the application orchestrator.
- **Safe lock lifecycle:** define acquisition, ownership, release, expiration or recovery, and behavior when lock storage is unavailable. Coordinate cancellation and lock release so a previous execution cannot continue concurrently with a new turn in the same conversation.
- **Per-user rate limiting:** restrict message submission frequency independently of the conversation lock.
- **Admission control:** bound the number of active executions admitted by the backend.
- **Timeouts:** define a total turn deadline and appropriate model/tool operation timeouts.
- **Agent limits:** cap model calls, tool calls, and graph execution steps. Count these separately because one model response can request several tools.
- **Output limits:** configure a maximum model response size where the provider supports it.
- **Streaming lifecycle:** define behavior for client disconnects, cancellation, partial output, and errors after streaming has started.

Choose active-execution limits based on this application's resources and measured behavior.

## Secrets and permissions

- Use Secret Manager for runtime secrets such as external model API keys. It is the selected managed secret store for this Google Cloud deployment.
- Grant the runtime service account access only to the secrets and resources it needs.
- Prefer workload identity and short-lived credentials for GitHub Actions access to Google Cloud.
- Keep runtime and deployment permissions separate.
- Keep secrets out of source control, frontend bundles, application logs, and committed configuration.
- Define local secret handling during implementation using untracked local configuration or an appropriate development identity.
- Terraform provisions secret resources and access policies; decide the secret-value injection process before implementation and avoid unnecessarily placing secret values in Terraform state.

## Observability

Use structured logs and Google Cloud logging/monitoring capabilities to understand behavior and cost.

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
- Define a local authentication strategy during implementation; the Firebase Authentication emulator is a candidate.
- Keep application configuration environment-specific while reusing the same code.
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
| 02 — OpenAI finance agent and tool readiness | OpenAI provider adapter, configurable model, finance-focused instructions, real streaming and usage/timing logs, and a bounded model/tools execution path. Register no concrete tools yet. | Use `make chat` with a real finance-focused model and full history, with interfaces ready for future tools. |
| 03 — Users and frontend | Firebase Authentication, registration/sign-in, and a minimal browser chat UI in the same repository. | Use the application from a browser with real user identity. |
| 04 — Google Cloud with Terraform | Cloud Run, Cloud SQL, Firebase Hosting, Secret Manager, permissions, secure remote Terraform state, and an initial deployment. Replace local-only coordination where needed; configure resources, logs, spending alerts, and production settings. | A first production environment provisioned with Terraform, initially deployed manually. |
| 05 — GitHub Actions | Pull-request checks, image builds, short-lived Google Cloud authentication, database migrations, and controlled deployments. | Deliver changes through a repeatable CI/CD pipeline. |
| 06 — Staging | Reuse infrastructure modules with separate configuration, data, and secrets; define promotion to production. | Two environments with a clear delivery workflow. |
| Optional — RAG | Define a knowledge source, ingestion/indexing, retrieval, and evaluation when the intended data and use case are known. | Answers grounded in the selected knowledge source. |

Tools do not require RAG. Iteration 02 prepares the graph and OpenAI integration for future tools without adding a calculator, business tool, or hosted provider tool. Its XML finance prompt includes separate per-user name context. OpenAI defaults to `gpt-6.1-terra`, overridable through configuration. Recording this roadmap does not authorize starting later iterations automatically.

## Next decisions

- Override the default OpenAI model through configuration when needed; the iteration 02 integration contract is specified below.
- Concrete tools and any RAG requirements.
- Region and initial resource sizing.
- Lock implementation, rate-limit algorithm, and numeric execution limits.
- Streaming event contract and failure/persistence semantics.
- Detailed schema, migrations, local authentication, and deployment workflow.

Keep project-wide decisions in this file. Describe the scope and acceptance criteria of each iteration in a separate document under `specs/`.

The first iteration is defined in [Iteration 01 — Initial Backend Setup](../specs/01-initial-backend-setup.md).

The second iteration is specified in [Iteration 02 — OpenAI Finance Agent](../specs/02-openai-finance-agent.md); implementation has not started.
