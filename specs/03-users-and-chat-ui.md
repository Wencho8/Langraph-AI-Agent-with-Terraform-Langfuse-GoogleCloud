# Iteration 03 — Username Authentication and Chat UI

Status: implemented and verified locally. Cloud deployment remains deferred.

Project decisions: [Definitions](../doc/definitions.md). Backend baseline: [Iteration 02](02-openai-finance-agent.md).

## Goal and scope

Open a React application, register with a name and username, sign in, and use one persistent finance conversation with streamed answers and saved history. Keep the application small and the authentication real.

Use **React + TypeScript + Vite + Tailwind CSS** in `frontend/`, in the same repository. The UI is a minimal modern chat and centered auth form titled "Chatbot de finanzas", without sales copy. Python/FastAPI authenticates username/password credentials and owns revocable PostgreSQL sessions. Firebase Hosting remains the future frontend host; Firebase Authentication is not used for this username-only design.

Include registration, login, logout, session restoration/expiration, ownership enforcement, a minimal chat screen, local Compose integration, and focused tests. Keep the existing graph, empty tool registry, model settings, full history, locks, and execution limits.

No email field, synthetic email addresses, social login, password recovery/change screens, MFA, account settings, multiple conversations, tools, RAG, uploads, or design system. Cloud provisioning, Firebase deployment, Terraform, and CI/CD implementation belong to later iterations. No Firebase account or OpenAI key is required for normal development/tests.

## Registration and identity

| Field | Rule |
| --- | --- |
| Name | Use existing `display_name`; required, trimmed, 1–120 characters. Shown in the UI and supplied as the existing escaped LLM profile context. |
| Username | Login identifier; trim and lowercase, then validate 3–32 ASCII characters from `a-z`, `0-9`, `_`, `-`, `.`. Enforce uniqueness in PostgreSQL, including concurrent registrations. |
| Password | 15–128 characters; allow spaces/Unicode, do not trim, silently truncate, or require arbitrary character combinations. |
| Repeat password | Must match exactly; validate in the form and registration endpoint. Never store it. |

Create a fresh internal UUID for every registered user. Clients cannot select IDs or claim existing development users. The username is not the LLM profile name; only the display name is added to profile context. Conversation text remains user-authored input.

Use Argon2id through a maintained password-hashing library, with a random per-password salt and encoded parameters. Start with at least `memory_cost=19456 KiB`, `time_cost=2`, `parallelism=1`. Store only the encoded hash. Password hashing/verification is blocking work: run it outside the event loop with at most two concurrent operations and bounded admission, not an unlimited thread queue.

Login failures use the same `401 invalid_credentials` response for unknown usernames and wrong passwords; use a dummy hash verification for unknown users. A duplicate registration may return `409 username_taken`, since usernames are public identifiers. Authentication validation errors must not echo password inputs or complete request bodies.

## Sessions and logout

- Use opaque, cryptographically random session tokens with at least 256 bits of entropy. Store only a SHA-256 verifier in PostgreSQL; do not use password hashing for these random tokens or invent a JWT/refresh-token system.
- Each successful registration/login creates a fresh session, replacing/revoking any previous session presented by that browser. Registration signs the new user in. Login does not rename or merge users.
- Set the token only in a host-only `__session` cookie: `HttpOnly`, `Path=/`, `SameSite=Lax`, and `Secure` in production. A local HTTP exception is allowed only in local/test environments. JavaScript never receives the authentication token in a response body or browser storage.
- Use an absolute 24-hour expiration initially, enforced server-side and reflected in the cookie. Each protected request checks the stored verifier, expiry, revocation, and user association. A restart preserves valid sessions; missing/expired/revoked sessions receive `401`.
- Logout revokes the **current session** in PostgreSQL and expires its cookie. Replaying a copied old cookie then fails; other devices' sessions remain valid. An already absent/expired session may be cleared with a successful logout response, without weakening origin/CSRF checks for an active session.
- Logout clears frontend user/chat state and aborts its pending requests. During generation, the backend also checks session validity through the existing execution watchdog and before later model/tool steps and final persistence. Reuse the 0.5-second watchdog interval with bounded database checks and fail-closed behavior. Revocation/expiration stops work when detected; document polling plus check latency, not instantaneous cancellation of an upstream request. Preserve cancellation-before-unlock behavior.
- Messages committed before logout remain history. Logout must not delete conversations. Rejected or cancelled partial output must not become a successful assistant message.

`__session` is chosen for future Firebase Hosting-to-Cloud Run rewrites: Hosting forwards that specially named cookie. Authenticated responses, including history and streams, use `Cache-Control: no-store`; do not cache private content at the CDN.

## Browser request protection and ownership

Use one browser origin. Locally, Vite proxies `/v1/*` to FastAPI, preserving paths. The deployment plan is Firebase Hosting serving the built frontend and rewriting `/v1/**` to Cloud Run. Do not depend on cross-site cookies or permissive credentialed CORS.

