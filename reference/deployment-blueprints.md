# Deployment Blueprints (Reference)

Read this file when building autoconfig.sh, deploy/ directory, or scaling infrastructure. Not needed for every conversation.

## Autoconfig Script Structure
```
autoconfig.sh
  |-- Phase 1: System update + packages (apt-get, firewall, fail2ban)
  |-- Phase 2: Runtime install (nvm/Node, Python, etc.)
  |-- Phase 3: App dependencies (npm install / pip install)
  |-- Phase 4: Database setup (PostgreSQL/SQLite/Redis -- create DB, user, run migrations)
  |-- Phase 5: Build (npm run build / equivalent)
  |-- Phase 6: Reverse proxy config (Nginx/Caddy -> localhost:APP_PORT)
  |-- Phase 7: Process manager (systemd service / PM2 ecosystem)
  |-- Phase 8: SSL (Certbot if domain is configured, skip if CF proxy only)
  |-- Phase 9: Secret rotation (if rerun detected)
  |-- Phase 10: Health check + summary output
```

## Autoconfig Script Requirements (Full Detail)
1. **Fully idempotent.** Running 1 or 100 times produces the same result. On rerun: rotate secrets/certs, update packages, restart services cleanly.
2. **Zero manual intervention.** Blank Ubuntu instance to running app on port 80.
3. **Single script does everything:** system packages, runtime, database setup, build, reverse proxy (Nginx/Caddy), process manager (systemd/PM2), firewall (UFW -- 80, 443, 22 only), SSL (Certbot/Caddy auto-TLS), log rotation, app startup.
4. **All configurables in `.env`.** Domain, credentials, API keys, ports, feature flags. Sensible defaults except secrets.
5. **Automatic secret rotation on rerun.** DB passwords, API tokens, JWT secrets, session keys rotated. Old revoked, new generated and written to `.env`.
6. **Cloudflare proxy compatibility.** Serves on port 80. Configures `X-Forwarded-For`, `X-Real-IP`, CF-Connecting-IP headers. Trusts CF IP ranges.
7. **Health check endpoint.** `GET /health` returns `{ "status": "ok", "version": "x.x.x" }`. Script verifies 200 before reporting success.
8. **Structured output.** Timestamps every step. Success: summary (domain, IP, ports, services, health). Failure: exact step and reason.

## Project `deploy/` Directory Structure
```
deploy/
  |-- docker/
  |   |-- Dockerfile              # Multi-stage build, same image for all tiers
  |   |-- docker-compose.yml      # Local dev with all services (DB, Redis, etc.)
  |   |-- docker-compose.prod.yml # Single-host production (Tier 1)
  |-- k8s/
  |   |-- base/                   # Kustomize base manifests
  |   |   |-- deployment.yaml
  |   |   |-- service.yaml
  |   |   |-- hpa.yaml            # Horizontal Pod Autoscaler
  |   |   |-- kustomization.yaml
  |   |-- overlays/
  |       |-- staging/
  |       |-- production/
  |-- terraform/
  |   |-- modules/
  |   |   |-- gke-cluster/        # GKE cluster provisioning
  |   |   |-- cloud-sql/          # Managed PostgreSQL
  |   |   |-- redis/              # Memorystore Redis
  |   |   |-- cdn/                # Cloud CDN + Load Balancer
  |   |   |-- monitoring/         # Prometheus + Grafana + alerting
  |   |-- environments/
  |       |-- staging.tfvars
  |       |-- production.tfvars
  |-- scripts/
      |-- scale-up.sh             # Promote tier
      |-- scale-down.sh           # Reduce infra
      |-- migrate-db.sh           # Zero-downtime DB migration
      |-- rotate-secrets.sh       # Cluster-wide secret rotation
```

## Scaling Tiers (Full Detail)

| Tier | Users | Infrastructure | Trigger to Next |
|------|-------|---------------|-----------------|
| **Tier 0: MVP** | 0-10K | `autoconfig.sh` on single GCP instance behind Cloudflare | CPU >70% or p95 >500ms |
| **Tier 1: Vertical** | 10K-100K | Bigger instance + managed DB (Cloud SQL) + Redis + CDN | Single instance maxed |
| **Tier 2: Horizontal** | 100K-1M | Multiple instances + GCP LB + read replicas + Redis cluster | Replica lag, write limits |
| **Tier 3: Multi-Region** | 1M-50M | GKE 3+ regions + Spanner/CockroachDB + Kafka + CQRS | DB bottleneck, data locality |
| **Tier 4: Planet Scale** | 50M-2B+ | Per-region clusters + sharding + edge compute + event sourcing | Tier 3 cost/complexity limit |

## Hyperscale Patterns (Full Detail)
1. **Dockerfile from day one.** Multi-stage build: deps -> build -> slim runtime image.
2. **HPA on CPU (60%), memory (70%), latency (p95 < 200ms).** Min 3 replicas prod.
3. **DB connection abstraction.** Supports single instance, read replicas, multi-region routing, sharding. Config switches driver.
4. **Observability from Tier 0.** Structured JSON logs, OpenTelemetry tracing, Prometheus metrics, `/health` + `/ready` + `/live`. Alert on error rate, latency, saturation.
5. **Zero-downtime deployments.** Rolling (Tier 1-2), blue-green (Tier 3+), canary (Tier 4).
6. **Cost-aware.** Spot instances for non-critical. Auto-scale down. Budget alerts.
7. **Cloudflare at every tier.** DNS, DDoS, WAF, CDN, edge caching. Tier 3+: Workers for geo-routing, A/B, rate limiting.
