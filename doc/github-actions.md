# GitHub Actions — Setup and Review

Status: implementation reviewed. The user reports applying the OIDC Terraform configuration and setting `GCP_WIF_PROVIDER`, and has explicitly authorized commit/push after review. The first real workflow/deployment remains pending verification. The old nine-addition JSON-key plan was never applied and is obsolete; this guide describes the OIDC design. The assistant has not applied Terraform, created a cloud key, or changed GitHub settings.

## What runs

| Event | Checks | Deployment |
| --- | --- | --- |
| Open/update/reopen a PR targeting `main` | Backend with PostgreSQL 17; frontend tests/typecheck/build; Terraform format/validation | None; no deployment credentials |
| Any push to `main`, including PR merges | Same checks | Changed components only, after all checks pass |
| Manual Actions run | Same checks | Both components only when the selected ref is `main` |

Docs-only and infra-only pushes still run checks but do not deploy apps. An infrastructure apply remains an explicit operator action. The Python helper in `scripts/ci_changes.py` determines components from the full push range, including merges and deleted/renamed files.

Backend tests use real temporary databases in the runner's PostgreSQL container, exercising Alembic and existing API/auth/persistence/coordination behavior. Frontend tests run Vitest/jsdom and the real production build. Google/OpenAI clients remain mocked in normal tests; there are no paid model calls. No extra local test containers are needed. GitHub runner usage has its own account quota/billing, separate from Google Cloud trial credits.

## Files to review

- `.github/workflows/ci-deploy.yml`: triggers, isolated test jobs, main-only credential use, image publication, migration/deploy order, and Hosting publication.
- `scripts/ci_changes.py`: select backend/frontend from the push or force both for manual dispatch.
- `scripts/deploy_backend.py`: save the old revision, migrate, deploy without traffic, promote, smoke-check, and restore old traffic when safe to attempt.
- `scripts/check_deployment.py`: bounded backend/frontend checks without accounts, cookies, or model calls.
- `scripts/tests/test_deployment.py`: fake-cloud failure scenarios, rollback behavior, component selection, and stale/broken frontend detection.
- `infra/environments/production/github_actions.tf`: a dedicated deploy identity, its permissions, and the OIDC pool/provider/trust binding.
- Cloud Run/job lifecycle rules: Terraform ignores application image updates; the service also ignores release-managed traffic. Other configuration remains Terraform-owned.

## 1. Review and apply deployment permissions

Run from the repository root in your own terminal:

```bash
export CLOUDSDK_CONFIG="$HOME/.config/gcloud-chatbot"
export CLOUDSDK_PYTHON="/opt/homebrew/bin/python3.13"
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud-chatbot/application_default_credentials.json"
gcloud auth list
terraform -chdir=infra/environments/production fmt
terraform -chdir=infra/environments/production validate
terraform -chdir=infra/environments/production plan -out=github-actions-oidc.tfplan
```

Expect the personal project/account and fourteen new resources: the previous nine deployment account/permission resources, two additional API resources (IAM Credentials and Security Token Service), one Workload Identity Pool, one OIDC provider, and one Workload Identity User binding. Review any additional changes before applying. The lifecycle changes do not create a new image or change current traffic. Do not apply the old `github-actions.tfplan` with nine additions.

After reviewing the saved plan:

```bash
terraform -chdir=infra/environments/production apply github-actions-oidc.tfplan
```

The deploy account is `chatbot-deploy@wencho8-chatbot-prod.iam.gserviceaccount.com`. It can publish images and Hosting, update this backend and migration job, execute the job, and use the runtime/migration identities. It does not receive direct SQL administration, access to the Terraform state bucket, or permission to read the OpenAI key. Existing runtime identities still perform SQL and secret access.

## 2. Configure the non-secret OIDC provider variable in GitHub

No service-account key is generated, downloaded, or stored in GitHub. Terraform establishes a trust relationship; the deploy job obtains temporary credentials from GitHub's OIDC identity and uses them to impersonate `chatbot-deploy`.

Trust is restricted to all of the following:

- Repository ID `1436208365` and owner ID `103704812`, verified from GitHub repository metadata. Trust does not depend on a hardcoded repository/account name; renaming either does not require updating these IDs. Transferring the repository to a different owner remains blocked until the owner-ID condition is deliberately changed.
- Branch `refs/heads/main`.
- Workflow `.github/workflows/ci-deploy.yml` from that branch and the same repository. Its full workflow ref is constructed from the repository name in the signed token, so a rename does not break this check. Moving/renaming the workflow file itself requires updating the trusted path.
- Event `push` or `workflow_dispatch`; pull-request events cannot use this trust.

