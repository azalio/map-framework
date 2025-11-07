---
description: Execute MAP Framework package release workflow with validation gates
---

# MAP Framework Release Workflow

**CRITICAL INSTRUCTION:** This is an **automated sequential workflow with IRREVERSIBLE operations**. You MUST execute ALL validation gates and get explicit user confirmation before pushing tags. This workflow orchestrates a complete package release from validation to PyPI publication.

**🚨 ABSOLUTELY FORBIDDEN 🚨**

You are **STRICTLY PROHIBITED** from:

❌ **"Skipping validation gates to save time"** - Every gate exists for a reason
❌ **"Pushing tags without CI confirmation"** - Tag push triggers release workflow immediately
❌ **"Assuming tests passed without checking"** - Always verify CI status explicitly
❌ **"Proceeding without user confirmation on IRREVERSIBLE steps"** - Tag push cannot be undone easily
❌ **"Skipping Reflector/Curator after release"** - Release learnings MUST be captured
❌ **"Creating releases without updating CHANGELOG.md"** - Users need to know what changed
❌ **Any variation of "I'll optimize the release process"** - Follow the workflow exactly

**IF YOU VIOLATE THESE RULES:**
- Invalid versions may be published to PyPI (cannot delete, only yank)
- Users will install broken packages
- CI/CD pipeline will fail in production
- Release rollback becomes necessary (manual intervention required)
- Knowledge about release issues won't be captured in playbook/cipher

**YOU MUST:**
✅ Execute ALL 8 phases sequentially
✅ Validate every gate before proceeding
✅ Get explicit user confirmation for IRREVERSIBLE operations
✅ Monitor CI/CD pipeline status in real-time
✅ Run Reflector + Curator to capture release learnings
✅ Verify package availability on PyPI before declaring success

Execute the following release using the MAP (Modular Agentic Planner) framework:

**Release Request:** $ARGUMENTS

## Workflow Overview

This workflow orchestrates a complete package release through 8 sequential phases:

```
Phase 1: Pre-Release Validation (12 gates)
   ↓
Phase 2: Version Determination (user decision)
   ↓
Phase 3: Execute Version Bump Script (updates code + git commit + tag)
   ↓
Phase 4: Push Commit and Tag ⚠️ IRREVERSIBLE - triggers CI/CD
   ↓
Phase 5: GitHub Release and CI/CD Monitoring (watch pipeline)
   ↓
Phase 6: Post-Release Verification (PyPI + installation test)
   ↓
Phase 7: Reflection and Playbook Update (Reflector + Curator)
   ↓
Phase 8: Final Summary and Cleanup
```

**⚠️ IMPORTANT:** After Phase 4 (tag push), the release workflow is triggered automatically. You CANNOT stop the CI/CD pipeline once started. All validation MUST happen before Phase 4.

**🔄 Recitation Plan Integration:**
This workflow creates a recitation plan to track progress and maintain context across phases. If context compaction occurs, recovery files are available in `.map/release_plan.md`.

---

## Phase 1: Pre-Release Validation

**Purpose:** Verify all prerequisites before initiating release. Failure in any gate aborts the workflow.

### 1.1 Load Playbook Context for Release Patterns

Query playbook for release-related patterns and past release issues:

```bash
# Query local playbook for release patterns
PLAYBOOK_BULLETS=$(mapify playbook query "release validation PyPI CI/CD" --limit 10)
```

**Also search Cipher** for cross-project release patterns:

```
mcp__cipher__cipher_memory_search(
  query="package release validation PyPI deployment best practices",
  top_k=5,
  similarity_threshold=0.3
)
```

### 1.2 Create Recitation Plan for Release Tracking

Create release plan to track validation gates and phases:

```bash
# Define release phases as subtasks
RELEASE_PHASES='[
  {"id": 1, "description": "Pre-release validation (12 gates)", "acceptance_criteria": "All gates pass", "estimated_complexity": "medium"},
  {"id": 2, "description": "Version determination", "acceptance_criteria": "User confirms version bump type", "estimated_complexity": "low"},
  {"id": 3, "description": "Execute version bump script", "acceptance_criteria": "Commit and tag created locally", "estimated_complexity": "low"},
  {"id": 4, "description": "Push commit and tag (IRREVERSIBLE)", "acceptance_criteria": "Tag pushed to origin", "estimated_complexity": "low"},
  {"id": 5, "description": "GitHub release and CI/CD monitoring", "acceptance_criteria": "Release created, CI passes", "estimated_complexity": "high"},
  {"id": 6, "description": "Post-release verification", "acceptance_criteria": "Package on PyPI, installs successfully", "estimated_complexity": "medium"},
  {"id": 7, "description": "Reflection and playbook update", "acceptance_criteria": "Learnings captured", "estimated_complexity": "medium"},
  {"id": 8, "description": "Final summary and cleanup", "acceptance_criteria": "Release documented", "estimated_complexity": "low"}
]'

TASK_ID="release_$(date +%s)"

# Create release plan
mapify recitation create "$TASK_ID" "Release MAP Framework: $ARGUMENTS" "$RELEASE_PHASES"

# Mark Phase 1 as in_progress
mapify recitation update 1 in_progress
```

### 1.3 Validation Gates (12 Required)

Execute all validation gates in parallel where possible:

#### Gate 1-4: Code Quality Checks

```bash
# Run in parallel (all must succeed)
pytest tests/ --cov=src/mapify_cli --cov-report=term-missing &
PID_PYTEST=$!

black src/ tests/ --check &
PID_BLACK=$!

ruff check src/ tests/ &
PID_RUFF=$!

mypy src/ &
PID_MYPY=$!

# Wait for all checks
wait $PID_PYTEST && wait $PID_BLACK && wait $PID_RUFF && wait $PID_MYPY
```

**Expected Results:**
- ✅ All tests pass (100% success rate)
- ✅ No black formatting issues
- ✅ No ruff linting errors
- ✅ No mypy type checking errors

