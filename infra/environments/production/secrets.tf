resource "google_secret_manager_secret" "openai_api_key" {
  project   = var.project_id
  secret_id = "openai-api-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [
    google_project_service.required["secretmanager.googleapis.com"]
  ]
}

# Values are supplied by the operator, never through Terraform/state.
resource "google_secret_manager_secret" "iol_credentials" {
  project   = var.project_id
  secret_id = "iol-credentials"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required["secretmanager.googleapis.com"]]
}

resource "google_secret_manager_secret" "langfuse_secret_key" {
  project   = var.project_id
  secret_id = "langfuse-secret-key"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required["secretmanager.googleapis.com"]]
}
