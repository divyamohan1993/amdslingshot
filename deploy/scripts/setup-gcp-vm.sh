#!/usr/bin/env bash
# =============================================================================
# JalNetra - GCP VM Setup Script
# Creates and configures a Google Cloud VM for production deployment.
#
# Usage:
#   ./setup-gcp-vm.sh [--project PROJECT_ID] [--zone ZONE] [--machine-type TYPE]
#                      [--domain DOMAIN] [--repo-url REPO_URL]
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Sufficient GCP permissions (Compute Admin, Network Admin)
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Configuration (override via flags or environment variables)
# ---------------------------------------------------------------------------
PROJECT_ID="${GCP_PROJECT_ID:-}"
ZONE="${GCP_ZONE:-asia-south1-a}"
REGION="${GCP_REGION:-asia-south1}"
MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-medium}"
INSTANCE_NAME="${GCP_INSTANCE_NAME:-jalnetra-vm}"
DISK_SIZE="${GCP_DISK_SIZE:-30}"
IMAGE_FAMILY="ubuntu-2204-lts"
IMAGE_PROJECT="ubuntu-os-cloud"
DOMAIN="${JALNETRA_DOMAIN:-}"
REPO_URL="${JALNETRA_REPO_URL:-https://github.com/your-org/jalnetra.git}"
NETWORK_TAG="jalnetra-server"
SERVICE_ACCOUNT_NAME="jalnetra-sa"
STATIC_IP_NAME="jalnetra-ip"

# Logging
readonly LOG_PREFIX="[JalNetra-Setup]"
log_info()  { echo "${LOG_PREFIX} [INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_warn()  { echo "${LOG_PREFIX} [WARN]  $(date '+%Y-%m-%d %H:%M:%S') $*" >&2; }
log_error() { echo "${LOG_PREFIX} [ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" >&2; }
log_fatal() { log_error "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Parse command-line arguments
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --project)     PROJECT_ID="$2";     shift 2 ;;
            --zone)        ZONE="$2";           shift 2 ;;
            --region)      REGION="$2";         shift 2 ;;
            --machine-type) MACHINE_TYPE="$2";  shift 2 ;;
            --instance)    INSTANCE_NAME="$2";  shift 2 ;;
            --disk-size)   DISK_SIZE="$2";      shift 2 ;;
            --domain)      DOMAIN="$2";         shift 2 ;;
            --repo-url)    REPO_URL="$2";       shift 2 ;;
            --help|-h)     usage; exit 0 ;;
            *)             log_fatal "Unknown argument: $1" ;;
        esac
    done
}

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --project PROJECT_ID    GCP project ID (required)
  --zone ZONE             GCP zone (default: asia-south1-a)
  --region REGION         GCP region (default: asia-south1)
  --machine-type TYPE     VM machine type (default: e2-medium)
  --instance NAME         VM instance name (default: jalnetra-vm)
  --disk-size SIZE        Boot disk size in GB (default: 30)
  --domain DOMAIN         Domain name for SSL (optional)
  --repo-url URL          Git repository URL
  --help, -h              Show this help message

Environment variables:
  GCP_PROJECT_ID, GCP_ZONE, GCP_REGION, GCP_MACHINE_TYPE,
  GCP_INSTANCE_NAME, GCP_DISK_SIZE, JALNETRA_DOMAIN, JALNETRA_REPO_URL