**If any check fails:** ABORT release, fix issues first.

#### Gate 5-6: Package Build Validation

```bash
# Build package
python -m build

# Verify package integrity
twine check dist/*
```

**Expected Results:**
- ✅ Package builds without errors
- ✅ `twine check` reports "PASSED" for all distributions

**If build fails:** ABORT release, investigate build errors.

#### Gate 7: Security Audit

```bash
# Check for known vulnerabilities
pip install pip-audit
pip-audit
```

**Expected Results:**
- ✅ No known security vulnerabilities in dependencies

**If vulnerabilities found:** Assess severity, update dependencies if critical.

#### Gate 8-10: Git Repository State

```bash
# Check branch (must be main)
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "❌ ERROR: Not on main branch (current: $CURRENT_BRANCH)"
  exit 1
fi

# Check working directory is clean
if [[ -n "$(git status --porcelain)" ]]; then
  echo "❌ ERROR: Working directory not clean"
  git status
  exit 1
fi

# Pull latest changes
git pull origin main
```

**Expected Results:**
- ✅ On `main` branch
- ✅ Working directory clean (no uncommitted changes)
- ✅ Local branch up-to-date with origin/main

**If not on main or dirty working directory:** ABORT release.

#### Gate 11: CI Status Verification

```bash
# Check latest CI run on main branch
gh run list --branch main --limit 1 --json conclusion,status,headBranch

# View details of latest run
gh run view
```

**Expected Results:**
- ✅ Latest CI run on main branch has conclusion: "success"
- ✅ All jobs passed (build, test, lint)

**If CI failed:** ABORT release, investigate and fix CI failures first.

#### Gate 12: CHANGELOG.md Validation

```bash
# Verify [Unreleased] section exists with content
if ! grep -A 5 "## \[Unreleased\]" CHANGELOG.md | grep -qE "^### (Added|Changed|Fixed|Removed)"; then
  echo "❌ ERROR: CHANGELOG.md [Unreleased] section is empty"
  exit 1
fi
```

**Expected Results:**
- ✅ CHANGELOG.md has [Unreleased] section
- ✅ [Unreleased] section contains changes to release

**If empty:** ABORT release, document changes in CHANGELOG.md first.

### 1.4 Mark Phase 1 Complete

If all 12 gates pass:

```bash
# Mark validation phase complete
mapify recitation update 1 completed

# Get current plan context
PLAN_CONTEXT=$(mapify recitation get-context)
```

**If any gate failed:** Do NOT proceed to Phase 2. Fix issues and re-run Phase 1.

---

## Phase 2: Version Determination

**Purpose:** Determine version bump type based on semantic versioning rules and get user confirmation.

### 2.1 Mark Phase 2 in Progress

```bash
mapify recitation update 2 in_progress
```

### 2.2 Analyze Changes for Semantic Versioning

Read CHANGELOG.md [Unreleased] section to determine bump type:

```bash
# Extract unreleased changes
UNRELEASED_CHANGES=$(awk '/## \[Unreleased\]/,/## \[/' CHANGELOG.md | sed '$d')
```

**Semantic Versioning Rules:**
- **MAJOR (X.0.0)**: Breaking changes, incompatible API/workflow changes
  - Look for: "BREAKING CHANGE", "removed", "incompatible", "migration required"
- **MINOR (x.Y.0)**: New features, backward compatible additions
  - Look for: "Added", "new feature", "enhancement"
- **PATCH (x.y.Z)**: Bug fixes and minor improvements
  - Look for: "Fixed", "bug fix", "patch", "minor improvement"

### 2.3 Get Current Version

```bash
# Get current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.*)"/\1/')

echo "Current version: $CURRENT_VERSION"
```

### 2.4 Ask User for Version Bump Type

Use AskUserQuestion to get user decision on version bump:

```
AskUserQuestion(
  questions: [
    {
      question: "What type of version bump should be performed for this release?",
      header: "Version Bump",
      multiSelect: false,
      options: [
        {
          label: "PATCH (x.y.Z)",
          description: "Bug fixes and minor improvements only. No new features or breaking changes. Example: 1.0.0 → 1.0.1"
        },
        {
          label: "MINOR (x.Y.0)",
          description: "New features, backward compatible additions. No breaking changes. Example: 1.0.0 → 1.1.0"
        },
        {
          label: "MAJOR (X.0.0)",
          description: "Breaking changes, incompatible API/workflow changes. Requires user migration. Example: 1.0.0 → 2.0.0"
        },
        {
          label: "EXPLICIT (X.Y.Z)",
          description: "Specify exact version number manually (e.g., 1.2.3). Use for special cases like pre-releases."
        }
      ]
    }
  ]
)
```

**Store user response:**

```bash
# User selected bump type
BUMP_TYPE="patch"  # or "minor", "major", "explicit"

# If explicit, ask for version
if [[ "$BUMP_TYPE" == "explicit" ]]; then
  # Prompt user for explicit version
  read -p "Enter explicit version (X.Y.Z format): " NEW_VERSION

  # Validate semver format
  if [[ ! "$NEW_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    echo "❌ ERROR: Invalid version format: $NEW_VERSION"
    exit 1
  fi
else
  # Calculate new version based on bump type
  # (bump-version.sh will calculate this)
  NEW_VERSION="calculated by script"
fi
```

### 2.5 Mark Phase 2 Complete

```bash
mapify recitation update 2 completed
```

---

## Phase 3: Execute Version Bump Script

**Purpose:** Use `scripts/bump-version.sh` to update version, CHANGELOG.md, create commit and tag.

### 3.1 Mark Phase 3 in Progress

```bash
mapify recitation update 3 in_progress
```

### 3.2 Review What Will Happen

Display what the script will do:

