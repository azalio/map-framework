# /map-release Supporting Reference

This file holds full phase scripts, rollback procedures, examples, and troubleshooting for `/map-release` so the invoked `SKILL.md` stays focused on the active release flow.

## Phase 1: Pre-Release Validation

### Gate 1–4: Code Quality Checks

```bash
# Run the maintained project gate (all checks must succeed)
make check
```

**Expected Results:**
- ✅ All tests pass (100% success rate)
- ✅ `ruff`, `mypy`, `pyright`, and hook linting pass
- ✅ Rendered templates match `templates_src`

**If any check fails:** ABORT release, fix issues first.

### Gate 5–6: Package Build Validation

```bash
# Build package
uv run --with build python -m build

# Verify package integrity
uv run --with twine twine check dist/*
```

**Expected Results:**
- ✅ Package builds without errors
- ✅ `twine check` reports "PASSED" for all distributions

### Gate 7: Security Audit

```bash
pip install pip-audit
pip-audit
```

**Expected Results:**
- ✅ No known security vulnerabilities in dependencies

**If vulnerabilities found:** Assess severity; update dependencies if critical.

### Gate 8–10: Git Repository State

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

### Gate 11: CI Status Verification

```bash
gh run list --branch main --limit 1 --json conclusion,status,headBranch
gh run view
```

**Expected Results:**
- ✅ Latest CI run on main branch has `conclusion: "success"`
- ✅ All jobs passed (build, test, lint)

**If CI failed:** ABORT release, investigate and fix CI failures first.

### Gate 12: CHANGELOG.md Completeness Validation

```bash
# Step 1: Check [Unreleased] section exists
if ! grep -q "## \[Unreleased\]" CHANGELOG.md; then
  echo "❌ ERROR: CHANGELOG.md missing [Unreleased] section"
  exit 1
fi

# Step 2: Check [Unreleased] has content
if ! grep -A 5 "## \[Unreleased\]" CHANGELOG.md | grep -qE "^### (Added|Changed|Fixed|Removed)"; then
  echo "❌ ERROR: CHANGELOG.md [Unreleased] section is empty"
  exit 1
fi

# Step 3: Completeness check — compare commits vs CHANGELOG entries
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

if [[ -n "$LAST_TAG" ]]; then
  echo "Checking CHANGELOG completeness since $LAST_TAG..."

  # Get user-visible commits since last tag. Exclude merge commits plus release-note
  # maintenance commits, which otherwise make this heuristic chase its own fixes.
  COMMITS_SINCE=$(git log ${LAST_TAG}..HEAD --no-merges --format="%s" | awk '!/^(docs\(changelog\)|chore\(release\):)/ { count++ } END { print count + 0 }')

  # Count CHANGELOG entries in [Unreleased] section.
  # NOTE: a range-pattern awk (/start/,/end/) collapses to the single
  # matching line when start and end match the SAME line — and "##
  # [Unreleased]" matches both "/## \[Unreleased\]/" and "/## \[/". Use an
  # explicit flag instead so the range spans past the heading line itself.
  CHANGELOG_ENTRIES=$(awk '/^## \[Unreleased\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md | grep -cE "^- " || echo "0")

  echo "Counted commits since $LAST_TAG: $COMMITS_SINCE"
  echo "(excluding docs(changelog) and chore(release) maintenance commits)"
  echo "CHANGELOG entries: $CHANGELOG_ENTRIES"

  # If significant gap, show commits for review
  if [[ $COMMITS_SINCE -gt $(($CHANGELOG_ENTRIES + 2)) ]]; then
    echo ""
    echo "⚠️  WARNING: CHANGELOG may be incomplete"
    echo "════════════════════════════════════════════════════════"
    echo "Commits since $LAST_TAG:"
    echo "════════════════════════════════════════════════════════"
    git log ${LAST_TAG}..HEAD --oneline --no-merges
    echo "════════════════════════════════════════════════════════"
    echo ""
    echo "Current CHANGELOG [Unreleased] content:"
    awk '/^## \[Unreleased\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md
    echo ""

    # Ask user to update CHANGELOG
    read -p "CHANGELOG appears incomplete. Update it now? (y/n): " UPDATE_CHANGELOG

    if [[ "$UPDATE_CHANGELOG" == "y" ]]; then
      echo ""
      echo "Suggested CHANGELOG entries (review and add manually):"
      echo "────────────────────────────────────────────────────────"
      git log ${LAST_TAG}..HEAD --no-merges --format="%s (%h)" | while read -r commit_msg; do
        if [[ "$commit_msg" =~ ^feat ]]; then
          echo "### Changed"
          echo "- ${commit_msg#feat*: }"
        elif [[ "$commit_msg" =~ ^fix ]]; then
          echo "### Fixed"
          echo "- ${commit_msg#fix*: }"
        elif [[ "$commit_msg" =~ ^docs ]]; then
          echo "### Documentation"
          echo "- ${commit_msg#docs*: }"
        else
          echo "### Changed"
          echo "- $commit_msg"
        fi
      done
      echo "────────────────────────────────────────────────────────"
      echo ""
      echo "Please update CHANGELOG.md manually, then re-run the release."
      exit 1
    else
      read -p "Continue with potentially incomplete CHANGELOG? (y/N): " PROCEED_ANYWAY
      [[ "$PROCEED_ANYWAY" != "y" ]] && exit 1
    fi
  fi
else
  echo "ℹ️  No previous tag found, skipping completeness check"
fi
```