EOF
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
preflight_checks() {
    log_info "Running preflight checks..."

    # Verify gcloud is installed
    if ! command -v gcloud &>/dev/null; then
        log_fatal "gcloud CLI is not installed. See: https://cloud.google.com/sdk/docs/install"
    fi

    # Verify project ID
    if [[ -z "${PROJECT_ID}" ]]; then
        PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
        if [[ -z "${PROJECT_ID}" ]]; then
            log_fatal "No project ID specified. Use --project or set GCP_PROJECT_ID."
        fi
        log_info "Using project from gcloud config: ${PROJECT_ID}"
    fi

    # Set project
    gcloud config set project "${PROJECT_ID}" --quiet

    # Verify authentication
    if ! gcloud auth list --filter="status:ACTIVE" --format="value(account)" 2>/dev/null | head -1 | grep -q '.'; then
        log_fatal "Not authenticated with gcloud. Run: gcloud auth login"
    fi

    # Enable required APIs
    log_info "Enabling required GCP APIs..."
    gcloud services enable compute.googleapis.com --quiet || true
    gcloud services enable storage.googleapis.com --quiet || true
    gcloud services enable iam.googleapis.com --quiet || true

    log_info "Preflight checks passed."
}

# ---------------------------------------------------------------------------
# Create service account with minimal permissions
# ---------------------------------------------------------------------------
create_service_account() {
    local sa_email="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

    if gcloud iam service-accounts describe "${sa_email}" &>/dev/null; then
        log_info "Service account ${sa_email} already exists, skipping creation."
    else
        log_info "Creating service account: ${SERVICE_ACCOUNT_NAME}..."
        gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
            --display-name="JalNetra Application Service Account" \
            --description="Minimal-permission SA for the JalNetra edge-AI water monitoring system" \
            --quiet
    fi

    # Assign minimal roles (idempotent)
    local roles=(
        "roles/logging.logWriter"
        "roles/monitoring.metricWriter"
        "roles/storage.objectViewer"
    )
    for role in "${roles[@]}"; do
        gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
            --member="serviceAccount:${sa_email}" \
            --role="${role}" \
            --condition=None \
            --quiet 2>/dev/null || true
    done

    log_info "Service account configured: ${sa_email}"
}

# ---------------------------------------------------------------------------
# Reserve a static external IP
# ---------------------------------------------------------------------------
reserve_static_ip() {
    if gcloud compute addresses describe "${STATIC_IP_NAME}" --region="${REGION}" &>/dev/null; then
        log_info "Static IP ${STATIC_IP_NAME} already exists."
    else
        log_info "Reserving static external IP: ${STATIC_IP_NAME}..."
        gcloud compute addresses create "${STATIC_IP_NAME}" \
            --region="${REGION}" \
            --quiet
    fi

    STATIC_IP=$(gcloud compute addresses describe "${STATIC_IP_NAME}" \
        --region="${REGION}" \
        --format="value(address)")
    log_info "Static IP: ${STATIC_IP}"
}

# ---------------------------------------------------------------------------
# Configure firewall rules
# ---------------------------------------------------------------------------
configure_firewall() {
    log_info "Configuring firewall rules..."

    # HTTP (80)
    if gcloud compute firewall-rules describe "jalnetra-allow-http" &>/dev/null; then
        log_info "Firewall rule jalnetra-allow-http already exists."
    else
        gcloud compute firewall-rules create "jalnetra-allow-http" \
            --direction=INGRESS \
            --priority=1000 \
            --network=default \
            --action=ALLOW \
            --rules=tcp:80 \
            --source-ranges=0.0.0.0/0 \
            --target-tags="${NETWORK_TAG}" \
            --description="Allow HTTP traffic to JalNetra" \
            --quiet
    fi

    # HTTPS (443)
    if gcloud compute firewall-rules describe "jalnetra-allow-https" &>/dev/null; then
        log_info "Firewall rule jalnetra-allow-https already exists."
    else
        gcloud compute firewall-rules create "jalnetra-allow-https" \
            --direction=INGRESS \
            --priority=1000 \
            --network=default \
            --action=ALLOW \
            --rules=tcp:443 \
            --source-ranges=0.0.0.0/0 \
            --target-tags="${NETWORK_TAG}" \
            --description="Allow HTTPS traffic to JalNetra" \
            --quiet
    fi

    # API port (8000) - for direct access during development
    if gcloud compute firewall-rules describe "jalnetra-allow-api" &>/dev/null; then
        log_info "Firewall rule jalnetra-allow-api already exists."
    else
        gcloud compute firewall-rules create "jalnetra-allow-api" \
            --direction=INGRESS \
            --priority=1000 \
            --network=default \
            --action=ALLOW \
            --rules=tcp:8000 \
            --source-ranges=0.0.0.0/0 \
            --target-tags="${NETWORK_TAG}" \
            --description="Allow direct API access to JalNetra (dev)" \
            --quiet
    fi

    log_info "Firewall rules configured."
}

