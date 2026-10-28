# Iteration 06 — GitHub Actions

Status: implementation reviewed; the user reports applying the OIDC Terraform configuration and setting the non-secret GitHub variable. The user explicitly authorized commit/push after review. Local application checks passed previously; the final review passed all 19 helper tests and actionlint again. The first real GitHub workflow/deployment remains pending verification. Terraform/cloud setup was operated by the user. Details are recorded in the setup guide.

## Goal

Run the existing tests automatically for every update to a pull request targeting `main`, and for every push to `main`. After successful checks on `main`, publish changed application components to production. A merged PR and a direct push use the same release path.

This iteration is authorized for local implementation and local tests; the user subsequently authorized commit/push after review. Do not create keys, change GitHub settings/secrets, or execute Terraform/gcloud/cloud deployment commands on the user's behalf. The user reviews files and operates cloud setup separately. Pushing the authorized workflow to main can trigger its automatic deployment.

## Decisions

- One workflow: `.github/workflows/ci-deploy.yml`, with backend, frontend, Terraform checks, then deployment.
- PR events target `main`; branch pushes without such a PR do not trigger this workflow. Direct `main` pushes run it. Manual dispatch runs tests on the selected ref but deploys only from `main`.
- Backend tests use Python 3.13, locked dependencies, and a real PostgreSQL 17 service container on the GitHub runner. Existing fixtures create isolated databases and run Alembic. Production SQL and paid model access are never used in tests.
- Frontend tests use Node 24, `npm ci`, Vitest, TypeScript, and a Vite production build. Preserve that exact build as a short-lived artifact for publication. These are component/protocol tests, not a new browser E2E framework.
- Terraform format and validation run without cloud credentials or remote state; no automatic plan/apply.
- Use GitHub OIDC and Workload Identity Federation through the dedicated deploy service account. Terraform manages the pool/provider and trust binding, with stable repository/owner IDs, an exact workflow path within the signed token's current repository, main branch, and push/manual-event conditions. Repository/account renames do not require a trust update; owner transfers or a changed workflow path do. Only the deploy job receives `id-token: write`. Configure the non-secret repository variable `GCP_WIF_PROVIDER`; no permanent deployment key or repository secret is required. Global deployment serialization remains omitted by user choice.
- PR/test jobs never receive deployment credentials. Google authentication is in the main-only deploy job, after all checks pass.
- Provision a dedicated `chatbot-deploy` identity with scoped image write, Cloud Run update/execute, runtime/migration identity use, Hosting administration, and supporting read/API usage permissions. Do not grant Owner/Editor, SQL administration, OpenAI secret access, or state bucket access.

## Release flow

1. After all checks pass on `main`, classify the push's complete `before..after` changes. Docs-only and infrastructure-only changes do not release apps. Backend changes select the backend; frontend/Hosting config changes select the frontend. Workflow/release-script changes and manual dispatch select both. If the previous commit is unavailable, select both rather than risk a missed application release.
2. Build/push a Linux AMD64 backend image tagged with commit/run/attempt, then deploy by immutable digest.
3. Save the existing single revision serving 100% of backend traffic.
4. Update the existing migration job to the new digest and execute it with `--wait`. Alembic applies pending changes or exits without schema changes if already current. A migration failure stops the release before changing the service.
5. Update the existing service to the new image without traffic and wait for startup checks. Confirm the expected revision is ready and the old revision still owns traffic.
6. Assign 100% traffic to the explicit new revision, then verify `/health/ready` with bounded retries and no model calls.
7. If promotion/smoke fails and that candidate still owns live traffic, restore the previous revision and verify readiness. The workflow still fails so the failed release is visible. Never downgrade the database automatically.
8. If selected, publish the frontend artifact to the explicit Firebase project using the OIDC-backed impersonated service account through ADC. Do not use interactive login, personal ADC, legacy `FIREBASE_TOKEN`, or a separate Firebase credential.
9. Verify the published index references this build's assets, the assets return non-HTML content, and `/v1/auth/session` returns expected unauthenticated JSON with `no-store`. Do not register production test users or call OpenAI.
10. Write a GitHub Actions summary identifying commit, backend digest/revisions where applicable, selected components, outcome, and frontend URL.

## Terraform and application ownership

Terraform keeps ownership of service/job configuration, IAM, resources, secrets references, limits, and health probes. The workflow owns current application images and service traffic. Lifecycle rules ignore only those release-controlled attributes; the existing `backend_image` remains the initial image for creating resources. Apply the reviewed Terraform changes before enabling the first automatic deployment.

Do not run infrastructure applies from Actions or automatically commit new image values to the repository.

## Rollback limits

- Build/test/migration/startup failures do not promote the candidate.
- Backend automatic rollback restores traffic, not schema, data, migration job image, or frontend releases. New migrations must remain compatible with the previous live backend; destructive changes need an explicit migration plan.
- Failed frontend verification is reported as failure. Frontend rollback is manual in Firebase Hosting release history; a backend already verified successfully is retained.
- There is no atomic multi-component release and no global deployment lock. Avoid overlapping production pushes. Best-effort revision checks refuse to replace an observed newer release, but do not eliminate all races, including migration job update/execution races. Runner cancellation/termination cannot guarantee rollback.
- Smoke checks prove basic startup/assets/routing, not all authentication/chat behavior or model quality. Component-only changes compare against the previous push; use manual dispatch to redeploy both after an incomplete earlier release.

## Review and activation

Follow [GitHub Actions setup and review](../doc/github-actions.md). The user first reviews the files and local test evidence, then generates/reviews/applies a new plan including the deploy identity/permissions and federation resources, sets `GCP_WIF_PROVIDER` as a repository variable, and chooses when to push. Do not apply the saved plan for the superseded key-based design. No cloud outcome is considered verified until the user observes a real run.

## Completion criteria

- PR updates targeting `main` execute the backend/PostgreSQL and frontend suites, plus Terraform checks, without production credentials or deployment.
- A direct push or merged PR into `main` passes checks and releases changed components in order.
- Migrations execute before backend promotion; readiness and frontend assets/routing are checked without model calls.
- Controlled local failure tests exercise migration/startup failure, promotion/smoke rollback, and refusal to overwrite observed newer traffic.
- The user verifies at least one real main-branch workflow run and can inspect its results. No staging is required.
