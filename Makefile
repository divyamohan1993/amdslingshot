.PHONY: help install dev test lint format train run docker-build docker-up docker-down deploy clean

PYTHON := python3
PIP := pip3
VENV := .venv

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	$(PIP) install -r requirements.txt

dev: ## Install development dependencies
	$(PIP) install -r requirements.txt -r requirements-dev.txt

test: ## Run test suite
	$(PYTHON) -m pytest edge/tests/ -v --tb=short

test-fast: ## Run tests excluding slow/model tests
	$(PYTHON) -m pytest edge/tests/ -v --tb=short -m "not slow and not model"

lint: ## Run linters
	$(PYTHON) -m ruff check edge/ training/
	$(PYTHON) -m mypy edge/ --ignore-missing-imports

format: ## Auto-format code
	$(PYTHON) -m ruff format edge/ training/
	$(PYTHON) -m ruff check --fix edge/ training/

# --- Data & Training ---

generate-data: ## Generate training datasets
	$(PYTHON) training/scripts/generate_dataset.py --output-dir training/data

train: generate-data ## Train all ML models
	$(PYTHON) training/scripts/train_all_models.py --data-dir training/data --output-dir edge/models/weights

# --- Run ---

run: ## Run edge gateway server (development)
	$(PYTHON) -m uvicorn edge.main:app --host 0.0.0.0 --port 8000 --reload --log-level info

run-prod: ## Run edge gateway server (production)
	$(PYTHON) -m uvicorn edge.main:app --host 0.0.0.0 --port 8000 --workers 2 --log-level warning

# --- Docker ---

docker-build: ## Build Docker images
	docker compose build

docker-up: ## Start all services
	docker compose up -d

docker-down: ## Stop all services
	docker compose down

docker-logs: ## View logs
	docker compose logs -f

# --- Deployment ---

deploy-gcp: ## Deploy to GCP VM
	bash deploy/scripts/setup-gcp-vm.sh

deploy-terraform: ## Deploy infrastructure with Terraform
	cd cloud/terraform && terraform init && terraform plan && terraform apply

# --- Cleanup ---

clean: ## Remove generated files
	rm -rf training/data/*.parquet
	rm -rf edge/models/weights/*.onnx
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
