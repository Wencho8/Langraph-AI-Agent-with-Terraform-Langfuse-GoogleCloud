resource "google_artifact_registry_repository" "backend" {
  project       = var.project_id
  location      = var.region
  repository_id = "chatbot"
  description   = "Docker images for the chatbot backend."
  format        = "DOCKER"

  depends_on = [
    google_project_service.required["artifactregistry.googleapis.com"]
  ]
}
