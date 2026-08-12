---
name: Release Checklist
about: Comprehensive checklist for creating a new MAP Framework release
title: 'Release v{{VERSION}}'
labels: ['release', 'process']
assignees: ''
---

# Release Checklist for v{{VERSION}}

**Release Type**: [ ] Major [ ] Minor [ ] Patch

**Target Release Date**: YYYY-MM-DD

**Related Documentation**: [RELEASING.md](../RELEASING.md)

---

## ⚙️ Before Starting

**IMPORTANT**: Replace all `{{VERSION}}` placeholders with the actual version number (e.g., `1.2.3`):
- Use find-and-replace: `{{VERSION}}` → `1.2.3`
- This includes placeholders in:
  - Checklist item text
  - Command examples (bash/sed commands below)
  - URLs and file paths
- Verify replacement: Search for `{{VERSION}}` - should find 0 results
- Total replacements needed: 17 instances

---

## Phase 1: Pre-Release Preparation (~30-45 min)

> **Reference**: [Pre-Release Checklist](../RELEASING.md#pre-release-checklist) in RELEASING.md

### 1.1 Code Quality Checks

- [ ] Run full maintained gate: `make check`
- [ ] ⚠️ All tests pass (100% success rate) - CRITICAL
- [ ] Linters, type checkers, hook linting, and render check pass
- [ ] No linting or type errors
- [ ] Build package locally: `uv run --with build python -m build`
- [ ] Validate package: `uv run --with twine twine check dist/*`
- [ ] Package builds without errors

### 1.2 Documentation Review

- [ ] README.md reflects current features
- [ ] CHANGELOG.md has `[Unreleased]` section with all changes
- [ ] All changes since last release are documented
- [ ] Installation instructions are accurate
- [ ] All documentation links are valid (manual review)
- [ ] API documentation is up to date (if applicable)

### 1.3 Dependency Verification

- [ ] Run security audit: `pip install pip-audit && pip-audit`
- [ ] No known security vulnerabilities
- [ ] All dependencies in `pyproject.toml` are pinned to compatible versions
- [ ] Test installation in clean environment: `uv venv .venv-test && source .venv-test/bin/activate && pip install . && mapify --version`
- [ ] CLI commands work correctly in clean environment
- [ ] Clean up test environment: `deactivate && rm -rf .venv-test`

### 1.4 Git Repository State

- [ ] On `main` branch: `git branch --show-current`
- [ ] Working directory is clean: `git status`
- [ ] Local branch is up to date: `git pull origin main`
- [ ] Check latest CI run: `gh run list --branch main --limit 1`
- [ ] Latest CI run passed all checks: `gh run view`
- [ ] No uncommitted changes

### 1.5 PyPI Configuration

- [ ] PyPI OIDC trusted publisher is configured (see [PyPI Trusted Publishing Setup](../RELEASING.md#pypi-trusted-publishing-setup))
- [ ] `.github/workflows/release.yml` exists and is valid
- [ ] Workflow has `id-token: write` and `contents: read` permissions
- [ ] TestPyPI workflow exists: `.github/workflows/test-pypi.yml`

---

## Phase 2: Version Bumping (~10-15 min)

> **Reference**: [Version Bumping](../RELEASING.md#version-bumping) in RELEASING.md

### 2.1 Determine Version Bump

- [ ] Review changes in CHANGELOG.md `[Unreleased]` section
- [ ] Determine version bump type:
  - **MAJOR** (X.0.0): Breaking changes, incompatible API/workflow changes
  - **MINOR** (x.Y.0): New features, backward compatible additions
  - **PATCH** (x.y.Z): Bug fixes and minor improvements
- [ ] New version number: `________________`

### 2.2 Run Version Bump Script

- [ ] Execute: `./scripts/bump-version.sh <major|minor|patch|X.Y.Z>`
- [ ] Script completes successfully
- [ ] Review commit created by script: `git show`
- [ ] Verify `pyproject.toml` version updated
- [ ] Verify CHANGELOG.md:
  - `[Unreleased]` content moved to new `[X.Y.Z]` section
  - Current date added to new version section
  - New empty `[Unreleased]` section created
- [ ] Verify git tag created: `git tag -l | grep v{{VERSION}}`
- [ ] Tag annotation contains changelog excerpt: `git show v{{VERSION}}`

### 2.3 Push Changes to GitHub

- [ ] Push commit to main: `git push origin main`
- [ ] Wait for CI checks to complete: `gh run watch`
- [ ] ⚠️ CI checks passed on main - CRITICAL (don't push tag if failing)
- [ ] ⚠️ Push tag (triggers release workflow): `git push origin v{{VERSION}}` - IRREVERSIBLE

---

## Phase 3: Create GitHub Release (~5 min)

> **Reference**: [Creating a GitHub Release](../RELEASING.md#creating-a-github-release) in RELEASING.md

### 3.1 Extract Release Notes

- [ ] Extract CHANGELOG excerpt for release notes:
  ```bash
  # BSD/macOS compatible. NB: a two-address awk range (/start/,/end/) collapses
  # to one line here — the version heading matches both patterns; use a flag.
  awk '/^## \[{{VERSION}}\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md
  ```
- [ ] Review release notes content
- [ ] Add any additional context (migration notes, breaking changes, etc.)

### 3.2 Create GitHub Release

- [ ] Create release using GitHub CLI:
  ```bash
  gh release create v{{VERSION}} \
    --title "MAP Framework v{{VERSION}}" \
    --notes "$(awk '/^## \[{{VERSION}}\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md)"
  ```
- [ ] Verify release created: `gh release view v{{VERSION}}`
- [ ] Release appears on GitHub releases page: https://github.com/azalio/map-framework/releases

---

## Phase 4: Verification (~15-20 min)

> **Reference**: [Verification](../RELEASING.md#verification) in RELEASING.md

### 4.1 CI/CD Pipeline Status

- [ ] Check release workflow triggered: `gh run list --workflow=release.yml --limit 1`
- [ ] View workflow run details: `gh run view --log`
- [ ] All workflow steps completed successfully
- [ ] Build step succeeded
- [ ] PyPI publish step succeeded

### 4.2 PyPI Package Verification

- [ ] Wait 2-5 minutes for PyPI to process upload: `sleep 120`
- [ ] Check package page exists: `curl -f https://pypi.org/project/mapify-cli/{{VERSION}}/`
- [ ] Package page loads successfully
- [ ] Check package versions: `pip index versions mapify-cli`
- [ ] ⚠️ New version appears in PyPI index - CRITICAL
- [ ] Package metadata is correct (description, links, classifiers)
- [ ] Download counts are tracking

### 4.3 Installation Test (Clean Environment)

- [ ] Create test virtual environment: `python3 -m venv .venv-release-test`
- [ ] Activate environment: `source .venv-release-test/bin/activate`
- [ ] Install specific version: `pip install mapify-cli=={{VERSION}}`
- [ ] Installation succeeds without errors
- [ ] Verify version: `mapify --version`
- [ ] ⚠️ Version matches expected: `{{VERSION}}` - CRITICAL
- [ ] Test basic CLI functionality: `mapify --help`
- [ ] All commands appear in help output
- [ ] Test core command (if applicable): `mapify [COMMAND]`
- [ ] Deactivate and clean up: `deactivate && rm -rf .venv-release-test`

### 4.4 TestPyPI Verification (Optional for pre-releases)

- [ ] If using TestPyPI workflow, verify test package: `pip install --index-url https://test.pypi.org/simple/ mapify-cli=={{VERSION}}`
- [ ] TestPyPI package works correctly
- [ ] Production PyPI package supersedes TestPyPI

---

## Phase 5: Post-Release Tasks (~15-30 min)

### 5.1 Announcements

- [ ] Update project documentation sites (if applicable)
- [ ] Post release announcement (if applicable):
  - [ ] GitHub Discussions
  - [ ] Project blog/website
  - [ ] Social media channels
  - [ ] Community forums
- [ ] Notify users of breaking changes (if major release)

### 5.2 Monitoring

- [ ] Monitor GitHub Issues for bug reports related to new release
- [ ] Monitor PyPI download statistics
- [ ] Monitor CI/CD workflows for any failures
- [ ] Check for user feedback in community channels

### 5.3 Update Development Environment

- [ ] Update local development environment: `pip install --upgrade mapify-cli`
- [ ] Verify local installation matches release version
- [ ] Update any project-specific tooling or scripts

---

## Phase 6: Rollback (~20-30 min, if needed)

> **Reference**: [Rollback Procedures](../RELEASING.md#rollback-procedures) in RELEASING.md

**🚨 STOP: Only complete this section if a critical issue is discovered and rollback is necessary.**

### 6.1 Assess Rollback Necessity

- [ ] Critical bug identified: **[DESCRIBE BUG]**
- [ ] ⚠️ Severity warrants rollback (security issue, data loss, complete breakage) - NOT for minor bugs
- [ ] Alternative solutions evaluated (hotfix patch release preferred over rollback)
- [ ] Team/maintainers consulted on decision

### 6.2 Execute Rollback (If Required)

**Option A: Yank Release (Recommended for published packages)**

- [ ] ⚠️ Navigate to PyPI: https://pypi.org/manage/project/mapify-cli/release/{{VERSION}}/
- [ ] ⚠️ Click "Options" → "Yank release" - PERMANENT MARKER
- [ ] Provide reason for yanking
- [ ] Update GitHub release to mark as yanked
- [ ] Create hotfix issue to address the problem
- [ ] Plan hotfix release

**Option B: Delete Tag (If not yet published to PyPI)**

- [ ] ⚠️ Delete remote tag: `git push --delete origin v{{VERSION}}` - DESTRUCTIVE
- [ ] Delete local tag: `git tag -d v{{VERSION}}`
- [ ] Delete GitHub release
- [ ] Fix issues in codebase
- [ ] Restart release process

### 6.3 Post-Rollback Communication

- [ ] Announce rollback/yank to users
- [ ] Document issues found
- [ ] Provide workaround or recommended action
- [ ] Set timeline for hotfix release

---

## Release Completion

**Release completed by**: @[GITHUB_USERNAME]
**Release date**: YYYY-MM-DD
**Final status**: [ ] Success [ ] Rolled back [ ] Partial (see notes)

**Post-release notes**:
```
[Add any observations, issues encountered, or improvements for next release]
```

---

## Troubleshooting Reference

For common issues and solutions, see [Troubleshooting](../RELEASING.md#troubleshooting) in RELEASING.md.

**Common Issues**:
- Version mismatch between tag and pyproject.toml
- Git working directory not clean
- CI/CD workflow failures
- PyPI OIDC authentication errors
- Package upload failures

**Debug Checklist** (from RELEASING.md):
- Tag format is `vX.Y.Z`
- Tag version matches `pyproject.toml` version
- Version doesn't already exist on PyPI
- On `main` branch
- Working directory clean
- Tag pushed to origin
- Workflow triggered by tag push
- All CI tests pass
- Trusted publisher configured correctly
- Workflow has `id-token: write` permission