For every state-changing browser endpoint, including login/registration, validate `Origin` against the configured exact frontend origin and require JSON. Missing/untrusted origins are rejected; local CLI helpers explicitly send the configured origin. For authenticated mutations, additionally require an unpredictable, session-bound CSRF token in `X-CSRF-Token` and validate it on the backend. Use the synchronizer-token pattern: store a separate CSRF value with the session and return it only through authenticated, non-cacheable session responses. Keep it in frontend memory; never use the authentication cookie itself as the CSRF token. Logout may have an empty JSON object as its body.

The backend derives `UserProfile` from the validated session. It never trusts a username, user ID, conversation ID, or development header to authorize a normal chat request. Keep existing chat endpoints scoped to the authenticated user; reject unsupported ownership fields. Any future ID-based lookup must enforce ownership in the query.

Select identity with `AUTH_MODE=session|development`, defaulting to `session`. Development mode is an explicit local/test-only alternative; it must fail startup in production. Session mode never falls back to `X-Dev-User-Id`, even when a cookie is missing or invalid. Retire the old enablement flag in examples/documentation rather than leaving two competing switches. Alice/Bob may remain local fixture rows without login credentials; do not assign published/default passwords to them.

Protect authentication separately from the existing per-user chat limiter. Initial configurable limits: login 10 attempts per rolling 60 seconds per client IP **and** normalized username; registration 5 per IP per 60 seconds. Limit before password hashing, bound limiter storage/queues, and return `429` with a retry hint. Avoid permanent account lockouts. Trust forwarded client-IP headers only from explicitly configured proxies. Process-local limits are acceptable locally; shared enforcement is a requirement before cloud exposure in iteration 04.

## Database and backend boundaries

Use the next Alembic migration, preserving every existing user/conversation/turn/message:

- Add nullable `users.username` (unique, normalized) and `users.password_hash`. Existing development rows can have neither; registered accounts require both. Reuse `display_name`. Preserve the unused external-identity column for compatibility; it is not used to resolve these sessions.
- Add `auth_sessions`: ID, user FK, unique token verifier, separate CSRF value, creation/expiration timestamps, and optional revocation timestamp. Add indexes needed for session lookup. Expired/revoked rows never authorize requests; automatic scheduled cleanup is deferred.
- Keep `conversations`, `turns`, `messages`, and the transcript/metadata fields unchanged. **An authentication session is not a conversation or a turn.** Several login sessions can access the same user's single conversation; conversation locks still coordinate them.

Add focused authentication use cases/ports and PostgreSQL/password adapters. Keep HTTP cookies and request/response objects in inbound HTTP adapters. Construct shared dependencies in `app.py`; retain one worker/event loop, four active turns by default, native async database/model I/O, and no database transaction while waiting for a model.

| Endpoint | Behavior |
| --- | --- |
| `POST /v1/auth/register` | Validate name/username/password/confirmation; atomically create the account and session; set cookie; return public profile and CSRF token. `201`. |
| `POST /v1/auth/login` | Verify credentials; establish a fresh session; set cookie; return public profile and CSRF token. `200`. |
| `GET /v1/auth/session` | Restore the validated session; return public profile and CSRF token, or `401`. Never return the authentication token/hash. |
| `POST /v1/auth/logout` | Revoke the current session and clear the cookie. `204`. |
| `GET /v1/chat/messages` | Existing history contract, now authenticated by the session in normal mode. |
| `POST /v1/chat/messages` | Existing SSE contract, with session, origin, and CSRF validation before admission. |

Safe auth logs include event type, outcome, timing, and internal identifiers where appropriate. Never log credentials, cookies, CSRF values, password hashes, full auth validation payloads, names, or chat content. Auth/session failures must not reveal database/provider exceptions.

## Frontend behavior

Use a small component tree with registration/login and chat screens. Include basic labels, keyboard access, readable mobile/desktop layout, loading states, and clear inline errors. No UI library or client state framework is required initially.

1. On startup, restore the session before requesting history. Show login for `401`; display/retry dependency/network errors without pretending the user is unauthenticated.
2. After registration/login, load only that user's history and show their display name and logout action.
3. Sending a nonblank message synchronously locks the composer/send action to prevent double clicks or Enter races. Other users can still talk normally. Keep server locks authoritative across tabs/devices.
4. Use streaming `fetch` with an `AbortController` for the existing POST SSE endpoint. Parse UTF-8/event frames across arbitrary network chunk boundaries; do not use `EventSource` for this POST body.
5. Render deltas progressively. Treat `completed.text` as the authoritative saved answer and reconcile the temporary message; never append that final text a second time. Metadata/tool internals are not product UI.
6. Release the composer on completion or failure. Handle HTTP `401/403/409/429/503`, SSE `error`, network failures, and stream EOF without a terminal event. Preserve an unsent draft where applicable; label partial failed replies as unsaved and reconcile persisted history. Do not automatically resend paid turns.
7. Reload restores canonical history. Logout/session expiry clears prior-user state and aborts generation. Discard late responses from an earlier session so logging in as another user cannot show stale chat content.

