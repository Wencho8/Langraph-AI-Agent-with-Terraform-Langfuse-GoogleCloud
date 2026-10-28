# Enables Firebase on the existing Google Cloud project. It neither creates a
# second project nor publishes frontend assets. Firebase enablement is permanent;
# removing this resource from state does not remove Firebase from the project.
resource "google_firebase_project" "chatbot" {
  provider = google-beta
  project  = var.project_id

  depends_on = [
    google_project_service.required["cloudresourcemanager.googleapis.com"],
    google_project_service.required["firebase.googleapis.com"],
    google_project_service.required["firebasehosting.googleapis.com"],
  ]
}
