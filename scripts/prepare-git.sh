#!/bin/bash
# Prepare repository for final commit and push

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "📦 Preparing repository for production"
echo "===================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 1. Check git status
echo "1. Checking git status..."
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${RED}❌ Not a git repository${NC}"
    exit 1
fi

UNSTAGED=$(git status --short | wc -l)
if [ "$UNSTAGED" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Found $UNSTAGED unstaged changes${NC}"
    git status --short | head -20
    echo ""
else
    echo -e "${GREEN}✅ Working directory clean${NC}"
fi
echo ""

# 2. Verify no secrets are staged
echo "2. Verifying no secrets in staging area..."
if git diff --cached | grep -E "(TOKEN|PASSWORD|SECRET|api_key|private)" > /dev/null 2>&1; then
    echo -e "${RED}❌ Found potential secrets in staged files${NC}"
    echo "Please review and remove before committing"
    exit 1
else
    echo -e "${GREEN}✅ No obvious secrets detected${NC}"
fi
echo ""

# 3. Check for large files
echo "3. Checking for large files..."
LARGE_FILES=$(find . -type f -size +10M ! -path './.git/*' ! -path './.venv/*' ! -path '*node_modules*' 2>/dev/null || true)
if [ -n "$LARGE_FILES" ]; then
    echo -e "${YELLOW}⚠️  Found large files:${NC}"
    echo "$LARGE_FILES"
else
    echo -e "${GREEN}✅ No unusually large files${NC}"
fi
echo ""

# 4. Verify .gitignore
echo "4. Verifying .gitignore..."
IGNORED_NOT_IN_INDEX=$(git status --ignored -s | grep "^!!" | wc -l)
if [ "$IGNORED_NOT_IN_INDEX" -gt 0 ]; then
    echo -e "${GREEN}✅ Found $IGNORED_NOT_IN_INDEX ignored files (good!)${NC}"
else
    echo -e "${YELLOW}⚠️  No ignored files detected${NC}"
fi
echo ""

# 5. Check commit history for sensitive data
echo "5. Scanning recent commits for secrets..."
if command -v git-secrets &> /dev/null; then
    git secrets --scan && echo -e "${GREEN}✅ No secrets found in history${NC}" || {
        echo -e "${RED}❌ Secrets found in git history${NC}"
        echo "Consider using: git filter-branch or BFG Repo-Cleaner"
        exit 1
    }
else
    echo -e "${YELLOW}⚠️  git-secrets not installed, skipping history scan${NC}"
    echo "Install with: npm install -g git-secrets"
fi
echo ""

# 6. Verify documentation
echo "6. Verifying documentation..."
DOCS_OK=true
for doc in README.md CONTRIBUTING.md CHANGELOG.md DEPLOYMENT.md; do
    if [ -f "$doc" ]; then
        LINES=$(wc -l < "$doc")
        echo "  ✓ $doc ($LINES lines)"
    else
        echo -e "  ${RED}✗ $doc missing${NC}"
        DOCS_OK=false
    fi
done
if [ "$DOCS_OK" = true ]; then
    echo -e "${GREEN}✅ All documentation complete${NC}"
fi
echo ""

# 7. Run validation
echo "7. Running validation suite..."
if [ -x "scripts/validate.sh" ]; then
    bash scripts/validate.sh || exit 1
else
    echo -e "${YELLOW}⚠️  Validation script not found${NC}"
fi
echo ""

# 8. Summary and instructions
echo "===================================="
echo -e "${GREEN}✅ Repository is ready for commit!${NC}"
echo ""
echo "Next steps:"
echo "  1. Review staged changes:     git diff --cached"
echo "  2. Commit your changes:       git commit -m 'message'"
echo "  3. Push to remote:            git push origin main"
echo ""
echo "For detailed commit message, use:"
echo "  git commit -m 'type: brief description'"
echo ""
echo "Types: feat, fix, docs, style, refactor, test, chore, ci"
echo ""

