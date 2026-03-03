#!/usr/bin/env bash
# =============================================================================
# JalNetra - VM Startup Script
# Pulls latest code, builds images, runs migrations, and starts services.
#
# Usage:
#   ./startup.sh [--skip-build] [--skip-pull] [--train-models]
#
# This script is designed to be run on VM boot or manually for updates.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="${JALNETRA_APP_DIR:-/opt/jalnetra}"
COMPOSE_FILE="${APP_DIR}/docker-compose.yml"
ENV_FILE="${APP_DIR}/.env"
LOG_DIR="${APP_DIR}/logs"
BACKUP_DIR="${APP_DIR}/backups"
SKIP_BUILD=false
SKIP_PULL=false
TRAIN_MODELS=false

# Logging
readonly LOG_FILE="${LOG_DIR}/startup-$(date '+%Y%m%d-%H%M%S').log"
readonly LOG_PREFIX="[JalNetra-Startup]"

log_info()  { echo "${LOG_PREFIX} [INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}"; }
log_warn()  { echo "${LOG_PREFIX} [WARN]  $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}" >&2; }
log_error() { echo "${LOG_PREFIX} [ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "${LOG_FILE}" >&2; }
log_fatal() { log_error "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --skip-build)    SKIP_BUILD=true;   shift ;;
            --skip-pull)     SKIP_PULL=true;    shift ;;
            --train-models)  TRAIN_MODELS=true; shift ;;
            --help|-h)
                echo "Usage: $0 [--skip-build] [--skip-pull] [--train-models]"
                exit 0
                ;;
            *) log_fatal "Unknown argument: $1" ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Ensure directories exist
# ---------------------------------------------------------------------------
ensure_directories() {
    log_info "Ensuring application directories exist..."
    mkdir -p "${LOG_DIR}" "${BACKUP_DIR}" "${APP_DIR}/data" "${APP_DIR}/models"
}

# ---------------------------------------------------------------------------
# Pull latest code from repository
# ---------------------------------------------------------------------------
pull_latest_code() {
    if [[ "${SKIP_PULL}" == "true" ]]; then
        log_info "Skipping code pull (--skip-pull)."
        return 0
    fi

    log_info "Pulling latest code..."
    cd "${APP_DIR}"

    if [[ -d ".git" ]]; then
        # Stash any local changes
        git stash --quiet 2>/dev/null || true

        # Pull latest from current branch
        local branch
        branch=$(git rev-parse --abbrev-ref HEAD)
        git fetch origin "${branch}" --quiet
        git reset --hard "origin/${branch}"

        local commit
        commit=$(git rev-parse --short HEAD)
        log_info "Updated to commit: ${commit} on branch: ${branch}"
    else
        log_warn "Not a git repository. Skipping pull."
    fi
}

# ---------------------------------------------------------------------------
# Build Docker images
# ---------------------------------------------------------------------------
build_images() {
    if [[ "${SKIP_BUILD}" == "true" ]]; then
        log_info "Skipping Docker build (--skip-build)."
        return 0
    fi

    log_info "Building Docker images..."
    cd "${APP_DIR}"

    docker compose -f "${COMPOSE_FILE}" build \
        --no-cache \
        --parallel \
        2>&1 | tee -a "${LOG_FILE}"

    log_info "Docker images built successfully."
}

# ---------------------------------------------------------------------------
# Run database migrations
# ---------------------------------------------------------------------------
run_migrations() {
    log_info "Running database migrations..."

    # Run migrations inside the API container
    docker compose -f "${COMPOSE_FILE}" run \
        --rm \
        --no-deps \
        -e JALNETRA_ENV=production \
        jalnetra-api \
        python -m edge.data.migrations 2>&1 | tee -a "${LOG_FILE}" || {
            log_warn "Migration command not found or failed. This is expected on first run."
            log_info "Database will be initialized on first application start."
        }

    log_info "Database migrations complete."
}

