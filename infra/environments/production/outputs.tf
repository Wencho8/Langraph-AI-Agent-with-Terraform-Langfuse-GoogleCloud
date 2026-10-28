output "sql_instance_name" {
  description = "Cloud SQL instance name for console and CLI inspection."
  value       = google_sql_database_instance.chatbot.name
}

output "sql_connection_name" {
  description = "Instance connection name used by the Cloud SQL connector."
  value       = google_sql_database_instance.chatbot.connection_name
}

output "sql_database_name" {
  description = "Application database name."
  value       = google_sql_database.chatbot.name
}

output "sql_runtime_user" {
  description = "PostgreSQL IAM username for the backend service account."
  value       = google_sql_user.runtime.name
}

output "sql_migrations_user" {
  description = "PostgreSQL IAM username for the migration service account."
  value       = google_sql_user.migrations.name
}

output "migration_job_name" {
  description = "Cloud Run migration job; execute explicitly only after SQL grants are ready."
  value       = google_cloud_run_v2_job.migrations.name
}

output "sql_admin_user" {
  description = "Personal IAM PostgreSQL administrator used for explicit privilege setup."
  value       = google_sql_user.admin.name
}

output "backend_service_name" {
  description = "Cloud Run backend service name for logs and console inspection."
  value       = google_cloud_run_v2_service.backend.name
}

output "backend_url" {
  description = "Cloud Run backend HTTPS URL; this is not the frontend origin."
  value       = google_cloud_run_v2_service.backend.uri
}

output "frontend_origin" {
  description = "Configured frontend origin; Hosting publication is a separate step."
  value       = var.frontend_origin
}
