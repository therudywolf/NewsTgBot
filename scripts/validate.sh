#!/bin/bash
# Comprehensive validation script for NewsTgBot

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "🔍 NewsTgBot Validation Suite"
echo "=============================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=0

# Helper functions
pass() {
    echo -e "${GREEN}✅ $1${NC}"
}

fail() {
    echo -e "${RED}❌ $1${NC}"
    FAILED=$((FAILED + 1))
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 1. Check Python syntax
echo "1. Checking Python syntax..."
for f in *.py parsers/*.py; do
    if [ -f "$f" ]; then
        python -m py_compile "$f" 2>/dev/null && pass "$f" || fail "$f"
    fi
done
echo ""

# 2. Check for secrets in git
echo "2. Scanning for secrets..."
if command -v detect-secrets &> /dev/null; then
    if detect-secrets scan --baseline .secrets.baseline 2>/dev/null; then
        pass "No secrets detected"
    else
        fail "Secrets detected! Review .secrets.baseline"
    fi
else
    warn "detect-secrets not installed, skipping secret scan"
fi
echo ""

# 3. Check .env file
echo "3. Checking .env file..."
if grep -q "^TELEGRAM_BOT_TOKEN=$" .env; then
    pass ".env has empty token (good!)"
else
    fail ".env contains token data"
fi

if grep -q "^LLM_MODEL_NAME=$" .env; then
    pass ".env has empty model name"
else
    warn ".env may have model name"
fi
echo ""

# 4. Check .gitignore
echo "4. Validating .gitignore..."
if grep -q "^\.env$" .gitignore; then
    pass ".env is in .gitignore"
else
    fail ".env is NOT in .gitignore"
fi

if grep -q "^\*\.db$" .gitignore; then
    pass "Database files are in .gitignore"
else
    fail "Database files NOT in .gitignore"
fi
echo ""

# 5. Check Docker configuration
echo "5. Validating Docker configuration..."
if docker-compose config > /dev/null 2>&1; then
    pass "docker-compose.yml is valid"
else
    fail "docker-compose.yml has errors"
fi
echo ""

# 6. Check documentation
echo "6. Checking documentation..."
for doc in README.md CONTRIBUTING.md LICENSE; do
    if [ -f "$doc" ]; then
        pass "$doc exists"
    else
        fail "$doc is missing"
    fi
done
echo ""

# 7. Check tests
echo "7. Validating tests..."
if [ -d "tests" ]; then
    TEST_FILES=$(find tests -name "test_*.py" | wc -l)
    if [ "$TEST_FILES" -gt 0 ]; then
        pass "Found $TEST_FILES test files"
    else
        fail "No test files found in tests/"
    fi
else
    fail "tests/ directory not found"
fi
echo ""

# 8. Check for required files
echo "8. Checking required files..."
REQUIRED_FILES=(
    ".env.example"
    ".gitignore"
    ".pre-commit-config.yaml"
    ".github/workflows/tests.yml"
    ".github/workflows/quality.yml"
    ".secrets.baseline"
    "setup.cfg"
    "requirements.txt"
    "requirements-dev.txt"
    "CHANGELOG.md"
    "DEPLOYMENT.md"
    "AGPL-3.0-or-later"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ] || [ -d "$file" ]; then
        pass "$file exists"
    else
        fail "$file is missing"
    fi
done
echo ""

# 9. Check for common issues
echo "9. Scanning for common issues..."
if grep -r "print(" *.py 2>/dev/null | grep -v "logging" > /dev/null; then
    warn "Found print() statements - should use logging"
else
    pass "No bare print() statements found"
fi

if grep -r "except:" parsers/*.py bot.py 2>/dev/null | grep -v "# NOQA" > /dev/null; then
    warn "Found bare except clauses - should catch specific exceptions"
else
    pass "No bare except clauses found"
fi
echo ""

# 10. Check AGPL compliance
echo "10. Checking AGPL compliance..."
if [ -f "LICENSE" ]; then
    if grep -q "AGPL-3.0-or-later" LICENSE; then
        pass "LICENSE file mentions AGPL-3.0-or-later"
    else
        fail "LICENSE file does not mention AGPL-3.0-or-later"
    fi
else
    fail "LICENSE file not found"
fi

if [ -f "NOTICE" ]; then
    pass "NOTICE file exists"
else
    warn "NOTICE file not found"
fi
echo ""

# Summary
echo "=============================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All validations passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ $FAILED validation(s) failed${NC}"
    exit 1
fi

