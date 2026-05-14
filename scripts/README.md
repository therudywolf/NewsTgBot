# NewsTgBot Helper Scripts

This directory contains utility scripts for development, testing, and deployment.

## Usage

### Validate Code Quality

```bash
bash scripts/validate.sh
```

Performs comprehensive checks:
- Python syntax validation
- Secret detection
- .env file verification
- Docker configuration validation
- Documentation completeness
- AGPL compliance verification

### Run Test Suite

```bash
bash scripts/test.sh
```

Executes:
- Unit tests with pytest (with coverage report)
- Code formatting with Black
- Import sorting with isort
- Linting with flake8
- Type checking with mypy
- Docker validation
- Comprehensive validation

**Requirements:**
- Virtual environment activated
- Dependencies installed: `pip install -r requirements-dev.txt`

### Prepare for Git Commit

```bash
bash scripts/prepare-git.sh
```

Ensures:
- No secrets in staged files
- No large files being committed
- .gitignore is properly configured
- Documentation is complete
- All validations pass

**Output:**
- Next steps for committing and pushing
- Recommended commit message format

## Making Scripts Executable

```bash
chmod +x scripts/*.sh
```

## Troubleshooting

### Permission Denied

```bash
# Make executable
chmod +x scripts/validate.sh scripts/test.sh scripts/prepare-git.sh
```

### Virtual Environment Not Activated

```bash
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate      # Windows
```

### Missing Dependencies

```bash
pip install -r requirements-dev.txt
```

### Docker Not Found

```bash
# Install Docker Desktop or Docker CLI
# macOS/Windows: https://www.docker.com/products/docker-desktop
# Linux: https://docs.docker.com/engine/install/
```

## Script Dependencies

| Script | Requires | Optional |
|--------|----------|----------|
| validate.sh | Python, git | detect-secrets, docker-compose |
| test.sh | pytest, venv | black, isort, flake8, mypy |
| prepare-git.sh | git | git-secrets |

## CI/CD Integration

These scripts are automatically run by GitHub Actions:
- `.github/workflows/quality.yml` - Code quality checks
- `.github/workflows/tests.yml` - Unit tests and Docker build

## Contributing

When adding new scripts:
1. Use bash as shebang: `#!/bin/bash`
2. Add error handling: `set -e`
3. Add colored output for clarity
4. Document in this README
5. Test locally before committing

