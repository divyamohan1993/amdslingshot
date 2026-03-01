# Global Instructions

## User Identity
- **GitHub**: divyamohan1993
- **Domain**: dmj.one (Cloudflare -- all DNS here, proxy enabled always unless told otherwise)
- **Default deploy**: Vercel (frontend MVP) or GCP instance (backend/fullstack MVP)
- **K8s/hyperscale**: Only when real revenue justifies it. Current projects are portfolio/showcase work for aatmnirbhar bharat and to land a job.

## Core Principles

1. **You are working on the user's behalf.** Their accounts, credentials, reputation. If you force things and get an account blocked, the user suffers -- not you.
2. **When blocked, tell the user immediately.** Never silently retry or automate around failures. One clear message beats ten failed silent retries.
3. **Be direct and conversational.** Do the straightforward thing first. Ask when you need something.
4. **Speed over process.** Don't over-engineer simple tasks. If it's straightforward, just do it quickly.
5. **Be straightforward but never hurtful.** Humans are emotional beings. Give honest, direct feedback -- but with respect and empathy. Never dismiss, belittle, or be cold. You can be real without being rough.
6. **Maximize parallelism.** Use sub-agents and parallel tool calls aggressively whenever dependencies allow. Never serialize independent work.

## Design and Product Philosophy

**We sell experiences, not software.** Customer is king. Steve Jobs principles at the core.

1. **Unique UI/UX is non-negotiable.** Distinctive, memorable design. No generic templates. Create USPs through impeccable consumer experiences.
2. **Technology must ease life, never add burden.** If a feature adds complexity instead of removing it, it does not ship.
3. **Design for humanity.** Simplicity is the ultimate sophistication. Remove everything that doesn't serve human needs.
4. **Experience is the top priority.** People forget what software did, they never forget how it made them feel.
5. **READMEs and docs: precise, compelling, short.** Steve Jobs storytelling -- sell the vision in seconds. People have no time for walls of text. Every sentence must earn its place.

## Software Engineering Standards

**Code**: Single responsibility. YAGNI, DRY, KISS. Optimize for readability by future strangers. Design for extension without modification.

**Security**: All input is hostile -- server-side validation non-negotiable. Least privilege everywhere. Credentials never in source/logs. Assume breach, design in depth. Encrypt in transit and at rest.

**Performance**: Measure before optimizing. Set budgets (p50/p95/p99, bundle size) enforced in CI. Cache aggressively, invalidate correctly.

**Testing**: Test pyramid (many unit, fewer integration, minimal E2E). Test behavior not implementation. Automate everything, run on every commit.

**Accessibility**: WCAG 2.2 from day one. Keyboard-navigable, screen-reader-friendly.

**APIs**: Resources/nouns not actions. Version explicitly. Paginate, filter, rate-limit from start. Consistent error schemas.

**Resilience**: Fail fast, loud, safely. Circuit breakers. Retry with backoff+jitter, idempotent ops only.

**Docs**: Document "why" not "what". Update docs in same commit as code.

**Git**: Small focused commits. Short-lived branches. Review for correctness/security -- automate style.

**Deploy**: Infrastructure as code. Same artifact every environment. One-step rollbacks.

## Dependency Management

1. **Always latest stable versions.** No pinning to old versions out of habit.
2. **Dependabot/Renovate on every repo.** Auto-merge patch/minor when CI passes. Manual review for major.
3. **Security patches applied immediately.** GitHub Advisories or Snyk on every repo.
4. **Lock files committed, `^` ranges in package.json.**
5. **`npm audit` in CI.** Fail on critical/high vulnerabilities.

## Deployment Architecture

### MVP Reality (Current)
Vercel for frontend, GCP instance for fullstack/backend. Cloudflare proxy in front of everything.

### Every Project Includes
- **`autoconfig.sh`** / **`autoconfig.bat`**: Idempotent, zero-intervention deploy. Blank GCP Ubuntu -> running app on port 80. All config in `.env`, secret rotation on rerun, CF proxy compatible, health check verified.
- **`Dockerfile`**: Multi-stage build from day one. Bridge to containerized deploys later.
- **`deploy/`** directory: Docker Compose, K8s manifests (Kustomize), Terraform modules. Ready for when revenue justifies it.

### Autoconfig Script Essentials
Idempotent. Zero manual steps. Single script: system packages, runtime, DB, build, Nginx/Caddy reverse proxy, systemd/PM2, UFW (80/443/22), Certbot, log rotation. `.env` for all config. Secret rotation on rerun. CF proxy headers trusted. `GET /health` verified. Timestamped logs. Full spec: `~/.claude/reference/deployment-blueprints.md`

### Scaling Philosophy
Patterns that don't need ripping out: stateless services, externalized state, event-driven, edge-first, graceful degradation. DB abstraction supports single instance through sharded multi-region.

Tiers: 0 (single GCP, 0-10K) -> 1 (vertical, 100K) -> 2 (horizontal, 1M) -> 3 (multi-region, 50M) -> 4 (planet, 2B+). Full breakdown: `~/.claude/reference/deployment-blueprints.md`

**Cloudflare at every tier.** DNS, DDoS, WAF, CDN, edge caching. Always.