```bash
echo "════════════════════════════════════════════════════════"
echo "Version Bump Script Will Execute:"
echo "════════════════════════════════════════════════════════"
echo ""
echo "1. Update pyproject.toml: version = \"$NEW_VERSION\""
echo "2. Update CHANGELOG.md: [Unreleased] → [$NEW_VERSION] - $(date +%Y-%m-%d)"
echo "3. Create git commit: chore(release): bump version to $NEW_VERSION"
echo "4. Create git tag: v$NEW_VERSION (annotated, with changelog excerpt)"
echo ""
echo "⚠️  Changes will be committed locally but NOT pushed yet."
echo "    You will review before pushing in Phase 4."
echo ""
```

### 3.3 Execute Version Bump Script

```bash
# Run bump-version.sh script
./scripts/bump-version.sh "$BUMP_TYPE"

# Script creates:
# - Updated pyproject.toml
# - Updated CHANGELOG.md
# - Git commit
# - Annotated git tag vX.Y.Z
```

**The script will:**
1. Validate version format
2. Check for duplicate tags
3. Update `pyproject.toml` version field
4. Update `CHANGELOG.md` ([Unreleased] → [X.Y.Z] with date)
5. Create git commit with message: `chore(release): bump version to X.Y.Z`
6. Create annotated git tag `vX.Y.Z` with changelog excerpt

**Script includes built-in validation gates** (from Gate 1-4 above).

### 3.4 Verify Script Success

```bash
# Verify commit created
LAST_COMMIT=$(git log -1 --oneline)
echo "Last commit: $LAST_COMMIT"

# Verify tag created
LAST_TAG=$(git tag --sort=-version:refname | head -1)
echo "Last tag: $LAST_TAG"

# Verify tag points to latest commit
TAG_COMMIT=$(git rev-list -n 1 "$LAST_TAG")
HEAD_COMMIT=$(git rev-parse HEAD)

if [[ "$TAG_COMMIT" != "$HEAD_COMMIT" ]]; then
  echo "❌ ERROR: Tag does not point to HEAD commit"
  exit 1
fi

# Verify version in pyproject.toml matches tag
PYPROJECT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.*)"/\1/')
TAG_VERSION="${LAST_TAG#v}"  # Remove 'v' prefix

if [[ "$PYPROJECT_VERSION" != "$TAG_VERSION" ]]; then
  echo "❌ ERROR: Version mismatch (pyproject.toml: $PYPROJECT_VERSION, tag: $TAG_VERSION)"
  exit 1
fi

echo "✅ Version bump successful: $PYPROJECT_VERSION"
```

**If verification fails:** Do NOT proceed to Phase 4. Investigate issue.

### 3.5 Show Changes for Review

```bash
# Show commit details
echo ""
echo "════════════════════════════════════════════════════════"
echo "Review Commit and Tag:"
echo "════════════════════════════════════════════════════════"
git show --stat

# Show tag annotation
echo ""
echo "Tag annotation:"
git tag -l -n50 "$LAST_TAG"
```

### 3.6 Mark Phase 3 Complete

```bash
mapify recitation update 3 completed
```

---

## Phase 4: Push Commit and Tag (IRREVERSIBLE)

**⚠️ CRITICAL PHASE:** This phase is IRREVERSIBLE. Once tag is pushed, the release workflow triggers immediately and publishes to PyPI.

### 4.1 Mark Phase 4 in Progress

```bash
mapify recitation update 4 in_progress
```

### 4.2 Pre-Push Safety Verification

Re-verify critical conditions before pushing:

```bash
# 1. Verify on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "❌ ABORT: Not on main branch (current: $CURRENT_BRANCH)"
  exit 1
fi

# 2. Verify CI passed on main (recent run within last 30 minutes)
LATEST_RUN=$(gh run list --branch main --limit 1 --json conclusion,status,createdAt,headBranch --jq '.[0]')
RUN_CONCLUSION=$(echo "$LATEST_RUN" | jq -r '.conclusion')
RUN_STATUS=$(echo "$LATEST_RUN" | jq -r '.status')

if [[ "$RUN_CONCLUSION" != "success" ]]; then
  echo "❌ ABORT: Latest CI run did not succeed (conclusion: $RUN_CONCLUSION)"
  exit 1
fi

# 3. Verify tag doesn't exist on remote
LAST_TAG=$(git tag --sort=-version:refname | head -1)
if git ls-remote --tags origin | grep -q "refs/tags/$LAST_TAG"; then
  echo "❌ ABORT: Tag already exists on remote: $LAST_TAG"
  exit 1
fi

echo "✅ Pre-push safety checks passed"
```

### 4.3 Get Explicit User Confirmation

**MANDATORY:** Ask user to confirm IRREVERSIBLE operation.

Use AskUserQuestion for explicit confirmation:

```
AskUserQuestion(
  questions: [
    {
      question: "⚠️ IRREVERSIBLE OPERATION ⚠️\n\nPushing tag will immediately:\n1. Trigger GitHub Actions release workflow\n2. Build and publish package to PyPI\n3. Create public GitHub release\n\nVersion: $LAST_TAG\nTarget: origin/main\n\nDo you want to proceed with tag push?",
      header: "Confirm Push",
      multiSelect: false,
      options: [
        {
          label: "YES - Push Tag",
          description: "⚠️ IRREVERSIBLE - Proceed with release. Package will be published to PyPI."
        },
        {
          label: "NO - Abort Release",
          description: "Stop release workflow. Tag will remain local only. You can push manually later."
        },
        {
          label: "REVIEW - Show Details",
          description: "Show full commit, tag, and CHANGELOG details before deciding."
        }
      ]
    }
  ]
)
```

**Handle user response:**