Render user messages as escaped text. Render assistant Markdown during streaming and from persisted history using `react-markdown` and GFM support; include readable paragraphs, emphasis, lists, code, and tables styled with Tailwind. Disable raw HTML/images, keep the renderer's safe URL transform, and use safe external-link attributes. Do not execute model/user HTML. Only public configuration belongs in a Vite bundle. OpenAI keys, database credentials, and server secrets stay in the backend.

## Planned files and local workflow

The implementation uses these boundaries; no additional service or framework is required.

```text
frontend/
  package.json, package-lock.json, index.html, tsconfig*.json, vite.config.ts
  Dockerfile
  src/
    main.tsx, App.tsx, styles.css
    api/                  # Typed auth/history requests and SSE parsing
    auth/                 # Session state and login/register forms
    chat/                 # History, composer, and streaming state
  tests/                  # Focused UI/request/stream tests
backend/
  migrations/versions/0003_*.py
  src/chatbot/application/auth.py and ports.py
  src/chatbot/adapters/inbound/http/auth_routes.py and auth schemas
  src/chatbot/adapters/outbound/identity/ and postgres/
  tests/                  # Auth, ownership, session, and migration checks
```

Add a normal frontend development service to Compose, alongside the existing backend/PostgreSQL. Bind it to localhost on port `5173` initially. Route its API calls through the Vite proxy, not a browser URL containing Docker service names. Production will publish `frontend/dist/` as static assets; no production Vite server is planned.

Extend `make start/build/stop/logs` as needed; provide clear frontend build/typecheck/test commands and preserve backend checks. Adapt `make chat/history` for real sessions using an ignored local cookie jar and origin/CSRF headers; do not embed passwords in Make recipes or command-line arguments. Document explicit development mode for Alice/Bob and how to log in interactively for session mode. Do not print credentials or silently downgrade authentication.

Keep separate `backend/.env.example` and `frontend/.env.example`, with ignored real component `.env` files. The backend owns auth/session/model/database settings and `APP_ORIGIN`; the frontend owns its local port. Make initializes both and migrates a legacy root `.env` while preserving credentials. `FRONTEND_PORT=5173` and backend `API_PORT=8088` are local host mappings, not Firebase/Cloud Run environment settings. Stage/production must configure their real HTTPS frontend origin and secure cookies; unchanged policy defaults need not be repeated. Reject unsafe production cookie/origin/development-mode configuration. Keep model/execution settings intact and use `MODEL=simulated` for automated checks. Use Node 24, lockfiles, and the Vite Tailwind plugin; no custom stylesheet beyond the Tailwind import/theme is required.

## Verification and completion

Use the existing PostgreSQL service with isolated test databases, plus focused frontend tests (for example Vitest and React Testing Library). No extra test services, browser automation grid, cloud/emulator dependencies, or paid model calls. A short manual browser check is part of completion.

- Migration preserves existing data, supports nullable development credentials, creates session constraints, and is safe to rerun. Username normalization/uniqueness handles concurrent registrations.
- Registration rejects invalid/mismatched input and stores a non-plaintext password hash. Login verifies valid credentials and returns generic failures. Hashing does not block the event loop or bypass admission/rate controls.
- Cookies have expected local/production attributes; expiration is server-enforced. Logout invalidates a copied cookie while another device's session still works; revoked sessions stay revoked after restart.
- Missing/tampered/expired/revoked sessions fail. User A cannot read/write B's chat by supplying B's UUID, username, development header, or extra conversation fields. Session mode ignores development identity; production refuses that mode.
- Untrusted/missing origins and missing/incorrect/cross-session CSRF tokens are rejected. Authenticated history/streams/session responses are non-cacheable; secrets never appear in API responses, validation errors, logs, or frontend artifacts.
- Revocation/expiration during generation cancels work and releases the existing lock/slot within the documented detection interval. Completed messages remain persisted; partial cancelled answers do not become canonical assistant history.
- UI checks cover form errors, session restore, history, double-submit prevention, fragmented SSE, final-text reconciliation, all terminal/error paths unlocking the composer, and late responses after logout/user switching.
- Existing async model/tool-loop, coordination, history, and provider tests continue to pass. Frontend typecheck and production build pass. Manual review: register two accounts, chat/refresh/logout/login, verify separate histories and rejected cookie replay, using the simulated provider unless the user explicitly runs OpenAI.

Verification: 66 backend tests, 13 frontend tests (including Markdown formatting and unsafe-content handling), TypeScript checking, and the static production build passed. A manual browser check registered two local accounts, streamed with composer locking, restored history after reload/login, verified an empty history for the other account, and logged out. All agent-run verification used the simulated provider; the user's real OpenAI settings were preserved. README documents commands and local versus deployed settings. Deployment and later iteration work do not start automatically.

## References

- [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP session management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP CSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Vite static deployment](https://vite.dev/guide/static-deploy)
- [Firebase Hosting cookie forwarding and cache behavior](https://firebase.google.com/docs/hosting/manage-cache)
