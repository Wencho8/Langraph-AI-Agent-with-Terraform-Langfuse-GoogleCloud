locals {
  migration_environment = {
    DATABASE_MODE      = "cloud_sql"
    CLOUD_SQL_INSTANCE = google_sql_database_instance.chatbot.connection_name
    DATABASE_NAME      = google_sql_database.chatbot.name
    DATABASE_USER      = google_sql_user.migrations.name
  }
}

# This declares the job only. Execute it explicitly after granting SQL schema
# privileges; never run migrations automatically as part of terraform apply.
resource "google_cloud_run_v2_job" "migrations" {
  project             = var.project_id
  name                = "chatbot-migrate"
  location            = var.region
  deletion_protection = false

  # Seed a new job from backend_image; later releases select the migration image.
  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account       = google_service_account.migrations.email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      timeout               = "300s"
      max_retries           = 0

      containers {
        image   = var.backend_image
        command = ["alembic"]
        args    = ["upgrade", "head"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        dynamic "env" {
          for_each = local.migration_environment
          content {
            name  = env.key
            value = env.value
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.required["run.googleapis.com"],
    google_project_iam_member.migrations_sql,
  ]
}
