variable "project_id" {
  description = "Google Cloud project for the production environment."
  type        = string
}

variable "region" {
  description = "Google Cloud region for production resources."
  type        = string
}

variable "sql_admin_email" {
  description = "Personal Google user registered as an IAM PostgreSQL administrator; never an application identity."
  type        = string

  validation {
    condition     = length(var.sql_admin_email) <= 63 && can(regex("^[^@[:space:]]+@[^@[:space:]]+$", var.sql_admin_email))
    error_message = "sql_admin_email must be a Google user email of at most 63 characters."
  }
}

variable "backend_image" {
  description = "Published backend image pinned to an immutable sha256 digest."
  type        = string

  validation {
    condition     = can(regex("^[^[:space:]@]+@sha256:[0-9a-f]{64}$", var.backend_image))
    error_message = "backend_image must be a published image reference ending in @sha256:<64 lowercase hexadecimal characters>."
  }
}

variable "frontend_origin" {
  description = "Exact HTTPS frontend origin accepted by the backend, without a trailing slash."
  type        = string

  validation {
    condition     = can(regex("^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]+)?$", var.frontend_origin))
    error_message = "frontend_origin must be an exact HTTPS origin with a lowercase DNS hostname, no path, and no trailing slash."
  }
}

variable "model" {
  description = "Non-secret model selection: simulated or openai:<model-id>."
  type        = string
  default     = "openai:gpt-6.1-terra"

  validation {
    condition     = var.model == "simulated" || can(regex("^openai:[^[:space:]]+$", var.model))
    error_message = "model must be simulated or openai:<model-id>."
  }
}

variable "openai_secret_version" {
  description = "Enabled numeric Secret Manager version to inject; Terraform does not read its value."
  type        = string
  default     = "1"

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.openai_secret_version))
    error_message = "openai_secret_version must be a positive numeric version, not latest."
  }
}
