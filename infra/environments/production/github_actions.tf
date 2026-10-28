locals {
  # Stable IDs allow repository/account renames while blocking owner transfers.
  github_repository_id = "1436208365"
  github_owner_id      = "103704812"
}

# GitHub OIDC impersonates this account; no service-account key is created.
resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = "chatbot-deploy"
  display_name = "Chatbot GitHub Actions deployment"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "chatbot-github"
  display_name              = "Chatbot GitHub Actions"

  depends_on = [
    google_project_service.required["iam.googleapis.com"],
    google_project_service.required["iamcredentials.googleapis.com"],
    google_project_service.required["sts.googleapis.com"],
  ]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC for main deployment"

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.repository"          = "assertion.repository"
    "attribute.ref"                 = "assertion.ref"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
    "attribute.event_name"          = "assertion.event_name"
  }

  attribute_condition = join(" && ", [
    "attribute.repository_id == '${local.github_repository_id}'",
    "attribute.repository_owner_id == '${local.github_owner_id}'",
    "attribute.ref == 'refs/heads/main'",
    # Use the token's current repository name only to locate its own workflow;
    # authorization of the repository and owner is based on the IDs above.
    "attribute.workflow_ref == attribute.repository + '/.github/workflows/ci-deploy.yml@refs/heads/main'",
    "(attribute.event_name == 'push' || attribute.event_name == 'workflow_dispatch')",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "deploy_github_oidc" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${local.github_repository_id}"

  depends_on = [google_iam_workload_identity_pool_provider.github]
}

resource "google_project_iam_member" "deploy_project" {
  for_each = toset([
    "roles/run.viewer",
    "roles/firebasehosting.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deploy.email}"

  depends_on = [google_firebase_project.chatbot]
}

resource "google_artifact_registry_repository_iam_member" "deploy_images" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.backend.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deploy_backend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_cloud_run_v2_job_iam_member" "deploy_migrations" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migrations.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_runtime_identity" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_service_account_iam_member" "deploy_migration_identity" {
  service_account_id = google_service_account.migrations.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}