```bash
case "$USER_RESPONSE" in
  "YES - Push Tag")
    echo "✅ User confirmed tag push"
    PROCEED_WITH_PUSH=true
    ;;
  "NO - Abort Release")
    echo "⚠️  Release aborted by user"
    echo "Tag remains local: $LAST_TAG"
    echo "To push later: git push origin main && git push origin $LAST_TAG"
    exit 0
    ;;
  "REVIEW - Show Details")
    # Show detailed review
    echo "════════════════════════════════════════════════════════"
    echo "COMMIT DETAILS:"
    echo "════════════════════════════════════════════════════════"
    git show

    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "TAG ANNOTATION:"
    echo "════════════════════════════════════════════════════════"
    git tag -l -n50 "$LAST_TAG"

    echo ""
    echo "════════════════════════════════════════════════════════"
    echo "CHANGELOG EXCERPT:"
    echo "════════════════════════════════════════════════════════"
    awk "/## \[$TAG_VERSION\]/,/## \[/" CHANGELOG.md | sed '$d'

    # Ask again after review
    # (recursive call to AskUserQuestion)
    ;;
esac
```

**If user aborts:** Stop workflow, exit gracefully.

### 4.4 Push Commit to Main

```bash
echo "Pushing commit to origin/main..."
git push origin main

# Verify push succeeded
if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: Failed to push commit to origin/main"
  exit 1
fi

echo "✅ Commit pushed to origin/main"
```

### 4.5 Push Tag (IRREVERSIBLE)

```bash
echo ""
echo "════════════════════════════════════════════════════════"
echo "⚠️  PUSHING TAG (IRREVERSIBLE OPERATION)"
echo "════════════════════════════════════════════════════════"
echo "Tag: $LAST_TAG"
echo "This will trigger release workflow immediately..."
echo ""

# Push tag to origin
git push origin "$LAST_TAG"

# Verify push succeeded
if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: Failed to push tag to origin"
  echo "Rollback: git push --delete origin $LAST_TAG (if partially pushed)"
  exit 1
fi

echo ""
echo "✅ Tag pushed to origin: $LAST_TAG"
echo "✅ Release workflow triggered"
```

### 4.6 Record Push Timestamp

```bash
# Record when tag was pushed (for verification timing)
PUSH_TIMESTAMP=$(date +%s)
echo "Tag pushed at: $(date)"
```

### 4.7 Mark Phase 4 Complete

```bash
mapify recitation update 4 completed
```

---

## Phase 5: GitHub Release and CI/CD Monitoring

**Purpose:** Create GitHub release and monitor CI/CD pipeline until completion.

### 5.1 Mark Phase 5 in Progress

```bash
mapify recitation update 5 in_progress
```

### 5.2 Wait for CI/CD Workflow to Start

```bash
echo "Waiting for release workflow to start..."
sleep 10

# Check for release workflow run
RELEASE_RUN=$(gh run list --workflow=release.yml --limit 1 --json databaseId,status,conclusion,createdAt)
RUN_ID=$(echo "$RELEASE_RUN" | jq -r '.[0].databaseId')

if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  echo "⚠️  WARNING: Release workflow not started yet (may take 30-60 seconds)"
  echo "Retrying in 30 seconds..."
  sleep 30

  RELEASE_RUN=$(gh run list --workflow=release.yml --limit 1 --json databaseId,status,conclusion,createdAt)
  RUN_ID=$(echo "$RELEASE_RUN" | jq -r '.[0].databaseId')
fi

echo "✅ Release workflow started: Run ID $RUN_ID"
```

### 5.3 Monitor CI/CD Pipeline in Real-Time

```bash
echo ""
echo "════════════════════════════════════════════════════════"
echo "Monitoring Release Workflow (this may take 3-5 minutes)"
echo "════════════════════════════════════════════════════════"
echo "Workflow URL: https://github.com/azalio/map-framework/actions/runs/$RUN_ID"
echo ""

# Watch workflow until completion
gh run watch "$RUN_ID"

# Get final status
FINAL_STATUS=$(gh run view "$RUN_ID" --json conclusion --jq '.conclusion')

echo ""
echo "════════════════════════════════════════════════════════"
echo "Workflow Status: $FINAL_STATUS"
echo "════════════════════════════════════════════════════════"
```

### 5.4 Verify Workflow Success

```bash
if [[ "$FINAL_STATUS" != "success" ]]; then
  echo "❌ ERROR: Release workflow failed with status: $FINAL_STATUS"
  echo ""
  echo "View logs: gh run view $RUN_ID --log"
  echo ""
  echo "⚠️  ROLLBACK REQUIRED - See Phase 8 Rollback Procedures"
  exit 1
fi

echo "✅ Release workflow completed successfully"
```

### 5.5 Create GitHub Release

Extract changelog excerpt and create GitHub release:

```bash
# Get version from tag
TAG_VERSION="${LAST_TAG#v}"

# Extract changelog excerpt for this version
CHANGELOG_EXCERPT=$(awk "/## \[$TAG_VERSION\]/,/## \[/" CHANGELOG.md | sed '$d')

# Create GitHub release
echo ""
echo "Creating GitHub release..."
gh release create "$LAST_TAG" \
  --title "MAP Framework $LAST_TAG" \
  --notes "$CHANGELOG_EXCERPT"

if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: Failed to create GitHub release"
  echo "You can create manually: gh release create $LAST_TAG"
else
  echo "✅ GitHub release created: $LAST_TAG"
fi

# Get release URL
RELEASE_URL=$(gh release view "$LAST_TAG" --json url --jq '.url')
echo "Release URL: $RELEASE_URL"
```

### 5.6 Mark Phase 5 Complete

```bash
mapify recitation update 5 completed
```

---

## Phase 6: Post-Release Verification

**Purpose:** Verify package is available on PyPI and can be installed successfully.

### 6.1 Mark Phase 6 in Progress

```bash
mapify recitation update 6 in_progress
```

### 6.2 Wait for PyPI Processing

```bash
echo ""
echo "════════════════════════════════════════════════════════"
echo "Waiting for PyPI to process package (2-5 minutes)..."
echo "════════════════════════════════════════════════════════"

# PyPI OIDC upload is fast, but indexing takes time
sleep 120

echo "Checking PyPI availability..."
```

