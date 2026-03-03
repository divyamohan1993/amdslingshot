# =============================================================================
# JalNetra - Terraform Outputs
# =============================================================================

# ---------------------------------------------------------------------------
# Instance Information
# ---------------------------------------------------------------------------
output "instance_name" {
  description = "Name of the GCP compute instance"
  value       = google_compute_instance.jalnetra_vm.name
}

output "instance_id" {
  description = "Instance ID of the GCP compute instance"
  value       = google_compute_instance.jalnetra_vm.instance_id
}

output "instance_zone" {
  description = "Zone where the instance is deployed"
  value       = google_compute_instance.jalnetra_vm.zone
}

output "machine_type" {
  description = "Machine type of the compute instance"
  value       = google_compute_instance.jalnetra_vm.machine_type
}

# ---------------------------------------------------------------------------
# Network Information
# ---------------------------------------------------------------------------
output "instance_external_ip" {
  description = "External (public) IP address of the JalNetra VM"
  value       = google_compute_address.jalnetra_ip.address
}

output "instance_internal_ip" {
  description = "Internal (private) IP address of the JalNetra VM"
  value       = google_compute_instance.jalnetra_vm.network_interface[0].network_ip
}

output "vpc_network" {
  description = "Name of the VPC network"
  value       = google_compute_network.jalnetra_vpc.name
}

output "subnet" {
  description = "Name of the subnet"
  value       = google_compute_subnetwork.jalnetra_subnet.name
}

# ---------------------------------------------------------------------------
# Access Commands
# ---------------------------------------------------------------------------
output "ssh_command" {
  description = "gcloud command to SSH into the VM"
  value       = "gcloud compute ssh ${google_compute_instance.jalnetra_vm.name} --zone=${google_compute_instance.jalnetra_vm.zone} --project=${var.project_id}"
}

output "scp_command" {
  description = "gcloud command to copy files to the VM"
  value       = "gcloud compute scp LOCAL_FILE ${google_compute_instance.jalnetra_vm.name}:/opt/jalnetra/ --zone=${google_compute_instance.jalnetra_vm.zone} --project=${var.project_id}"
}

# ---------------------------------------------------------------------------
# Application URLs
# ---------------------------------------------------------------------------
output "application_url" {
  description = "URL to access the JalNetra application"
  value       = var.domain != "" ? "https://${var.domain}" : "http://${google_compute_address.jalnetra_ip.address}"
}

output "api_health_url" {
  description = "URL to check API health"
  value       = "http://${google_compute_address.jalnetra_ip.address}:8000/api/v1/health"
}

output "dashboard_url" {
  description = "URL to access the JalNetra dashboard"
  value       = var.domain != "" ? "https://${var.domain}/dashboard" : "http://${google_compute_address.jalnetra_ip.address}/dashboard"
}

output "api_docs_url" {
  description = "URL to access the FastAPI interactive documentation"
  value       = "http://${google_compute_address.jalnetra_ip.address}:8000/docs"
}

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
output "backup_bucket_name" {
  description = "Name of the Cloud Storage bucket for backups"
  value       = google_storage_bucket.jalnetra_backups.name
}

output "backup_bucket_url" {
  description = "URL of the Cloud Storage bucket for backups"
  value       = google_storage_bucket.jalnetra_backups.url
}

# ---------------------------------------------------------------------------
# Service Account
# ---------------------------------------------------------------------------
output "service_account_email" {
  description = "Email of the JalNetra service account"
  value       = google_service_account.jalnetra_sa.email
}
