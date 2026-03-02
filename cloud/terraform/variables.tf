# =============================================================================
# JalNetra - Terraform Variables
# =============================================================================

# ---------------------------------------------------------------------------
# Project Configuration
# ---------------------------------------------------------------------------
variable "project_id" {
  description = "The GCP project ID where resources will be created"
  type        = string

  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "The GCP region for resource deployment (asia-south1 for India)"
  type        = string
  default     = "asia-south1"
}

variable "zone" {
  description = "The GCP zone within the region"
  type        = string
  default     = "asia-south1-a"
}

# ---------------------------------------------------------------------------
# Application Configuration
# ---------------------------------------------------------------------------
variable "app_name" {
  description = "Application name used as a prefix for all resources"
  type        = string
  default     = "jalnetra"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]+$", var.app_name))
    error_message = "app_name must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Deployment environment (production, staging, development)"
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "environment must be one of: production, staging, development."
  }
}

# ---------------------------------------------------------------------------
# Compute Configuration
# ---------------------------------------------------------------------------
variable "machine_type" {
  description = "GCP machine type for the VM instance (e2-medium recommended for production)"
  type        = string
  default     = "e2-medium"

  validation {
    condition = contains([
      "e2-micro", "e2-small", "e2-medium",
      "n1-standard-1", "n1-standard-2",
      "n2-standard-2",
    ], var.machine_type)
    error_message = "Unsupported machine type. Use e2-medium or n1-standard-2 for production."
  }
}

variable "disk_size" {
  description = "Boot disk size in GB"
  type        = number
  default     = 30

  validation {
    condition     = var.disk_size >= 20 && var.disk_size <= 500
    error_message = "disk_size must be between 20 and 500 GB."
  }
}

# ---------------------------------------------------------------------------
# Network Configuration
# ---------------------------------------------------------------------------
variable "network_tag" {
  description = "Network tag applied to the VM for firewall rule targeting"
  type        = string
  default     = "jalnetra-server"
}

variable "api_allowed_cidrs" {
  description = "CIDR ranges allowed to access the API port (8000) directly"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ---------------------------------------------------------------------------
# Domain Configuration (optional)
# ---------------------------------------------------------------------------
variable "domain" {
  description = "Domain name for the application (leave empty if not using a custom domain)"
  type        = string
  default     = ""
}

variable "enable_ssl" {
  description = "Whether to configure SSL certificate management"
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Backup Configuration
# ---------------------------------------------------------------------------
variable "backup_retention_days" {
  description = "Number of days to retain backups in Cloud Storage"
  type        = number
  default     = 30

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 365
    error_message = "backup_retention_days must be between 1 and 365."
  }
}