### 6.3 Verify Package on PyPI

```bash
# Check package page exists
TAG_VERSION="${LAST_TAG#v}"
PYPI_URL="https://pypi.org/project/mapify-cli/$TAG_VERSION/"

echo "Checking PyPI URL: $PYPI_URL"

# Try up to 5 times with exponential backoff
MAX_RETRIES=5
RETRY_COUNT=0
WAIT_TIME=30

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
  if curl -f -s "$PYPI_URL" > /dev/null; then
    echo "✅ Package available on PyPI: $PYPI_URL"
    break
  else
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; then
      echo "⚠️  Package not yet available (attempt $RETRY_COUNT/$MAX_RETRIES)"
      echo "   Waiting ${WAIT_TIME}s before retry..."
      sleep $WAIT_TIME
      WAIT_TIME=$((WAIT_TIME * 2))  # Exponential backoff
    else
      echo "❌ ERROR: Package not available on PyPI after $MAX_RETRIES attempts"
      echo "   Check manually: $PYPI_URL"
      exit 1
    fi
  fi
done
```

### 6.4 Verify Package Metadata

```bash
# Check package versions available
echo ""
echo "Verifying package metadata..."
pip index versions mapify-cli | head -20

# Check if new version is listed
if pip index versions mapify-cli | grep -q "$TAG_VERSION"; then
  echo "✅ Version $TAG_VERSION found in PyPI index"
else
  echo "⚠️  WARNING: Version $TAG_VERSION not yet in pip index (may take additional time)"
fi
```

### 6.5 Installation Test (Clean Environment)

```bash
echo ""
echo "════════════════════════════════════════════════════════"
echo "Testing Installation in Clean Environment"
echo "════════════════════════════════════════════════════════"

# Create temporary virtual environment
python3 -m venv .venv-release-test
source .venv-release-test/bin/activate

# Install from PyPI
pip install --no-cache-dir "mapify-cli==$TAG_VERSION"

if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: Failed to install from PyPI"
  deactivate
  rm -rf .venv-release-test
  exit 1
fi

# Verify CLI works
INSTALLED_VERSION=$(mapify --version)
echo "Installed version: $INSTALLED_VERSION"

# Test basic commands
mapify --help > /dev/null
if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: mapify --help failed"
  deactivate
  rm -rf .venv-release-test
  exit 1
fi

mapify validate --help > /dev/null
if [[ $? -ne 0 ]]; then
  echo "❌ ERROR: mapify validate --help failed"
  deactivate
  rm -rf .venv-release-test
  exit 1
fi

echo "✅ Installation test passed"

# Cleanup
deactivate
rm -rf .venv-release-test
```

### 6.6 Mark Phase 6 Complete

```bash
mapify recitation update 6 completed
```

---

## Phase 7: Reflection and Playbook Update

**Purpose:** Extract learnings from release process and update playbook with patterns.

**⚠️ MANDATORY:** This phase MUST be executed to capture release learnings in playbook and cipher.

### 7.1 Mark Phase 7 in Progress

```bash
mapify recitation update 7 in_progress
```

### 7.2 Collect Release Execution Data

Gather data for Reflector analysis:

```bash
# Get release statistics
RELEASE_DATA=$(cat <<EOF
{
  "version_released": "$TAG_VERSION",
  "bump_type": "$BUMP_TYPE",
  "release_timestamp": "$(date -r $PUSH_TIMESTAMP +%Y-%m-%dT%H:%M:%S%z)",
  "ci_workflow_duration_seconds": $(( $(date +%s) - PUSH_TIMESTAMP - 120 )),
  "validation_gates_passed": 12,
  "validation_gates_failed": 0,
  "rollback_required": false,
  "pypi_availability_delay_seconds": 120,
  "installation_test_passed": true,
  "github_release_url": "$RELEASE_URL",
  "pypi_package_url": "$PYPI_URL"
}
EOF
)

echo "$RELEASE_DATA"
```

### 7.3 Call Reflector to Extract Lessons

**CRITICAL:** Reflector MUST use `cipher_memory_search` before suggesting new patterns.

```
Task(
  subagent_type="reflector",
  description="Extract lessons from release workflow execution",
  prompt="Extract structured lessons from this MAP Framework release:

**Release Data:**
$RELEASE_DATA

**Phases Executed:**
1. Pre-release validation (12 gates)
2. Version determination (user decision: $BUMP_TYPE)
3. Version bump script execution
4. Push commit and tag (IRREVERSIBLE operation)
5. GitHub release and CI/CD monitoring
6. Post-release verification (PyPI + installation)

**Workflow Outcome:** SUCCESS - Package published to PyPI

**MANDATORY FIRST STEP (per agent template):**
Before extracting patterns, you MUST:
1. Call cipher_memory_search(query=\"package release workflow PyPI CI/CD validation\", top_k=5)
2. Check if similar release patterns already exist
3. Only suggest new bullets if pattern is genuinely novel
4. Reference existing cipher patterns in your analysis

**Analyze:**
- Which validation gates were most valuable?
- Did IRREVERSIBLE operation warning prevent mistakes?
- Was PyPI availability timing accurate (2-5 min estimate)?
- Did CI/CD monitoring provide sufficient visibility?
- Were there any manual interventions needed?
- What could be automated further?

**Output JSON with:**
- key_insight: string (one sentence takeaway about release process)
- patterns_used: array of strings (which playbook patterns were helpful)
- patterns_discovered: array of strings (new patterns discovered during release)
- bullet_updates: array of {bullet_id, new_helpful_count, new_harmful_count, reason}
- suggested_new_bullets: array of {section, content, code_example, initial_score}
"
)
```