## Phase 2: Version Determination

```bash
# Get current version from pyproject.toml
CURRENT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.*)"/\1/')
echo "Current version: $CURRENT_VERSION"

# Read CHANGELOG unreleased section
UNRELEASED_CHANGES=$(awk '/^## \[Unreleased\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md)
```

**Semantic Versioning Rules:**
- **MAJOR (X.0.0):** Breaking changes, incompatible API/workflow changes
- **MINOR (x.Y.0):** New features, backward-compatible additions
- **PATCH (x.y.Z):** Bug fixes and minor improvements

Use `AskUserQuestion` with these options:

```
AskUserQuestion(
  questions=[
    {
      question: "What type of version bump should be performed for this release?",
      header: "Version Bump",
      multiSelect: false,
      options: [
        {label: "PATCH (x.y.Z)", description: "Bug fixes and minor improvements only."},
        {label: "MINOR (x.Y.0)", description: "New features, backward compatible additions."},
        {label: "MAJOR (X.0.0)", description: "Breaking changes, incompatible API/workflow changes."},
        {label: "EXPLICIT (X.Y.Z)", description: "Specify exact version number manually."}
      ]
    }
  ]
)
```

If explicit version requested, validate `^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`.

## Phase 3: Execute Version Bump Script

### 3.1 Show What Will Happen

```bash
echo "Version Bump Script Will Execute:"
echo "1. Update pyproject.toml: version = \"$NEW_VERSION\""
echo "2. Update CHANGELOG.md: [Unreleased] → [$NEW_VERSION] - $(date +%Y-%m-%d)"
echo "3. Create git commit: chore(release): bump version to $NEW_VERSION"
echo "4. Create git tag: v$NEW_VERSION (annotated, with changelog excerpt)"
echo "Changes will be committed locally but NOT pushed yet."
```

### 3.2 Execute

```bash
./scripts/bump-version.sh --yes "$BUMP_TYPE"
```

### 3.3 Verify

```bash
LAST_TAG=$(git tag --sort=-version:refname | head -1)
TAG_VERSION="${LAST_TAG#v}"

# Verify tag points to HEAD
TAG_COMMIT=$(git rev-list -n 1 "$LAST_TAG")
HEAD_COMMIT=$(git rev-parse HEAD)
[[ "$TAG_COMMIT" != "$HEAD_COMMIT" ]] && echo "❌ ERROR: Tag does not point to HEAD" && exit 1

# Verify pyproject.toml matches tag
PYPROJECT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/version = "(.*)"/\1/')
[[ "$PYPROJECT_VERSION" != "$TAG_VERSION" ]] && echo "❌ ERROR: Version mismatch" && exit 1

# 🚨 CRITICAL: Verify __version__ in __init__.py (bump-version.sh known bug)
INIT_VERSION=$(grep -E '^__version__ = ' src/mapify_cli/__init__.py | head -1 | sed -E 's/__version__ = "(.*)"/\1/')
if [[ "$INIT_VERSION" != "$TAG_VERSION" ]]; then
  echo "❌ CRITICAL ERROR: __version__ mismatch!"
  echo "   pyproject.toml: $PYPROJECT_VERSION"
  echo "   __init__.py:    $INIT_VERSION"
  echo "   tag:            $TAG_VERSION"
  echo ""
  echo "ACTION REQUIRED:"
  echo "1. sed -i '' 's/__version__ = \".*\"/__version__ = \"$TAG_VERSION\"/' src/mapify_cli/__init__.py"
  echo "2. git add src/mapify_cli/__init__.py && git commit --amend --no-edit"
  echo "3. git tag -f $LAST_TAG"
  echo "4. Re-run verification"
  exit 1
fi

echo "✅ Version bump successful: $PYPROJECT_VERSION"
echo "✅ All version fields match (pyproject.toml, __init__.py, git tag)"
```

