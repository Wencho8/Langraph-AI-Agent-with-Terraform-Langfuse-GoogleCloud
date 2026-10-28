# Human administration is separate from the runtime and migration identities.
resource "google_project_iam_member" "sql_admin_access" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/cloudsql.instanceUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "user:${var.sql_admin_email}"

  depends_on = [google_project_service.required["sqladmin.googleapis.com"]]
}

resource "google_sql_user" "admin" {
  project  = var.project_id
  instance = google_sql_database_instance.chatbot.name
  name     = var.sql_admin_email
  type     = "CLOUD_IAM_USER"

  database_roles = [
    "cloudsqlsuperuser",
    # Lets the human SET ROLE to configure defaults for objects created by
    # migrations. Neither application account receives cloudsqlsuperuser.
    google_sql_user.migrations.name,
  ]

  depends_on = [google_project_iam_member.sql_admin_access]
}