**Verify Reflector Output:**
- [ ] Did Reflector call `cipher_memory_search`?
- [ ] Did Reflector check for duplicate patterns?
- [ ] Did Reflector provide `suggested_new_bullets`?

**If Reflector didn't use MCP tools:** The agent violated its template instructions. This is a critical failure.

### 7.4 Call Curator to Update Playbook

**CRITICAL:** Curator MUST use `cipher_memory_search` for deduplication and `cipher_extract_and_operate_memory` for high-quality bullets.

```
Task(
  subagent_type="curator",
  description="Update playbook with release learnings",
  prompt="Integrate these release learnings into the playbook:

**Reflector Insights:** [paste reflector JSON output]

**MANDATORY STEPS (per agent template):**
1. BEFORE creating ADD operations: Call cipher_memory_search(query=\"release validation PyPI deployment\", top_k=5) to check for cross-project duplicates
2. Create delta operations (ADD/UPDATE/DEPRECATE) for playbook bullets
3. AFTER applying operations: IF any bullet has helpful_count >= 5, MUST call cipher_extract_and_operate_memory to sync to cross-project knowledge base

**Focus Areas:**
- Release validation gate patterns
- Version bump automation patterns
- CI/CD monitoring best practices
- PyPI publication verification steps
- Rollback procedures (if any issues occurred)

**Output JSON with:**
- operations: array of {operation: 'ADD'|'UPDATE'|'DEPRECATE', section, bullet_id, content, code_example, reason}
- deduplication_check: array of {new_bullet, similar_existing_bullets, action_taken}
- sync_to_cipher: array of {bullet_id, content, helpful_count} (REQUIRED if helpful_count >= 5)
"
)
```

**Verify Curator Output:**
- [ ] Did Curator call `cipher_memory_search` for deduplication?
- [ ] Did Curator provide `operations` array?
- [ ] Did Curator provide `sync_to_cipher` array (if applicable)?

**If Curator didn't use MCP tools:** The agent violated its template instructions.

### 7.5 Apply Curator Operations

```bash
# Save Curator output to file
echo '[Curator JSON output]' > /tmp/curator_release_operations.json

# Apply to playbook SQLite database
mapify playbook apply-delta /tmp/curator_release_operations.json

echo "✅ Playbook updated with release learnings"
```

### 7.6 Sync High-Quality Bullets to Cipher

**MANDATORY:** If Curator output contains `sync_to_cipher` entries, sync them now.

```bash
# Check if sync_to_cipher has entries
SYNC_ENTRIES=$(echo '[Curator JSON output]' | jq -r '.sync_to_cipher | length')

if [[ "$SYNC_ENTRIES" -gt 0 ]]; then
  echo "Syncing $SYNC_ENTRIES high-quality bullets to Cipher..."

  # For each entry in sync_to_cipher
  # (Curator template specifies: helpful_count >= 5 qualifies for sync)

  # Example:
  mcp__cipher__cipher_extract_and_operate_memory(
    interaction: "[bullet content from sync_to_cipher]",
    memoryMetadata: {
      "projectId": "map-framework",
      "source": "curator",
      "domain": "release-engineering"
    }
  )

  echo "✅ High-quality patterns synced to Cipher"
else
  echo "ℹ️  No bullets met threshold for Cipher sync (helpful_count < 5)"
fi
```

### 7.7 Mark Phase 7 Complete

```bash
mapify recitation update 7 completed
```

---

## Phase 8: Final Summary and Cleanup

**Purpose:** Provide comprehensive release summary and clean up temporary files.

### 8.1 Mark Phase 8 in Progress

```bash
mapify recitation update 8 in_progress
```

### 8.2 Generate Release Statistics

```bash
# Get recitation statistics
RECITATION_STATS=$(mapify recitation stats)

echo ""
echo "════════════════════════════════════════════════════════"
echo "RELEASE SUMMARY"
echo "════════════════════════════════════════════════════════"
echo ""
echo "Version Released: $TAG_VERSION"
echo "Bump Type: $BUMP_TYPE"
echo "Release Tag: $LAST_TAG"
echo ""
echo "GitHub Release: $RELEASE_URL"
echo "PyPI Package: $PYPI_URL"
echo ""
echo "CI/CD Workflow: Run ID $RUN_ID"
echo "Workflow Status: $FINAL_STATUS"
echo ""
echo "Installation Test: ✅ PASSED"
echo "Package Available: ✅ YES"
echo ""
echo "════════════════════════════════════════════════════════"
echo "WORKFLOW STATISTICS"
echo "════════════════════════════════════════════════════════"
echo "$RECITATION_STATS"
echo ""
```

### 8.3 Store Release Pattern in Cipher

Store the complete release workflow pattern for future reuse:

```
mcp__cipher__cipher_extract_and_operate_memory(
  interaction: "Successfully executed MAP Framework package release workflow for version $TAG_VERSION.

  Workflow included: 12 validation gates, semantic versioning decision, automated version bump script, IRREVERSIBLE tag push with confirmation, CI/CD monitoring, PyPI verification, installation testing, and knowledge capture via Reflector + Curator.

  Key success factors:
  - All validation gates passed before IRREVERSIBLE operations
  - Explicit user confirmation for tag push prevented mistakes
  - Real-time CI/CD monitoring caught issues early
  - PyPI availability verification with retry logic (2-5 min)
  - Clean environment installation test validated package
  - Reflector + Curator captured learnings for playbook

  Release completed in $(( $(date +%s) - PUSH_TIMESTAMP )) seconds total.",

  memoryMetadata: {
    "projectId": "map-framework",
    "source": "map-release-workflow",
    "domain": "release-engineering"
  }
)
```

### 8.4 List Next Steps for Users

