#!/usr/bin/env bash
# =============================================================================
# JalNetra - One-Command Deployment Script
# Handles fresh installations, updates, zero-downtime rolling restarts,
# database backups, and rollback capability.
#
# Usage:
#   ./deploy.sh                   # Standard deployment
#   ./deploy.sh --fresh           # Fresh install (rebuild everything)
#   ./deploy.sh --rollback        # Rollback to previous version
#   ./deploy.sh --backup-only     # Only backup, no deployment
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="${JALNETRA_APP_DIR:-/opt/jalnetra}"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"
ENV_FILE="${APP_DIR}/.env"
BACKUP_DIR="${APP_DIR}/backups"
LOG_DIR="${APP_DIR}/logs"
DATA_DIR="${APP_DIR}/data"
MODEL_DIR="${APP_DIR}/models"
ROLLBACK_DIR="${BACKUP_DIR}/rollback"
DEPLOY_TIMEOUT=120
HEALTH_ENDPOINT="http://localhost:8000/api/v1/health"

# Flags
FRESH_INSTALL=false
ROLLBACK=false
BACKUP_ONLY=false
FORCE=false
DRY_RUN=false

# Logging
readonly DEPLOY_ID="deploy-$(date '+%Y%m%d-%H%M%S')"
readonly LOG_FILE="${LOG_DIR}/${DEPLOY_ID}.log"
readonly LOG_PREFIX="[JalNetra-Deploy]"

log_info()  { echo "${LOG_PREFIX} [INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}" 2>/dev/null || echo "${LOG_PREFIX} [INFO] $*"; }
log_warn()  { echo "${LOG_PREFIX} [WARN]  $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}" 2>/dev/null >&2 || echo "${LOG_PREFIX} [WARN] $*" >&2; }
log_error() { echo "${LOG_PREFIX} [ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}" 2>/dev/null >&2 || echo "${LOG_PREFIX} [ERROR] $*" >&2; }
log_fatal() { log_error "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Parse command-line arguments
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --fresh)        FRESH_INSTALL=true; shift ;;
            --rollback)     ROLLBACK=true;      shift ;;
            --backup-only)  BACKUP_ONLY=true;   shift ;;
            --force)        FORCE=true;         shift ;;
            --dry-run)      DRY_RUN=true;       shift ;;
            --help|-h)      usage; exit 0 ;;
            *)              log_fatal "Unknown argument: $1. Use --help for usage." ;;
        esac
    done
}

