# =============================================================================
# JalNetra - Terraform Infrastructure as Code
# Google Cloud Platform deployment for edge-AI water quality monitoring
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Uncomment to use remote state storage in GCS
  # backend "gcs" {
  #   bucket = "jalnetra-terraform-state"
  #   prefix = "terraform/state"
  # }
}

# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# ---------------------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------------------
data "google_project" "current" {
  project_id = var.project_id
}

# ---------------------------------------------------------------------------
# VPC Network
# ---------------------------------------------------------------------------
resource "google_compute_network" "jalnetra_vpc" {
  name                    = "${var.app_name}-vpc"
  auto_create_subnetworks = false
  description             = "VPC network for JalNetra water quality monitoring system"
}

resource "google_compute_subnetwork" "jalnetra_subnet" {
  name          = "${var.app_name}-subnet"
  ip_cidr_range = "10.10.0.0/24"
  region        = var.region
  network       = google_compute_network.jalnetra_vpc.id

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# ---------------------------------------------------------------------------
# Firewall Rules
# ---------------------------------------------------------------------------

# Allow SSH (restricted to IAP for security)
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "${var.app_name}-allow-iap-ssh"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # IAP IP range for secure SSH tunneling
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [var.network_tag]
  description   = "Allow SSH via Identity-Aware Proxy"
}

# Allow HTTP
resource "google_compute_firewall" "allow_http" {
  name    = "${var.app_name}-allow-http"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.network_tag]
  description   = "Allow HTTP traffic for JalNetra dashboard"
}

# Allow HTTPS
resource "google_compute_firewall" "allow_https" {
  name    = "${var.app_name}-allow-https"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.network_tag]
  description   = "Allow HTTPS traffic for JalNetra dashboard"
}

# Allow API port (8000) - for direct access
resource "google_compute_firewall" "allow_api" {
  name    = "${var.app_name}-allow-api"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["8000"]
  }

  source_ranges = var.api_allowed_cidrs
  target_tags   = [var.network_tag]
  description   = "Allow direct API access to JalNetra (port 8000)"
}

# Allow internal communication
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.app_name}-allow-internal"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = ["10.10.0.0/24"]
  description   = "Allow internal VPC communication"
}

# Allow health check probes from GCP
resource "google_compute_firewall" "allow_health_check" {
  name    = "${var.app_name}-allow-health-check"
  network = google_compute_network.jalnetra_vpc.name

  allow {
    protocol = "tcp"
    ports    = ["8000"]
  }

  # GCP health check IP ranges
  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
  target_tags   = [var.network_tag]
  description   = "Allow GCP health check probes"
}

# ---------------------------------------------------------------------------
# Static External IP
# ---------------------------------------------------------------------------
resource "google_compute_address" "jalnetra_ip" {
  name         = "${var.app_name}-static-ip"
  region       = var.region
  address_type = "EXTERNAL"
  description  = "Static IP for JalNetra application"
}

# ---------------------------------------------------------------------------
# Service Account (minimal permissions)
# ---------------------------------------------------------------------------
resource "google_service_account" "jalnetra_sa" {
  account_id   = "${var.app_name}-sa"
  display_name = "JalNetra Application Service Account"
  description  = "Minimal-permission service account for JalNetra edge-AI system"
}

# Logging write access
resource "google_project_iam_member" "sa_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.jalnetra_sa.email}"
}

# Monitoring metrics write access
resource "google_project_iam_member" "sa_monitoring" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.jalnetra_sa.email}"
}

# Storage read access (for model artifacts)
resource "google_project_iam_member" "sa_storage" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.jalnetra_sa.email}"
}

# Storage write access for backup bucket only
resource "google_storage_bucket_iam_member" "sa_backup_writer" {
  bucket = google_storage_bucket.jalnetra_backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.jalnetra_sa.email}"
}

# ---------------------------------------------------------------------------
# Compute Instance
# ---------------------------------------------------------------------------
resource "google_compute_instance" "jalnetra_vm" {
  name         = "${var.app_name}-vm"
  machine_type = var.machine_type
  zone         = var.zone

  tags = [var.network_tag]

  labels = {
    app         = var.app_name
    environment = var.environment
    managed_by  = "terraform"
  }

  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = var.disk_size
      type  = "pd-balanced"
      labels = {
        app = var.app_name
      }
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.jalnetra_subnet.id

    access_config {
      nat_ip = google_compute_address.jalnetra_ip.address
    }
  }

  service_account {
    email  = google_service_account.jalnetra_sa.email
    scopes = [
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
      "https://www.googleapis.com/auth/devstorage.read_only",
    ]
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  metadata_startup_script = templatefile("${path.module}/../../deploy/scripts/startup.sh", {})

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  allow_stopping_for_update = true

  lifecycle {
    ignore_changes = [
      metadata_startup_script,
    ]
  }
}

# ---------------------------------------------------------------------------
# Cloud Storage Bucket (backups)
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "jalnetra_backups" {
  name          = "${var.project_id}-${var.app_name}-backups"
  location      = var.region
  storage_class = "STANDARD"
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      age                = 7
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    app         = var.app_name
    environment = var.environment
    purpose     = "backups"
  }
}

# ---------------------------------------------------------------------------
# Cloud Router and NAT (for outbound internet from private instances)
# ---------------------------------------------------------------------------
resource "google_compute_router" "jalnetra_router" {
  name    = "${var.app_name}-router"
  region  = var.region
  network = google_compute_network.jalnetra_vpc.id
}

resource "google_compute_router_nat" "jalnetra_nat" {
  name                               = "${var.app_name}-nat"
  router                             = google_compute_router.jalnetra_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
