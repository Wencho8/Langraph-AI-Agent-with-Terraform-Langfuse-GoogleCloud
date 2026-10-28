resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "chatbot-runtime"
  display_name = "Chatbot backend runtime"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}

resource "google_service_account" "migrations" {
  project      = var.project_id
  account_id   = "chatbot-migrations"
  display_name = "Chatbot database migrations"

  depends_on = [google_project_service.required["iam.googleapis.com"]]
}
