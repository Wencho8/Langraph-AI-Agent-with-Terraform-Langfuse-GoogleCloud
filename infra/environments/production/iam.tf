resource "google_project_iam_member" "runtime_sql" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"

  depends_on = [
    google_project_service.required["sqladmin.googleapis.com"]
  ]
}

resource "google_project_iam_member" "migrations_sql" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.migrations.email}"

  depends_on = [
    google_project_service.required["sqladmin.googleapis.com"]
  ]
}

resource "google_secret_manager_secret_iam_member" "runtime_openai" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.openai_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_iol" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.iol_credentials.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_langfuse" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.langfuse_secret_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
