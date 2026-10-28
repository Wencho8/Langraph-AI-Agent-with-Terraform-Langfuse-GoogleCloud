provider "google" {
  project = var.project_id
  region  = var.region
}

# Firebase resources use the beta provider; existing backend resources keep google.
# Both providers use the operator's explicitly selected personal ADC file.
provider "google-beta" {
  project               = var.project_id
  region                = var.region
  billing_project       = var.project_id
  user_project_override = true
}
