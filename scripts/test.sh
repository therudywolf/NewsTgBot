#!/bin/bash
# Run all tests and quality checks

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "🧪 NewsTgBot Test Suite"
echo "======================"
echo ""

# Check if venv is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Virtual environment not activated"
    echo "Run: source .venv/bin/activate"
    exit 1
fi

# 1. Run Python tests
echo "1. Running unit tests with pytest..."
if command -v pytest &> /dev/null; then
    pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing || exit 1
    echo ""
else
    echo "⚠️  pytest not found, skipping unit tests"
fi

# 2. Code formatting with Black
echo "2. Checking code format with Black..."
if command -v black &> /dev/null; then
    black --check . || (black . && echo "Auto-formatted files")
else
    echo "⚠️  black not found"
fi
echo ""

# 3. Import sorting with isort
echo "3. Checking import order with isort..."
if command -v isort &> /dev/null; then
    isort --check-only . || (isort . && echo "Auto-sorted imports")
else
    echo "⚠️  isort not found"
fi
echo ""

# 4. Linting with flake8
echo "4. Running flake8 linting..."
if command -v flake8 &> /dev/null; then
    flake8 . --max-line-length=120 --extend-ignore=E203,E266,E501,W503 || echo "⚠️  Some linting issues found (non-critical)"
else
    echo "⚠️  flake8 not found"
fi
echo ""

# 5. Type checking with mypy
echo "5. Running mypy type checks..."
if command -v mypy &> /dev/null; then
    mypy . --ignore-missing-imports || echo "⚠️  Some type issues found (non-critical)"
else
    echo "⚠️  mypy not found"
fi
echo ""

# 6. Docker validation
echo "6. Validating Docker configuration..."
if command -v docker-compose &> /dev/null; then
    docker-compose config > /dev/null && echo "✅ docker-compose.yml is valid"
else
    echo "⚠️  docker-compose not found"
fi
echo ""

# 7. Validation script
echo "7. Running comprehensive validation..."
if [ -x "scripts/validate.sh" ]; then
    bash scripts/validate.sh
else
    echo "⚠️  validation script not found"
fi
echo ""

echo "======================"
echo "✅ Test suite completed!"
echo ""
echo "Coverage report: htmlcov/index.html"