# ---------------------------------------------------------------------------
# Generate the VM startup script (runs on first boot)
# ---------------------------------------------------------------------------
generate_startup_script() {
    cat <<'STARTUP_EOF'
#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
LOG_FILE="/var/log/jalnetra-setup.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "[$(date)] Starting JalNetra VM initialization..."

# -- System updates --
apt-get update -y
apt-get upgrade -y

# -- Install Docker --
if ! command -v docker &>/dev/null; then
    echo "[$(date)] Installing Docker..."
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo "[$(date)] Docker installed successfully."
else
    echo "[$(date)] Docker already installed."
fi

# -- Install docker-compose standalone (v2) --
if ! command -v docker-compose &>/dev/null && ! docker compose version &>/dev/null; then
    echo "[$(date)] Installing docker-compose plugin..."
    apt-get install -y docker-compose-plugin
fi

# -- Install additional tools --
apt-get install -y git curl wget htop unzip jq certbot python3-certbot-nginx nginx

# -- Create application user --
if ! id jalnetra &>/dev/null; then
    useradd -m -s /bin/bash -G docker jalnetra
    echo "[$(date)] User 'jalnetra' created."
fi

# -- Clone or update repository --
APP_DIR="/opt/jalnetra"
if [[ ! -d "${APP_DIR}" ]]; then
    mkdir -p "${APP_DIR}"
    chown jalnetra:jalnetra "${APP_DIR}"
    echo "[$(date)] Application directory created at ${APP_DIR}."
fi

# -- Create data directories --
mkdir -p "${APP_DIR}/data" "${APP_DIR}/models" "${APP_DIR}/logs" "${APP_DIR}/backups"
chown -R jalnetra:jalnetra "${APP_DIR}"

# -- Setup systemd service --
if [[ -f "${APP_DIR}/deploy/systemd/jalnetra.service" ]]; then
    cp "${APP_DIR}/deploy/systemd/jalnetra.service" /etc/systemd/system/jalnetra.service
    systemctl daemon-reload
    systemctl enable jalnetra.service
    echo "[$(date)] Systemd service installed."
fi

# -- Setup nginx --
if [[ -f "${APP_DIR}/deploy/nginx/jalnetra.conf" ]]; then
    cp "${APP_DIR}/deploy/nginx/jalnetra.conf" /etc/nginx/sites-available/jalnetra
    ln -sf /etc/nginx/sites-available/jalnetra /etc/nginx/sites-enabled/jalnetra
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl reload nginx
    echo "[$(date)] Nginx configured."
fi

# -- Setup log rotation --
cat > /etc/logrotate.d/jalnetra <<'LOGROTATE'
/opt/jalnetra/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 jalnetra jalnetra
    sharedscripts
}
LOGROTATE

echo "[$(date)] JalNetra VM initialization complete."
STARTUP_EOF
}