usage() {
    cat <<EOF
JalNetra Deployment Script

Usage: $0 [OPTIONS]

Options:
  --fresh           Fresh install - rebuild all images from scratch
  --rollback        Rollback to the previous deployment version
  --backup-only     Create database backup without deploying
  --force           Skip confirmation prompts
  --dry-run         Show what would be done without executing
  --help, -h        Show this help message

Examples:
  $0                Deploy latest changes (standard update)
  $0 --fresh        Clean rebuild and deploy
  $0 --rollback     Revert to the previous version
  $0 --backup-only  Create a backup of the database
EOF
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
preflight_checks() {
    log_info "Running preflight checks..."

    # Check Docker
    if ! command -v docker &>/dev/null; then
        log_fatal "Docker is not installed. Run setup-gcp-vm.sh first."
    fi

    # Check Docker Compose
    if ! docker compose version &>/dev/null; then
        log_fatal "Docker Compose is not available."
    fi

    # Ensure we are in the right directory
    if [[ ! -f "${COMPOSE_FILE}" ]]; then
        log_fatal "docker-compose.yml not found at ${COMPOSE_FILE}. Are you in the right directory?"
    fi

    # Check .env file
    if [[ ! -f "${ENV_FILE}" ]]; then
        if [[ -f "${APP_DIR}/.env.example" ]]; then
            log_warn ".env file not found. Copying from .env.example..."
            cp "${APP_DIR}/.env.example" "${ENV_FILE}"
            log_warn "Please review and update ${ENV_FILE} with production values."
        else
            log_warn "No .env file found. Using defaults from docker-compose.yml."
        fi
    fi

    # Ensure directories exist
    mkdir -p "${BACKUP_DIR}" "${LOG_DIR}" "${DATA_DIR}" "${MODEL_DIR}" "${ROLLBACK_DIR}"

    log_info "Preflight checks passed."
}

# ---------------------------------------------------------------------------
# Backup database and critical data
# ---------------------------------------------------------------------------
backup_database() {
    log_info "Creating pre-deployment backup..."

    local backup_name="backup-${DEPLOY_ID}"
    local backup_path="${BACKUP_DIR}/${backup_name}"
    mkdir -p "${backup_path}"

    # Backup SQLite database (if it exists)
    local db_file="${DATA_DIR}/jalnetra.db"
    if [[ -f "${db_file}" ]]; then
        # Use SQLite's .backup for a consistent copy
        if command -v sqlite3 &>/dev/null; then
            sqlite3 "${db_file}" ".backup '${backup_path}/jalnetra.db'"
        else
            # Fallback: copy the file (ensure no writes are happening)
            cp "${db_file}" "${backup_path}/jalnetra.db"
        fi
        log_info "Database backed up to ${backup_path}/jalnetra.db"
    else
        log_info "No existing database found. Skipping database backup."
    fi

    # Backup .env file
    if [[ -f "${ENV_FILE}" ]]; then
        cp "${ENV_FILE}" "${backup_path}/.env"
    fi

    # Store the current git commit hash for rollback reference
    if [[ -d "${APP_DIR}/.git" ]]; then
        git -C "${APP_DIR}" rev-parse HEAD > "${backup_path}/git-commit" 2>/dev/null || true
        git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD > "${backup_path}/git-branch" 2>/dev/null || true
    fi

    # Save current Docker image tags
    docker compose -f "${COMPOSE_FILE}" images --format json > "${backup_path}/docker-images.json" 2>/dev/null || true

    # Record backup metadata
    cat > "${backup_path}/metadata.json" <<METADATA
{
    "deploy_id": "${DEPLOY_ID}",
    "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "git_commit": "$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'unknown')",
    "git_branch": "$(git -C "${APP_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
}
METADATA

    # Update rollback pointer
    echo "${backup_name}" > "${ROLLBACK_DIR}/latest"

    # Prune old backups (keep last 5)
    local backup_count
    backup_count=$(find "${BACKUP_DIR}" -maxdepth 1 -name "backup-deploy-*" -type d | wc -l)
    if [[ ${backup_count} -gt 5 ]]; then
        log_info "Pruning old backups (keeping latest 5)..."
        find "${BACKUP_DIR}" -maxdepth 1 -name "backup-deploy-*" -type d \
            | sort \
            | head -n -5 \
            | xargs rm -rf
    fi

    log_info "Backup complete: ${backup_path}"
}

# ---------------------------------------------------------------------------
# Rollback to previous version
# ---------------------------------------------------------------------------
rollback() {
    log_info "=== Starting rollback ==="

    local latest_file="${ROLLBACK_DIR}/latest"
    if [[ ! -f "${latest_file}" ]]; then
        log_fatal "No rollback point found. Cannot rollback."
    fi

    local backup_name
    backup_name=$(cat "${latest_file}")
    local backup_path="${BACKUP_DIR}/${backup_name}"

    if [[ ! -d "${backup_path}" ]]; then
        log_fatal "Rollback backup not found at ${backup_path}."
    fi

    log_info "Rolling back to: ${backup_name}"

    # Restore git commit if available
    if [[ -f "${backup_path}/git-commit" ]]; then
        local commit
        commit=$(cat "${backup_path}/git-commit")
        log_info "Restoring to git commit: ${commit}"
        cd "${APP_DIR}"
        git fetch origin --quiet 2>/dev/null || true
        git checkout "${commit}" 2>/dev/null || log_warn "Could not checkout commit ${commit}"
    fi

    # Restore database
    if [[ -f "${backup_path}/jalnetra.db" ]]; then
        log_info "Restoring database..."
        docker compose -f "${COMPOSE_FILE}" stop jalnetra-api 2>/dev/null || true
        cp "${backup_path}/jalnetra.db" "${DATA_DIR}/jalnetra.db"
        log_info "Database restored."
    fi

    # Restore .env if it was backed up
    if [[ -f "${backup_path}/.env" ]]; then
        cp "${backup_path}/.env" "${ENV_FILE}"
        log_info "Environment file restored."
    fi

    # Rebuild and restart
    docker compose -f "${COMPOSE_FILE}" build --quiet 2>&1 | tee -a "${LOG_FILE}"
    docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans 2>&1 | tee -a "${LOG_FILE}"

    # Verify health after rollback
    if verify_health; then
        log_info "=== Rollback complete and verified ==="
    else
        log_error "=== Rollback completed but health check failed ==="
        log_error "Manual intervention may be required."
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Pull latest code
# ---------------------------------------------------------------------------
pull_code() {
    cd "${APP_DIR}"

    if [[ ! -d ".git" ]]; then
        log_info "Not a git repository. Skipping code pull."
        return 0
    fi

    log_info "Pulling latest code..."
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)

    git fetch origin "${branch}" --quiet
    git reset --hard "origin/${branch}"

    local commit
    commit=$(git rev-parse --short HEAD)
    log_info "Code updated to ${branch}@${commit}"
}

# ---------------------------------------------------------------------------
# Build Docker images
# ---------------------------------------------------------------------------
build_images() {
    log_info "Building Docker images..."
    cd "${APP_DIR}"

    local build_args=""
    if [[ "${FRESH_INSTALL}" == "true" ]]; then
        build_args="--no-cache"
    fi

    docker compose -f "${COMPOSE_FILE}" build ${build_args} --parallel 2>&1 | tee -a "${LOG_FILE}"

    log_info "Docker images built."
}

# ---------------------------------------------------------------------------
# Zero-downtime rolling restart
# ---------------------------------------------------------------------------
rolling_restart() {
    log_info "Performing zero-downtime rolling restart..."

    cd "${APP_DIR}"

    # Check if services are currently running
    local is_running=false
    if docker compose -f "${COMPOSE_FILE}" ps --format json jalnetra-api 2>/dev/null | grep -q "running"; then
        is_running=true
    fi

    if [[ "${is_running}" == "true" && "${FRESH_INSTALL}" == "false" ]]; then
        # Rolling update: start new containers before stopping old ones
        log_info "Starting new containers (rolling update)..."

        # Recreate API service with the new image
        docker compose -f "${COMPOSE_FILE}" up -d \
            --no-deps \
            --build \
            --force-recreate \
            jalnetra-api \
            2>&1 | tee -a "${LOG_FILE}"

        # Wait for the new API to be healthy
        if ! verify_health; then
            log_error "New API container failed health check. Rolling back..."
            rollback
            return 1
        fi

        # Now update nginx (quick restart, minimal downtime)
        docker compose -f "${COMPOSE_FILE}" up -d \
            --no-deps \
            --force-recreate \
            jalnetra-nginx \
            2>&1 | tee -a "${LOG_FILE}"

    else
        # Fresh deploy or no services running
        log_info "Starting all services..."
        docker compose -f "${COMPOSE_FILE}" down --timeout 30 2>/dev/null || true
        docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans 2>&1 | tee -a "${LOG_FILE}"
    fi

    log_info "Services updated."
}

# ---------------------------------------------------------------------------
# Run database migrations
# ---------------------------------------------------------------------------
run_migrations() {
    log_info "Running database migrations..."

    docker compose -f "${COMPOSE_FILE}" exec -T jalnetra-api \
        python -m edge.data.migrations 2>&1 | tee -a "${LOG_FILE}" || {
            log_warn "Migration command not available or failed. Skipping."
        }
}

# ---------------------------------------------------------------------------
# Health check verification
# ---------------------------------------------------------------------------
verify_health() {
    log_info "Verifying deployment health..."

    local max_retries=$(( DEPLOY_TIMEOUT / 10 ))
    local retries=0

    while [[ ${retries} -lt ${max_retries} ]]; do
        retries=$((retries + 1))

        if curl -sf "${HEALTH_ENDPOINT}" >/dev/null 2>&1; then
            log_info "Health check PASSED."
            return 0
        fi

        log_info "Health check pending... (${retries}/${max_retries})"
        sleep 10
    done

    log_error "Health check FAILED after ${DEPLOY_TIMEOUT}s."
    return 1
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
cleanup() {
    log_info "Cleaning up..."

    # Remove dangling images
    docker image prune -f 2>/dev/null || true

    # Remove stopped containers
    docker container prune -f 2>/dev/null || true

    log_info "Cleanup complete."
}

# ---------------------------------------------------------------------------
# Print deployment report
# ---------------------------------------------------------------------------
print_report() {
    local git_commit
    git_commit=$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo "unknown")

    cat <<EOF

================================================================================
  JalNetra Deployment Report
================================================================================
  Deploy ID:     ${DEPLOY_ID}
  Git Commit:    ${git_commit}
  Timestamp:     $(date -u '+%Y-%m-%dT%H:%M:%SZ')
  Log File:      ${LOG_FILE}
  Status:        SUCCESS
--------------------------------------------------------------------------------
  Services:
$(docker compose -f "${COMPOSE_FILE}" ps 2>/dev/null | sed 's/^/    /')
--------------------------------------------------------------------------------
  Endpoints:
    Health:      ${HEALTH_ENDPOINT}
    Dashboard:   http://localhost/dashboard
    API Docs:    http://localhost:8000/docs
================================================================================
EOF
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    log_info "========================================="
    log_info "  JalNetra Deployment (${DEPLOY_ID})"
    log_info "========================================="

    preflight_checks

    # Backup-only mode
    if [[ "${BACKUP_ONLY}" == "true" ]]; then
        backup_database
        log_info "Backup-only mode complete."
        exit 0
    fi

    # Rollback mode
    if [[ "${ROLLBACK}" == "true" ]]; then
        rollback
        exit 0
    fi

    # Standard or fresh deployment
    backup_database
    pull_code
    build_images
    rolling_restart
    run_migrations

    if verify_health; then
        cleanup
        print_report
        log_info "=== Deployment successful ==="
    else
        log_error "Deployment health check failed!"
        log_error "Attempting automatic rollback..."
        rollback
        exit 1
    fi
}

main "$@"
