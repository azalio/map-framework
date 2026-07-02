# MAP Framework Release Process

<!-- IMPORTANT: When updating this file, also update .github/ISSUE_TEMPLATE/release-checklist.md -->
<!-- The release checklist template references sections from this document -->

This document describes the complete release process for the MAP Framework, from preparation to verification and troubleshooting.

**Quick Start**: Use the [Release Checklist Template](.github/ISSUE_TEMPLATE/release-checklist.md) to create a trackable GitHub issue for each release.

## Table of Contents

1. [Overview](#overview)
2. [Pre-Release Checklist](#pre-release-checklist)
3. [Version Bumping](#version-bumping)
4. [Creating a GitHub Release](#creating-a-github-release)
5. [Verification](#verification)
6. [Rollback Procedures](#rollback-procedures)
7. [PyPI Trusted Publishing Setup](#pypi-trusted-publishing-setup)
8. [Troubleshooting](#troubleshooting)

## Overview

**Repository**: https://github.com/azalio/map-framework
**PyPI Project**: [mapify-cli](https://pypi.org/project/mapify-cli/)
**Package Manager**: pip/uv
**CI/CD**: GitHub Actions with PyPI OIDC Trusted Publishing

### Release Workflow Summary

```
1. Pre-release checks → 2. Version bump → 3. Push commit & tag → 4. Create GitHub release → 5. CI/CD auto-publishes → 6. Verify on PyPI
```

The release process is **semi-automated**:
- **Manual**: Version bumping, tagging, GitHub release creation
- **Automated**: CI/CD testing, building, and PyPI publishing (triggered by git tag)

### Release Artifacts

- **Source Distribution**: `mapify-cli-X.Y.Z.tar.gz`
- **Wheel**: `mapify_cli-X.Y.Z-py3-none-any.whl`
- **Published to**: PyPI via OIDC trusted publishing (no API tokens needed)

---

## Pre-Release Checklist

Before starting the release process, verify all requirements are met:

### 1. Code Quality Checks

```bash
# Run the maintained CI/CD gate locally
make check

# Verify package builds successfully
uv run --with build python -m build
uv run --with twine twine check dist/*
```

**Expected Results**:
- ✅ All tests pass (100% success rate)
- ✅ No linting errors
- ✅ Type checking passes
- ✅ Rendered templates are up to date
- ✅ Package builds without errors
- ✅ `twine check` reports no issues

### 2. Documentation Review

```bash
# Verify README.md is up to date
cat README.md | grep -i "version"

# Check CHANGELOG.md has [Unreleased] section with changes
grep -A 20 "## \\[Unreleased\\]" CHANGELOG.md

# Verify all doc links are valid (manual review)
grep -r "\\[.*\\](.*\\.md)" docs/ README.md
```

**Requirements**:
- ✅ README.md reflects current features
- ✅ CHANGELOG.md has [Unreleased] section with all changes since last release
- ✅ All documentation links are valid
- ✅ Installation instructions are accurate

### 3. Dependency Verification

```bash
# Check for security vulnerabilities
pip install pip-audit
pip-audit

# Verify dependency versions in pyproject.toml
cat pyproject.toml | grep -A 20 "dependencies"

# Test installation in clean environment
uv venv .venv-test
source .venv-test/bin/activate
pip install .
mapify --version
mapify --help
deactivate
rm -rf .venv-test
```

**Requirements**:
- ✅ No known security vulnerabilities
- ✅ All dependencies are pinned to compatible versions
- ✅ Package installs successfully in clean environment
- ✅ CLI commands work correctly

### 4. Git Repository State

```bash
# Verify on main branch
git branch --show-current
# Expected: main

# Verify working directory is clean
git status
# Expected: "nothing to commit, working tree clean"

# Pull latest changes
git pull origin main

# Verify all CI checks pass on main
gh run list --branch main --limit 1
gh run view  # View latest run details
```

**Requirements**:
- ✅ On `main` branch
- ✅ Working directory is clean (no uncommitted changes)
- ✅ Local branch is up to date with origin/main
- ✅ Latest CI run passed all checks

### 5. PyPI Trusted Publishing Setup

```bash
# Verify OIDC configuration is set up (see section below)
# This only needs to be done once per project

# Check release workflow exists
cat .github/workflows/release.yml
```

**Requirements**:
- ✅ PyPI OIDC trusted publisher configured (see [PyPI Trusted Publishing Setup](#pypi-trusted-publishing-setup))
- ✅ release.yml workflow exists and is valid

---

## Version Bumping

### Semantic Versioning

MAP Framework follows [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR** (X.0.0): Breaking changes, incompatible API/workflow changes
- **MINOR** (x.Y.0): New features, backward compatible additions
- **PATCH** (x.y.Z): Bug fixes and minor improvements

### Version Bump Script

Use the `scripts/bump-version.sh` script to automate version bumping:

```bash
# Syntax
./scripts/bump-version.sh <major|minor|patch|X.Y.Z>

# Examples
./scripts/bump-version.sh patch  # 1.0.0 → 1.0.1 (bug fixes)
./scripts/bump-version.sh minor  # 1.0.0 → 1.1.0 (new features)
./scripts/bump-version.sh major  # 1.0.0 → 2.0.0 (breaking changes)
./scripts/bump-version.sh 1.2.3  # explicit version
```

### What the Script Does

1. **Validates** version format (semantic versioning)
2. **Checks** for duplicate git tags (prevents version collisions)
3. **Updates** `pyproject.toml` version field
4. **Updates** `CHANGELOG.md`:
   - Moves [Unreleased] content to new [X.Y.Z] section
   - Adds current date
   - Creates new empty [Unreleased] section
5. **Creates** git commit with conventional commit format
6. **Creates** annotated git tag `vX.Y.Z` with changelog excerpt

### Push Changes

```bash
# Push commit to main
git push origin main

# Push tag (this triggers release workflow)
git push origin v1.0.1
```

**IMPORTANT**: Pushing the tag triggers the CI/CD release workflow. Make sure:
- ✅ Commit is pushed first (so tag points to correct commit)
- ✅ CI checks passed on main before pushing tag
- ✅ Tag name matches version in pyproject.toml (script ensures this)

---

## Creating a GitHub Release

After pushing the tag, create a GitHub release to make it official and notify users.

### Using GitHub CLI (Recommended)

```bash
# Example: Create release from tag with CHANGELOG excerpt
# Note: Uses awk (BSD/GNU compatible) instead of sed for better portability
gh release create v1.0.1 \
  --title "MAP Framework v1.0.1" \
  --notes "$(awk '/## \[1.0.1\]/,/## \[/' CHANGELOG.md | sed '$d')"

# Alternative: Via file (if command substitution has issues)
awk '/## \[1.0.1\]/,/## \[/' CHANGELOG.md | sed '$d' > /tmp/release-notes.md
gh release create v1.0.1 \
  --title "MAP Framework v1.0.1" \
  --notes-file /tmp/release-notes.md
rm /tmp/release-notes.md
```

---

## Verification

### 1. CI/CD Pipeline Status

```bash
# Check release workflow triggered by tag push
gh run list --workflow=release.yml --limit 1

# View workflow run details
gh run view --log
```

### 2. PyPI Package Verification

```bash
# Wait 2-5 minutes for PyPI to process upload
sleep 120

# Check package page exists
curl -f https://pypi.org/project/mapify-cli/1.0.1/

# Verify package metadata
pip index versions mapify-cli
```

### 3. Installation Test (Clean Environment)

```bash
# Create temporary virtual environment
python3 -m venv .venv-test
source .venv-test/bin/activate
pip install mapify-cli==1.0.1
mapify --version
deactivate
rm -rf .venv-test
```

---

## Rollback Procedures

### Scenario 1: Tag Pushed, But Release Not Created

```bash
# Delete remote tag
git push --delete origin v1.0.1

# Delete local tag
git tag -d v1.0.1
```

### Scenario 2: Package Published to PyPI with Bug

#### Option A: Yank the Release (Recommended)

Go to PyPI web interface:
1. https://pypi.org/manage/project/mapify-cli/release/1.0.1/
2. Click "Options" → "Yank release"
3. Provide reason

**Effect of yanking**:
- ✅ `pip install mapify-cli` will skip v1.0.1
- ✅ `pip install mapify-cli==1.0.1` still works
- ✅ Package files remain available

---

## PyPI Trusted Publishing Setup

**One-time setup** required before first release. Uses OpenID Connect (OIDC) for secure, token-free authentication.

### Setup Steps

#### 1. Configure PyPI Trusted Publisher

1. Log in to PyPI: https://pypi.org/account/login/
2. Navigate to: https://pypi.org/manage/account/publishing/
3. Add a new publisher:
   - **PyPI Project Name**: `mapify-cli`
   - **Owner**: `azalio`
   - **Repository name**: `map-framework`
   - **Workflow name**: `release.yml`
   - **Environment name**: *(leave empty)*
4. Click "Add"

#### 2. Verify Workflow Configuration

Check `.github/workflows/release.yml` has required permissions:

```yaml
permissions:
  id-token: write  # Required for PyPI OIDC authentication
  contents: read   # Required for checkout
```

---

## Troubleshooting

### Common Issues

#### Issue: "Version mismatch between tag and pyproject.toml"

```bash
# Delete incorrect tag
git push --delete origin v1.0.2
git tag -d v1.0.2

# Update pyproject.toml
./scripts/bump-version.sh 1.0.2

# Push correct tag
git push origin main
git push origin v1.0.2
```

#### Issue: "Git working directory is not clean"

```bash
# Check what's changed
git status

# Commit changes
git add .
git commit -m "chore: prepare for release"
```

### Debug Checklist

1. **Version Validation**:
   - [ ] Tag format is `vX.Y.Z`
   - [ ] Tag version matches `pyproject.toml` version
   - [ ] Version doesn't already exist on PyPI

2. **Git State**:
   - [ ] On `main` branch
   - [ ] Working directory clean
   - [ ] Tag pushed to origin

3. **CI/CD**:
   - [ ] Workflow triggered by tag push
   - [ ] All CI tests pass
   - [ ] Build step succeeds

4. **PyPI OIDC**:
   - [ ] Trusted publisher configured correctly
   - [ ] Workflow has `id-token: write` permission

---

## Upgrading existing projects to bundle-first `/map-review`

Projects initialised before the persisted review bundle landed must refresh the
shipped runtime helper and the `map-review` skill so the new flow takes effect.

The recommended path is to re-run the installer:

```bash
mapify init . --force
```

This overwrites only the framework-owned surfaces; user content under `.map/`
(workflow artifacts, run dossiers) is preserved.

If `--force` is undesirable, the minimum manual steps are:

1. Overwrite `.map/scripts/map_step_runner.py` from this repo's
   `src/mapify_cli/templates/map/scripts/map_step_runner.py` to pick up
   `create_review_bundle()` and `prepare_detached_review()`.
2. Overwrite `.claude/skills/map-review/SKILL.md` (and the Codex mirror at
   `.agents/skills/map-review/SKILL.md`, plus its `review-reference.md` and
   `adversarial-reference.md` siblings) so the skill invokes the bundle
   helpers and surfaces the `--detached` flag.
3. Re-run `make render-templates` inside the MAP repo if you maintain a fork —
   the render parity gate is enforced by `make check-render` and
   `pytest tests/test_template_render.py`.

After upgrading, the first `/map-review` invocation will materialise
`.map/<branch>/review-bundle.json` and `.md`; subsequent reviews read the
bundle as their primary context.

---

## Appendix: Release Workflow Reference

### Complete Release Command Sequence

```bash
# 1. Pre-release checks
git checkout main
git pull origin main
git status  # Verify clean
pytest tests/ --cov  # Run tests

# 2. Version bump
./scripts/bump-version.sh patch  # or minor/major

# 3. Review and push
git show  # Review commit
git push origin main
git push origin v1.0.1

# 4. Create GitHub release
gh release create v1.0.1 \
  --title "MAP Framework v1.0.1" \
  --notes "$(awk '/## \[1.0.1\]/,/## \[/' CHANGELOG.md | sed '$d')"

# 5. Monitor CI/CD
gh run watch

# 6. Verify on PyPI
curl -f https://pypi.org/project/mapify-cli/1.0.1/
pip index versions mapify-cli
```