### 3.4 Show Changes for Review

```bash
git show --stat
git tag -l -n50 "$LAST_TAG"
```

## Phase 4: Push Commit and Tag (IRREVERSIBLE)

### 4.1 Pre-Push Safety Verification

```bash
CURRENT_BRANCH=$(git branch --show-current)
[[ "$CURRENT_BRANCH" != "main" ]] && echo "❌ ABORT: Not on main branch" && exit 1

LATEST_RUN=$(gh run list --branch main --limit 1 --json conclusion,status,createdAt,headBranch --jq '.[0]')
RUN_CONCLUSION=$(printf '%s' "$LATEST_RUN" | jq -r '.conclusion')
[[ "$RUN_CONCLUSION" != "success" ]] && echo "❌ ABORT: Latest CI did not succeed" && exit 1

LAST_TAG=$(git tag --sort=-version:refname | head -1)
git ls-remote --tags origin | grep -q "refs/tags/$LAST_TAG" && echo "❌ ABORT: Tag already on remote" && exit 1

echo "✅ Pre-push safety checks passed"
```

### 4.2 User Confirmation

```
AskUserQuestion(
  questions=[
    {
      question: "⚠️ IRREVERSIBLE OPERATION ⚠️\n\nPushing tag will immediately:\n1. Trigger GitHub Actions release workflow\n2. Build and publish package to PyPI\n3. Create public GitHub release\n\nVersion: $LAST_TAG\nTarget: origin/main\n\nDo you want to proceed?",
      header: "Confirm Push",
      multiSelect: false,
      options: [
        {label: "YES - Push Tag", description: "⚠️ IRREVERSIBLE - Proceed with release."},
        {label: "NO - Abort Release", description: "Stop. Tag remains local only."},
        {label: "REVIEW - Show Details", description: "Show full commit, tag, and CHANGELOG before deciding."}
      ]
    }
  ]
)
```

If `REVIEW`: show `git show`, `git tag -l -n50 "$LAST_TAG"`, and CHANGELOG excerpt, then ask again.

### 4.3 Push

```bash
git push origin main
git push origin "$LAST_TAG"
PUSH_TIMESTAMP=$(date +%s)
echo "✅ Tag pushed: $LAST_TAG"
echo "✅ Release workflow triggered"
```

## Phase 5: CI/CD Monitoring

```bash
echo "Waiting for release workflow to start..."
sleep 10

RELEASE_RUN=$(gh run list --workflow=release.yml --limit 1 --json databaseId,status,conclusion,createdAt)
RUN_ID=$(printf '%s' "$RELEASE_RUN" | jq -r '.[0].databaseId')

if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
  echo "⚠️  Workflow not started yet; retrying in 30s..."
  sleep 30
  RELEASE_RUN=$(gh run list --workflow=release.yml --limit 1 --json databaseId,status,conclusion,createdAt)
  RUN_ID=$(printf '%s' "$RELEASE_RUN" | jq -r '.[0].databaseId')
fi

echo "Workflow URL: https://github.com/azalio/map-framework/actions/runs/$RUN_ID"
gh run watch "$RUN_ID"

FINAL_STATUS=$(gh run view "$RUN_ID" --json conclusion --jq '.conclusion')
[[ "$FINAL_STATUS" != "success" ]] && echo "❌ Release workflow failed. See rollback procedures." && exit 1
echo "✅ Release workflow completed successfully"
```

## Phase 6: Post-Release Verification

```bash
sleep 120
TAG_VERSION="${LAST_TAG#v}"
PYPI_URL="https://pypi.org/project/mapify-cli/$TAG_VERSION/"

# The retry MUST wrap the install itself, not a cheap HTML probe. The
# human-facing project page (pypi.org/project/...) and the PEP 503 simple
# index pip resolves against sit behind independent CDN caches: the page can
# return 200 while `pip install` still reports "no matching distribution"
# (observed on v3.28.0 — the index lagged the page by ~60-90 s). A successful
# install is the only check equivalent to "a user can install this now".
MAX_RETRIES=5; RETRY_COUNT=0; WAIT_TIME=45; INSTALL_OK=0
while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
  rm -rf .venv-release-test
  python3 -m venv .venv-release-test
  if .venv-release-test/bin/pip install -q --no-cache-dir "mapify-cli==$TAG_VERSION"; then
    INSTALL_OK=1
    break
  fi
  RETRY_COUNT=$((RETRY_COUNT + 1))
  [[ $RETRY_COUNT -lt $MAX_RETRIES ]] \
    && echo "⚠️  Not resolvable yet (attempt $RETRY_COUNT/$MAX_RETRIES); waiting ${WAIT_TIME}s..." \
    && sleep $WAIT_TIME
done

if [[ $INSTALL_OK -ne 1 ]]; then
  echo "❌ mapify-cli==$TAG_VERSION not installable after $MAX_RETRIES attempts"
  echo "   Project page: $PYPI_URL"
  echo "   Index probe:  curl -s https://pypi.org/simple/mapify-cli/ | grep mapify_cli-$TAG_VERSION"
  rm -rf .venv-release-test
  exit 1
fi

echo "✅ Package installable: $PYPI_URL"
.venv-release-test/bin/mapify --version
.venv-release-test/bin/mapify --help > /dev/null && echo "✅ --help OK"
.venv-release-test/bin/mapify validate --help > /dev/null && echo "✅ validate --help OK"
rm -rf .venv-release-test
echo "✅ Installation test passed"
```