# ---------------------------------------------------------------------------
# Create the VM instance
# ---------------------------------------------------------------------------
create_vm_instance() {
    local sa_email="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

    if gcloud compute instances describe "${INSTANCE_NAME}" --zone="${ZONE}" &>/dev/null; then
        log_info "VM instance ${INSTANCE_NAME} already exists. Skipping creation."
        return 0
    fi

    log_info "Creating VM instance: ${INSTANCE_NAME} (${MACHINE_TYPE}) in ${ZONE}..."

    # Generate startup script to a temp file
    local startup_script_file
    startup_script_file=$(mktemp /tmp/jalnetra-startup-XXXXXX.sh)
    generate_startup_script > "${startup_script_file}"

    gcloud compute instances create "${INSTANCE_NAME}" \
        --zone="${ZONE}" \
        --machine-type="${MACHINE_TYPE}" \
        --image-family="${IMAGE_FAMILY}" \
        --image-project="${IMAGE_PROJECT}" \
        --boot-disk-size="${DISK_SIZE}GB" \
        --boot-disk-type="pd-balanced" \
        --address="${STATIC_IP}" \
        --tags="${NETWORK_TAG}" \
        --service-account="${sa_email}" \
        --scopes="logging-write,monitoring-write,storage-ro" \
        --metadata-from-file="startup-script=${startup_script_file}" \
        --labels="app=jalnetra,env=production,managed-by=setup-script" \
        --quiet

    rm -f "${startup_script_file}"

    log_info "VM instance created successfully."
    log_info "Waiting for VM to initialize (this may take 2-3 minutes)..."
    sleep 30

    # Wait for SSH to become available
    local retries=10
    while [[ ${retries} -gt 0 ]]; do
        if gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="echo 'SSH ready'" --quiet 2>/dev/null; then
            log_info "SSH connection established."
            break
        fi
        log_info "Waiting for SSH... (${retries} retries left)"
        sleep 15
        retries=$((retries - 1))
    done

    if [[ ${retries} -eq 0 ]]; then
        log_warn "Could not establish SSH connection. VM may still be initializing."
        log_warn "Try manually: gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}"
    fi
}

# ---------------------------------------------------------------------------
# Setup SSL with Let's Encrypt
# ---------------------------------------------------------------------------
setup_ssl() {
    if [[ -z "${DOMAIN}" ]]; then
        log_info "No domain specified. Skipping SSL setup."
        log_info "To setup SSL later, run on the VM:"
        log_info "  sudo certbot --nginx -d YOUR_DOMAIN --non-interactive --agree-tos -m admin@YOUR_DOMAIN"
        return 0
    fi

    log_info "Setting up SSL for domain: ${DOMAIN}..."

    gcloud compute ssh "${INSTANCE_NAME}" --zone="${ZONE}" --command="
        sudo certbot --nginx \
            -d ${DOMAIN} \
            --non-interactive \
            --agree-tos \
            -m admin@${DOMAIN} \
            --redirect \
            || echo 'SSL setup failed - domain may not be pointing to this IP yet.'
    " --quiet || log_warn "SSL setup requires domain DNS to be configured first."
}

# ---------------------------------------------------------------------------
# Print deployment summary
# ---------------------------------------------------------------------------
print_summary() {
    cat <<EOF

================================================================================
  JalNetra GCP VM Deployment Summary
================================================================================

  Project:       ${PROJECT_ID}
  Instance:      ${INSTANCE_NAME}
  Zone:          ${ZONE}
  Machine Type:  ${MACHINE_TYPE}
  Static IP:     ${STATIC_IP}
  Domain:        ${DOMAIN:-"(not configured)"}

  Access:
    SSH:         gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}
    HTTP:        http://${STATIC_IP}
    API:         http://${STATIC_IP}:8000/api/v1/health
    Dashboard:   http://${STATIC_IP}/dashboard

  Next Steps:
    1. SSH into the VM:
       gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}

    2. Clone your repository:
       cd /opt/jalnetra && git clone ${REPO_URL} .

    3. Create .env file:
       cp .env.example .env && nano .env

    4. Deploy the application:
       ./deploy/scripts/deploy.sh

    5. (Optional) Configure DNS and SSL:
       Point ${DOMAIN:-"your-domain.com"} A record to ${STATIC_IP}
       sudo certbot --nginx -d ${DOMAIN:-"your-domain.com"}

================================================================================
EOF
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
main() {
    log_info "=== JalNetra GCP VM Setup ==="
    parse_args "$@"
    preflight_checks
    create_service_account
    reserve_static_ip
    configure_firewall
    create_vm_instance
    setup_ssl
    print_summary
    log_info "=== Setup complete ==="
}

main "$@"
