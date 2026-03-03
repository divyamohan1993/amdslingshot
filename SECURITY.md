# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in JalNetra, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email **divyamohan1993@gmail.com** with:

1. A description of the vulnerability
2. Steps to reproduce
3. Potential impact
4. Suggested fix (if any)

We will acknowledge receipt within **48 hours** and provide a detailed response within **7 days**.

## Security Measures

JalNetra implements the following security practices:

### Authentication and Authorisation
- JWT-based authentication with configurable expiry
- bcrypt password hashing via passlib
- Role-based access for API endpoints

### Data Protection
- HTTPS/TLS encryption in transit (Let's Encrypt)
- Environment-based secrets management (never hardcoded)
- SQLite with WAL mode and foreign key constraints

### Infrastructure
- Non-root Docker container execution (UID 1000)
- Minimal base images (python:3.11-slim)
- GCP firewall rules restricted to IAP SSH and HTTP/HTTPS
- IAM service accounts with least-privilege roles

### Code Quality
- Static analysis with Ruff (includes flake8-bandit security rules)
- Type checking with mypy (strict mode)
- Dependency pinning in requirements.txt

## Disclosure Policy

We follow coordinated disclosure. Once a fix is available, we will:

1. Release a patched version
2. Publish a security advisory on GitHub
3. Credit the reporter (unless they prefer anonymity)
