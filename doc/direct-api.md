# Direct Cloud Run API and Bearer sessions

Firebase Hosting serves React's static assets. Browser API requests (auth, history, administration and SSE chat) go directly to Cloud Run; `/v1` no longer passes through Hosting. This avoids Hosting buffering and its 60-second proxy timeout. Cloud Run retains the configured 270-second request timeout and the app's 240-second turn deadline.

## Authentication

Login returns an opaque `access_token`, `token_type: Bearer`, user and expiry. The browser keeps only the token in per-tab `sessionStorage`; requests use `Authorization: Bearer` and omit cookies. Session restore returns the user/expiry, never another token. Without a saved token the login form renders immediately. Reload restores a session; closing the tab normally clears its browser token. JavaScript can access this storage, unlike an HttpOnly cookie.

The existing PostgreSQL session verifier, expiry, logout revocation, user approval and conversation ownership are reused. Blocking/logging out still stops a running turn through its access checks. No JWT, schema migration, new secret, or Firebase Authentication integration is needed. The historical CSRF column remains unused to avoid an unnecessary migration. Old cookie sessions are not accepted, so sign in again after deploying. The CLI also needs `make login` again; it stores a token in ignored `.local/session.json` (0600).

FastAPI CORS uses the existing exact `APP_ORIGIN`. It permits GET/POST and Authorization/Content-Type preflights; it does not permit credential cookies or arbitrary origins. Mutation origin/JSON checks remain. Tokens/passwords never belong in frontend env files, URLs or logs.

## Local review

Run the ordinary `make start` when ready; no additional test containers are needed. Leave `VITE_API_BASE_URL` empty in `frontend/.env` so Vite proxies to the local backend. Log in again, reload, send a tool/chart request, check incremental activity/text, and log out. Existing users and conversations are preserved.

Focused offline tests cover the HTTP Bearer/CORS boundary, revocation/replay, direct frontend transport and incremental event delivery. Real PostgreSQL ownership/expiry/approval tests run in the existing CI PostgreSQL service. No live model or broker calls are required for automated tests.

## Production delivery

The workflow supplies `VITE_API_BASE_URL` when building the tested frontend artifact. It defaults to the existing public URL `https://chatbot-backend-dasag4h7iq-uc.a.run.app`. The optional non-secret repository variable `API_BASE_URL` overrides it; use an HTTPS API origin without `/v1`. Manual production builds must supply the same value:

```bash
VITE_API_BASE_URL=https://chatbot-backend-dasag4h7iq-uc.a.run.app npm --prefix frontend run build
```

Deploy the backend first and frontend second using the main-branch workflow. This is a direct cutover for the personal application; there is no old-cookie compatibility phase. Smoke checks verify frontend assets and direct API 401/no-store/CORS/preflight responses without creating accounts or calling the LLM. Reload the web app and log in again, then verify real incremental events in the browser. No domain purchase or new IAM/resource provisioning is required.

No Terraform apply is required for functionality: APP_ORIGIN and public invocation already exist. The Terraform source removes the obsolete SESSION_COOKIE_SECURE env entry; applying that cleanup later is optional because the new app ignores it. No Terraform or gcloud command was executed as part of this implementation. Infrastructure permissions, secrets, database and model/tool execution remain unchanged.

This supersedes cookie/rewrite instructions in historical specifications 03/05. Runtime auth still uses `AUTH_MODE=session`; this names the database session mechanism, not the transport.
