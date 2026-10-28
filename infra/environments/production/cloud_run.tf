locals {
  backend_environment = {
    APP_ENV               = "production"
    AUTH_MODE             = "session"
    APP_ORIGIN            = var.frontend_origin
    SESSION_COOKIE_SECURE = "true"
    DATABASE_MODE         = "cloud_sql"
    CLOUD_SQL_INSTANCE    = google_sql_database_instance.chatbot.connection_name
    DATABASE_NAME         = google_sql_database.chatbot.name
    DATABASE_USER         = google_sql_user.runtime.name
    DATABASE_POOL_SIZE    = "6"
    MAX_ACTIVE_TURNS      = "4"
    MODEL                 = var.model
  }
}

resource "google_cloud_run_v2_service" "backend" {
  project             = var.project_id
  name                = "chatbot-backend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  # Terraform owns service configuration; the release workflow owns the current
  # image and explicit revision traffic (including rollback).
  lifecycle {
    ignore_changes = [template[0].containers[0].image, traffic]
  }

  # Service-level cap across revisions receiving traffic, not just one revision.
  scaling {
    min_instance_count = 0
    max_instance_count = 1
  }

  template {
    service_account                  = google_service_account.runtime.email
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 8
    timeout                          = "60s"

    containers {
      image = var.backend_image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle          = true
        startup_cpu_boost = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      dynamic "env" {
        for_each = local.backend_environment
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai_api_key.secret_id
            version = var.openai_secret_version
          }
        }
      }

      # Lifespan checks SQL/schema before serving; this probe never calls OpenAI.
      startup_probe {
        initial_delay_seconds = 0
        period_seconds        = 10
        timeout_seconds       = 3
        failure_threshold     = 12

        http_get {
          path = "/health/ready"
          port = 8080
        }
      }

      # A database outage should not trigger a container restart loop.
      liveness_probe {
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3

        http_get {
          path = "/health/live"
          port = 8080
        }
      }
    }
  }

  # SQL grants and Alembic must already have been run by the operator. Depending
  # on the job resource would only prove it exists, not that it ran successfully.
  depends_on = [
    google_project_service.required["run.googleapis.com"],
    google_project_iam_member.runtime_sql,
    google_secret_manager_secret_iam_member.runtime_openai,
  ]
}

# Google IAM permits browser requests; FastAPI still enforces sessions, ownership,
# exact origin, and CSRF for the application endpoints. This grants no SQL access.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