```bash
echo "════════════════════════════════════════════════════════"
echo "NEXT STEPS"
echo "════════════════════════════════════════════════════════"
echo ""
echo "1. Announce release:"
echo "   - Update project README.md if needed"
echo "   - Notify users via GitHub Discussions/Discord/Twitter"
echo "   - Update documentation site (if applicable)"
echo ""
echo "2. Monitor for issues:"
echo "   - Watch GitHub Issues for bug reports"
echo "   - Monitor PyPI download stats"
echo "   - Check for user feedback"
echo ""
echo "3. Plan next release:"
echo "   - Add new features to CHANGELOG.md [Unreleased]"
echo "   - Triage issues for next milestone"
echo ""
```

### 8.5 Clean Up Recitation Plan

```bash
# Clean up release plan
mapify recitation clear

echo "✅ Recitation plan cleared"
```

### 8.6 Mark Phase 8 Complete

```bash
mapify recitation update 8 completed
```

### 8.7 Final Success Message

```bash
echo ""
echo "════════════════════════════════════════════════════════"
echo "✅ RELEASE COMPLETE"
echo "════════════════════════════════════════════════════════"
echo ""
echo "MAP Framework $TAG_VERSION successfully released!"
echo ""
echo "Package: https://pypi.org/project/mapify-cli/$TAG_VERSION/"
echo "Release: $RELEASE_URL"
echo ""
echo "Install: pip install mapify-cli==$TAG_VERSION"
echo ""
```

---

## Rollback Procedures

**Use these procedures if something goes wrong during release.**

### Scenario 1: Pre-Release Validation Failure (Phase 1)

**Symptoms:** One or more validation gates failed.

**Action:**
1. Do NOT proceed with release
2. Fix the failing validation gate
3. Re-run Phase 1 from beginning
4. Only proceed when ALL 12 gates pass

**Example:**
```bash
# If tests fail
pytest tests/ --verbose  # Debug failing test
# Fix issue, commit changes
git add . && git commit -m "fix: resolve test failure for release"
# Re-run Phase 1
```

### Scenario 2: Version Bump Script Failure (Phase 3)

**Symptoms:** `bump-version.sh` exits with error.

**Action:**
1. Review error message from script
2. Common issues:
   - Working directory not clean → Commit or stash changes
   - Invalid version format → Use X.Y.Z format
   - Duplicate tag exists → Delete tag or choose different version
3. Fix issue and re-run script

**Example:**
```bash
# If working directory not clean
git status
git add . && git commit -m "chore: prepare for release"

# Re-run version bump
./scripts/bump-version.sh patch
```

### Scenario 3: Tag Pushed, But CI/CD Failed (Phase 5)

**Symptoms:** Tag pushed to GitHub, but release workflow failed.

**Critical:** Package NOT published to PyPI (CI must succeed for publish).

**Action:**
1. View workflow logs:
   ```bash
   gh run list --workflow=release.yml --limit 1
   gh run view --log
   ```

2. Identify failure cause (common issues):
   - Test failures → Fix tests, will need new patch release
   - Build errors → Fix build config, new patch release
   - PyPI authentication failure → Check OIDC config (see Troubleshooting)

3. Fix issue in new commit:
   ```bash
   # Fix issue
   git add . && git commit -m "fix: resolve release workflow failure"
   git push origin main
   ```

4. Create new patch release:
   ```bash
   # Increment patch version
   ./scripts/bump-version.sh patch
   git push origin main
   git push origin v1.0.2  # New tag
   ```