## Rollback Procedures

### Scenario 1: Pre-Release Validation Failure (Phase 1)

Fix the failing gate, commit changes, then re-run Phase 1 from the beginning. Only proceed when all 12 gates pass.

### Scenario 2: Version Bump Script Failure (Phase 3)

Common issues:
- Working directory not clean → commit or stash changes
- Invalid version format → use X.Y.Z
- Duplicate tag exists → delete tag or choose different version

```bash
# Example: clean up and retry
git status
git add . && git commit -m "chore: prepare for release"
./scripts/bump-version.sh --yes patch
```

### Scenario 3: Tag Pushed, But CI/CD Failed (Phase 5)

Package NOT published to PyPI (CI must succeed for publish).

```bash
gh run list --workflow=release.yml --limit 1
gh run view --log

# Fix issue in new commit, then create a new patch release
git add . && git commit -m "fix: resolve release workflow failure"
git push origin main
./scripts/bump-version.sh --yes patch
git push origin main
git push origin v1.0.2
```

**Do NOT:** re-run failed workflow, or delete tag and re-push.

### Scenario 4: Package Published to PyPI with Critical Bug

You CANNOT delete packages from PyPI. Only option is yank.

**Option A: Yank (Recommended)**
1. Go to https://pypi.org/manage/project/mapify-cli/release/X.Y.Z/
2. Click "Options" → "Yank release", provide reason
3. Release patched version immediately

**Effect of yanking:** `pip install mapify-cli` skips yanked version; explicit `==X.Y.Z` still works.

**Option B: Leave (For Minor Issues)** — add fix to next scheduled release, document workaround.

### Scenario 5: PyPI Not Available After 5+ Minutes

```bash
gh run view $RUN_ID --log | grep -A 10 "pypi-publish"
# Check https://status.python.org/
# Wait up to 15 minutes, probing the simple index pip resolves against —
# NOT the project page, which goes live earlier (see Phase 6):
while true; do
  curl -s "https://pypi.org/simple/mapify-cli/" | grep -q "mapify_cli-$TAG_VERSION" && break
  echo "Still waiting for the simple index..."; sleep 300
done
```

### Scenario 6: Wrong Version Pushed

Cannot change pushed tag. Let CI complete, then yank if needed, release correct version.

### Rollback Command Reference

```bash
git tag -d v1.0.1                           # Delete local tag (before push)
git push --delete origin v1.0.1             # Delete remote tag (does NOT stop CI)
# Yank PyPI: https://pypi.org/manage/project/mapify-cli/release/1.0.1/
git reset --hard HEAD~1 && git tag -d v1.0.1  # Undo local bump (before push)
gh run list --workflow=release.yml --limit 5
gh run view <run-id> --log
```

## MCP Tools

- **`mcp__sequential-thinking__sequentialthinking`** — complex decision making for version bump
- **`AskUserQuestion`** (built-in) — explicit confirmation for IRREVERSIBLE operations

## Examples

```
/map-release                            # full release workflow; bump type chosen at confirmation gate
/map-release patch                      # hint to version-determination phase
```

## Troubleshooting

- **`make check` (Gate 1) fails.** Stop — fix every lint/type/test failure before any tag or publish step; the release gates are hard stops, not warnings.
- **`__version__` is out of sync after `bump-version.sh`.** Apply the documented `__version__` sync workaround in Phase 3 before continuing: manually edit `__init__.py`, amend the commit, re-tag.
- **A tag or PyPI publish step failed midway.** Follow the rollback scenario for that phase; never re-run an irreversible step blindly.
- **CI shows stale run.** Ensure the run being checked is on `main` and was triggered AFTER the last commit; use `--limit 1` and inspect `headBranch` + `createdAt`.