# ---------------------------------------------------------------------------
# Train models if weights do not exist
# ---------------------------------------------------------------------------
train_models_if_needed() {
    local model_dir="${APP_DIR}/models"
    local models_exist=false

    # Check for any ONNX or model files
    if find "${model_dir}" -name "*.onnx" -o -name "*.json" -o -name "*.pkl" 2>/dev/null | head -1 | grep -q .; then
        models_exist=true
    fi

    if [[ "${models_exist}" == "true" && "${TRAIN_MODELS}" == "false" ]]; then
        log_info "Model weights found in ${model_dir}. Skipping training."
        return 0
    fi

    if [[ "${TRAIN_MODELS}" == "true" || "${models_exist}" == "false" ]]; then
        log_info "Training models (this may take several minutes)..."

        docker compose -f "${COMPOSE_FILE}" run \
            --rm \
            --no-deps \
            -e JALNETRA_ENV=production \
            -e JALNETRA_MODEL_DIR=/app/models \
            jalnetra-api \
            python -m training.scripts.train_all 2>&1 | tee -a "${LOG_FILE}" || {
                log_warn "Model training script not available or failed."
                log_info "Models can be trained later with: docker compose run jalnetra-api python -m training.scripts.train_all"
            }
    fi
}

# ---------------------------------------------------------------------------
# Start docker-compose services
# ---------------------------------------------------------------------------
start_services() {
    log_info "Starting JalNetra services..."
    cd "${APP_DIR}"

    # Stop any running containers gracefully
    docker compose -f "${COMPOSE_FILE}" down --timeout 30 2>/dev/null || true

    # Start all services in detached mode
    docker compose -f "${COMPOSE_FILE}" up -d --remove-orphans 2>&1 | tee -a "${LOG_FILE}"

    log_info "Services started."
}

# ---------------------------------------------------------------------------
# Health check verification
# ---------------------------------------------------------------------------
verify_health() {
    log_info "Verifying service health..."

    local max_retries=12
    local retry_interval=10
    local retries=0

    while [[ ${retries} -lt ${max_retries} ]]; do
        retries=$((retries + 1))

        # Check if API container is running
        if ! docker compose -f "${COMPOSE_FILE}" ps --format json jalnetra-api 2>/dev/null | grep -q "running"; then
            log_warn "API container not running yet. Attempt ${retries}/${max_retries}..."
            sleep "${retry_interval}"
            continue
        fi

        # Check health endpoint
        if curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then
            log_info "Health check PASSED - API is responding."

            # Print service status
            echo ""
            docker compose -f "${COMPOSE_FILE}" ps 2>/dev/null
            echo ""

            log_info "JalNetra is running and healthy."
            return 0
        fi

        log_info "Waiting for API to become healthy... (${retries}/${max_retries})"
        sleep "${retry_interval}"
    done

    log_error "Health check FAILED after ${max_retries} attempts."
    log_error "Check logs with: docker compose -f ${COMPOSE_FILE} logs jalnetra-api"
    docker compose -f "${COMPOSE_FILE}" logs --tail=50 jalnetra-api 2>&1 | tee -a "${LOG_FILE}"
    return 1
}

# ---------------------------------------------------------------------------
# Cleanup old Docker resources
# ---------------------------------------------------------------------------
cleanup() {
    log_info "Cleaning up unused Docker resources..."
    docker image prune -f --filter "until=168h" 2>/dev/null || true
    docker volume prune -f --filter "label!=com.jalnetra" 2>/dev/null || true
    log_info "Cleanup complete."
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    log_info "========================================="
    log_info "  JalNetra Startup Sequence"
    log_info "========================================="
    log_info "App directory: ${APP_DIR}"
    log_info "Log file: ${LOG_FILE}"

    ensure_directories
    pull_latest_code
    build_images
    run_migrations
    train_models_if_needed
    start_services
    verify_health
    cleanup

    log_info "========================================="
    log_info "  Startup complete!"
    log_info "========================================="
    log_info "  API:       http://localhost:8000/api/v1/health"
    log_info "  Dashboard: http://localhost/dashboard"
    log_info "  Logs:      ${LOG_FILE}"
    log_info "========================================="
}

main "$@"