**Do NOT attempt to:**
- Re-run failed workflow (won't help if code is broken)
- Delete tag and re-push (GitHub caches tags)

### Scenario 4: Package Published to PyPI with Critical Bug

**Symptoms:** Release completed, but package has critical bug discovered immediately.

**Critical:** You CANNOT delete packages from PyPI. Only option is "yank".

**Action Option A: Yank the Release (Recommended)**

1. Go to PyPI web interface:
   - https://pypi.org/manage/project/mapify-cli/release/X.Y.Z/
   - Click "Options" → "Yank release"
   - Provide reason: "Critical bug in [component], use X.Y.Z+1 instead"

2. Effect of yanking:
   - ✅ `pip install mapify-cli` will skip yanked version
   - ✅ `pip install mapify-cli==X.Y.Z` still works (if user needs it)
   - ✅ Package files remain available (no 404 errors)

3. Release patched version immediately:
   ```bash
   # Fix bug
   git add . && git commit -m "fix: critical bug in [component]"

   # Update CHANGELOG.md with fix
   # Add to [Unreleased] section:
   # ### Fixed
   # - Critical bug in [component] (fixes yanked version X.Y.Z)

   # Release patch
   ./scripts/bump-version.sh patch
   git push origin main
   git push origin v1.0.2
   ```

**Action Option B: Leave Package (For Minor Issues)**

If bug is not critical:
1. Add fix to CHANGELOG.md [Unreleased]
2. Include fix in next scheduled release
3. Document workaround in GitHub Issues

### Scenario 5: PyPI Not Available After 5+ Minutes (Phase 6)

**Symptoms:** Package published (CI succeeded), but not showing on PyPI.

**Action:**
1. Verify CI workflow actually published:
   ```bash
   gh run view $RUN_ID --log | grep -A 10 "pypi-publish"
   ```

2. Check for PyPI incident:
   - https://status.python.org/

3. Wait longer (up to 15 minutes):
   ```bash
   # Check every 5 minutes
   while true; do
     curl -f "https://pypi.org/project/mapify-cli/$TAG_VERSION/" && break
     echo "Still waiting..."
     sleep 300
   done
   ```

4. If still not available after 15 minutes:
   - Check PyPI OIDC configuration (see Troubleshooting)
   - Contact PyPI support: https://pypi.org/help/

### Scenario 6: Wrong Version Pushed (User Error)

**Symptoms:** Realized after push that version bump type was incorrect.

**Critical:** Cannot change pushed tag. Must release corrective version.

**Action:**
1. If NOT yet on PyPI (CI still running):
   - Cannot stop CI once tag pushed
   - Let it complete, then yank if needed

2. If already on PyPI:
   - Yank incorrect version (see Scenario 4)
   - Release correct version immediately

**Example:**
```bash
# User pushed v2.0.0 (major) but meant v1.1.0 (minor)

# Option 1: Yank v2.0.0, release v2.0.1 with note
# Option 2: Leave v2.0.0, document as mistake in release notes
```

### Rollback Command Reference

```bash
# Delete local tag (before push)
git tag -d v1.0.1

# Delete remote tag (after push, use with caution)
git push --delete origin v1.0.1
# ⚠️  WARNING: This does NOT stop CI if already triggered

# Yank PyPI release (via web only)
# https://pypi.org/manage/project/mapify-cli/release/1.0.1/

# Undo local version bump commit (before push)
git reset --hard HEAD~1
git tag -d v1.0.1

# View release workflow logs
gh run list --workflow=release.yml --limit 5
gh run view <run-id> --log

# Check package status on PyPI
curl -f https://pypi.org/project/mapify-cli/1.0.1/
pip index versions mapify-cli
```

---

## MCP Tools and Critical Constraints

### MCP Tools Available

Use these MCP tools throughout the workflow:

- **`mcp__cipher__cipher_memory_search`** - Search for release patterns from past projects
- **`mcp__cipher__cipher_extract_and_operate_memory`** - Store release learnings cross-project
- **`mcp__sequential-thinking__sequentialthinking`** - Complex decision making for version bump
- **`AskUserQuestion`** - Get explicit confirmation for IRREVERSIBLE operations

### Critical Constraints

- **NEVER skip validation gates** - All 12 gates must pass before proceeding
- **NEVER push tag without CI confirmation** - Verify CI passed on main before Phase 4
- **NEVER proceed without user confirmation on IRREVERSIBLE operations** - Tag push cannot be easily undone
- **ALWAYS monitor CI/CD pipeline** - Don't assume success, watch in real-time
- **ALWAYS verify PyPI availability** - Don't declare success until package is installable
- **ALWAYS run Reflector + Curator** - Capture learnings after every release
- **ALWAYS update playbook** - Future releases benefit from documented patterns

### Validation Gate Failure Matrix

| Gate # | Gate Name | Failure Impact | Can Proceed? | Fix Action |
|--------|-----------|----------------|--------------|------------|
| 1 | Pytest tests | High | ❌ NO | Fix failing tests |
| 2 | Black format | Medium | ❌ NO | Run black --fix |
| 3 | Ruff lint | Medium | ❌ NO | Fix linting errors |
| 4 | Mypy types | Low | ⚠️ Review | Fix type errors (recommended) |
| 5 | Package build | High | ❌ NO | Fix build config |
| 6 | Twine check | High | ❌ NO | Fix package metadata |
| 7 | Security audit | High | ⚠️ Review | Update vulnerable deps |
| 8 | Git branch | High | ❌ NO | Switch to main |
| 9 | Git clean | High | ❌ NO | Commit/stash changes |
| 10 | Git sync | Medium | ❌ NO | Pull origin/main |
| 11 | CI status | High | ❌ NO | Fix CI failures |
| 12 | CHANGELOG | Medium | ❌ NO | Document changes |

**Legend:**
- ❌ NO = Cannot proceed, must fix
- ⚠️ Review = Can proceed with caution, fix recommended

---

## Example Invocation

User says: `/map-release patch`

You should:

1. **Phase 1 - Pre-Release Validation:**
   ```bash
   mapify playbook query "release validation PyPI" --limit 10
   # Create recitation plan
   mapify recitation create release_1699999999 "Release MAP Framework: patch" '[...]'
   # Run all 12 validation gates
   pytest tests/ && black --check src/ && ruff check src/ && mypy src/ && ...
   # Verify CI passed on main
   gh run list --branch main --limit 1
   ```

2. **Phase 2 - Version Determination:**
   ```bash
   # Get current version
   CURRENT_VERSION=$(grep version pyproject.toml | head -1 | sed -E 's/.*"(.*)".*/\1/')
   # Ask user to confirm bump type (already provided: patch)
   BUMP_TYPE="patch"
   ```

3. **Phase 3 - Execute Version Bump:**
   ```bash
   ./scripts/bump-version.sh patch
   # Verify commit and tag created
   git log -1 --oneline
   git tag --sort=-version:refname | head -1
   ```

4. **Phase 4 - Push Tag (IRREVERSIBLE):**
   ```bash
   # Ask for explicit confirmation
   AskUserQuestion(...)
   # Push commit and tag
   git push origin main
   git push origin v1.0.1
   ```

5. **Phase 5 - Monitor CI/CD:**
   ```bash
   gh run list --workflow=release.yml --limit 1
   gh run watch <run-id>
   # Create GitHub release
   gh release create v1.0.1 --title "MAP Framework v1.0.1" --notes "$(awk ...)"
   ```

6. **Phase 6 - Verify PyPI:**
   ```bash
   sleep 120  # Wait for PyPI processing
   curl -f https://pypi.org/project/mapify-cli/1.0.1/
   # Test installation in clean venv
   python3 -m venv .venv-test && source .venv-test/bin/activate
   pip install mapify-cli==1.0.1
   mapify --version
   deactivate && rm -rf .venv-test
   ```

7. **Phase 7 - Reflection and Playbook:**
   ```bash
   # Call Reflector agent
   Task(subagent_type="reflector", ...)
   # Call Curator agent
   Task(subagent_type="curator", ...)
   # Apply curator operations
   mapify playbook apply-delta curator_operations.json
   # Sync to cipher if needed
   mcp__cipher__cipher_extract_and_operate_memory(...)
   ```

8. **Phase 8 - Summary:**
   ```bash
   mapify recitation stats
   # Display final summary
   echo "✅ RELEASE COMPLETE: MAP Framework v1.0.1"
   # Clean up
   mapify recitation clear
   ```

Begin now with the release request above.
