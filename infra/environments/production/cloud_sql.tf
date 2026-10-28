resource "google_sql_database_instance" "chatbot" {
  project             = var.project_id
  name                = "chatbot-postgres"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = true

  settings {
    edition           = "ENTERPRISE"
    tier              = "db-g1-small"
    availability_type = "ZONAL"
    activation_policy = "ALWAYS"

    disk_type       = "PD_SSD"
    disk_size       = 10
    disk_autoresize = false

    deletion_protection_enabled = true
    connector_enforcement       = "REQUIRED"

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"

      # No authorized networks: use an authenticated Cloud SQL connector.
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    # Backup and restore workflows are outside the initial learning scope.
    backup_configuration {
      enabled                        = false
      point_in_time_recovery_enabled = false
    }
  }

  depends_on = [google_project_service.required["sqladmin.googleapis.com"]]
}

resource "google_sql_database" "chatbot" {
  project  = var.project_id
  name     = "chatbot"
  instance = google_sql_database_instance.chatbot.name
}

resource "google_sql_user" "runtime" {
  project  = var.project_id
  name     = trimsuffix(google_service_account.runtime.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.chatbot.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"

  # Table privileges are granted separately after schema initialization.
}

resource "google_sql_user" "migrations" {
  project  = var.project_id
  name     = trimsuffix(google_service_account.migrations.email, ".gserviceaccount.com")
  instance = google_sql_database_instance.chatbot.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"

  # Schema creation privileges are granted separately before Alembic runs.
}
