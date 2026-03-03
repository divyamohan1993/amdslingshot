# Contributing to JalNetra

Thank you for your interest in contributing to JalNetra! This document provides guidelines and instructions for contributing.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Reporting Issues](#reporting-issues)

---

## Code of Conduct

This project follows a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/amdslingshot.git
   cd amdslingshot
   ```
3. **Set up** the development environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   make dev
   cp .env.example .env
   ```
4. **Create a branch** for your work:
   ```bash
   git checkout -b feature/your-feature-name
   ```

---

## Development Workflow

### Running the Project

```bash
# Edge gateway (hot-reload)
make run

# Dashboard
cd dashboard && npm install && npm run dev

# Full stack via Docker
make docker-build && make docker-up
```

### Running Tests

```bash
# Full test suite
make test

# Fast tests (skip slow/model tests)
make test-fast

# Lint and type-check
make lint

# Auto-format
make format
```

Always ensure tests pass and linting is clean before submitting a pull request.

---

## Coding Standards

### Python (Edge API & Training)

- **Python 3.11+** with type annotations
- **Ruff** for linting and formatting (configured in `pyproject.toml`)
- **mypy** for static type checking (strict mode)
- Line length: **100 characters**
- Follow PEP 8 naming conventions

### TypeScript (Dashboard)

- **TypeScript** strict mode
- **ESLint** for linting
- **Tailwind CSS** for styling
- Functional React components with hooks

### C++ (Firmware)

- **PlatformIO** build system
- Arduino framework conventions
- Constants via build flags in `platformio.ini`

---

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

### Types

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code refactoring (no feature/fix) |
| `test` | Adding or updating tests |
| `chore` | Build, CI, or tooling changes |
| `perf` | Performance improvement |

### Scopes

`edge`, `dashboard`, `firmware`, `training`, `cloud`, `deploy`, `docs`

### Examples

```
feat(edge): add pH trend prediction endpoint
fix(dashboard): correct map marker position on mobile
docs: update deployment instructions in README
test(edge): add integration tests for alert dispatcher
```

---

## Pull Requests

1. **One concern per PR** — keep changes focused.
2. **Update tests** if your change affects behaviour.
3. **Update documentation** if you change public APIs or configuration.
4. **Fill out the PR template** with a clear description.
5. **Link related issues** using `Closes #123` or `Fixes #123`.

### PR Checklist

- [ ] Tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] New code has type annotations
- [ ] Documentation updated (if applicable)
- [ ] Commit messages follow conventions

---

## Reporting Issues

When reporting a bug, please include:

1. **Description** of the issue
2. **Steps to reproduce**
3. **Expected** versus **actual** behaviour
4. **Environment** (OS, Python version, Node version, Docker version)
5. **Logs** or error messages (if applicable)

Use [GitHub Issues](https://github.com/divyamohan1993/amdslingshot/issues) to report bugs or request features.

---

## Questions?

If you have questions about contributing, open a [discussion](https://github.com/divyamohan1993/amdslingshot/discussions) or reach out to the team.