Only the deploy job has `permissions: id-token: write`. Tests and Terraform validation do not request OIDC tokens. The provider's server-side conditions still restrict authentication even if a PR edits workflow conditions.

After the reviewed apply, read the provider resource name:

```bash
terraform -chdir=infra/environments/production output -raw github_workload_identity_provider
```

In the personal repository, open **Settings → Secrets and variables → Actions → Variables → New repository variable**:

- Name: `GCP_WIF_PROVIDER`.
- Value: the complete Terraform output above, expected to be `projects/269905799757/locations/global/workloadIdentityPools/chatbot-github/providers/github`.

This is a configuration identifier, not a password or secret. The deployment service-account email is already configured in the workflow. No repository deployment secret is required.

Alternatively, after confirming `gh auth status` shows your personal account with access to this repository:

```bash
gh variable set GCP_WIF_PROVIDER \
  --repo Wencho8/AI-chatbot-Agent---Langraph-Terraform-Gcloud \
  --body "$(terraform -chdir=infra/environments/production output -raw github_workload_identity_provider)"
```

The auth action exports temporary ADC configuration for gcloud and Firebase and cleans it up after the job. The generated `gha-creds-*.json` remains ignored: a temporary credential configuration file can exist even though no permanent service-account private key is created. Do not upload your human `application_default_credentials.json`. OpenAI still uses the existing runtime Secret Manager reference; its key is not needed in GitHub.

New federation resources and IAM permissions can take a few minutes to propagate before the first run succeeds. Configure the variable and inspect any authentication failure before retrying.

## 3. Review, push, and observe

The assistant must not commit or push without a new explicit request. When you choose to push:

1. A PR targeting `main` runs checks after each update; it cannot deploy.
2. A push to `main` or merge runs those same checks, then releases selected components. A missing/wrong `GCP_WIF_PROVIDER` variable fails with an explicit setup message before cloud authentication.
3. Backend publication uses a commit/run/attempt tag and an immutable digest for both migrations and the service. The migration job runs first, then a no-traffic revision is created and promoted explicitly after startup.
4. Frontend publication downloads the exact build tested by the frontend job. Both-component releases publish frontend only after successful backend deployment.
5. Inspect the Actions job summary and logs. Verify the reported revision/image, readiness result, Hosting URL, and final status. Open the app for a manual session/chat check; automatic smoke checks do not call OpenAI.

Automatic backend traffic rollback is bounded and best-effort. A failed migration or startup leaves old traffic in place. A failed promotion/smoke attempts to restore the old revision only if the candidate still owns traffic. The job remains failed even when recovery succeeds. No schema downgrade is automatic; migrations must remain compatible with the old backend. Failed frontend publication/checks require inspecting Firebase Hosting; use its previous release rollback if necessary.

Avoid overlapping production pushes: there is intentionally no global concurrency lock. Do not cancel an in-progress migration expecting guaranteed rollback. A manual Actions run on `main` redeploys both components if a previous partial release needs retrying. No workflow run provides a transaction across backend, database, and frontend.

## Terraform after the first automatic release

`backend_image` is the initial bootstrap image, not a release pointer that Actions must commit. Terraform ignores only the service image/traffic and migration job image so a later infrastructure apply cannot put an old image back. It still manages identities, secrets references, resources, limits, and health checks. A backend config change may create a new revision from the currently observed image. Review every infrastructure plan and check service traffic/readiness after an explicit apply.

## Local verification

Verified locally: 86 backend tests passed against the existing local PostgreSQL, 13 frontend tests passed, and the TypeScript/Vite production build passed. The final pre-push review reran all 19 operator/deployment helper tests with fake cloud/HTTP clients and actionlint 1.7.12 successfully. Application code is unchanged since its passing checks. Terraform commands and real cloud operations were not executed by the assistant; the user reports completing OIDC setup and the GitHub variable. A real workflow run is still required to verify integration.

```bash
python3.13 -m unittest discover -s scripts/tests -v
make backend-test
npm --prefix frontend test
npm --prefix frontend run build
```

The helper tests fake gcloud and HTTP and do not execute cloud commands. Backend tests require the existing local PostgreSQL/container setup; they do not use the production database. Real Actions, IAM permissions, registry publication, migration execution, and rollback in Google Cloud remain unverified until the user activates and observes the workflow.

## References

- [Google Actions authentication through Workload Identity Federation](https://github.com/google-github-actions/auth)
- [Google Cloud federation for deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [Firebase CLI with Application Default Credentials](https://firebase.google.com/docs/cli#cli-ci-systems)
- [Cloud Run traffic and rollback](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)
