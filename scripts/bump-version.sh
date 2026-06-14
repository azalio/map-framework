#!/usr/bin/env bash

################################################################################
# bump-version.sh - Automated Version Bumping for MAP Framework
################################################################################
#
# DESCRIPTION:
#   Automates semantic versioning workflow: updates pyproject.toml, updates
#   CHANGELOG.md, creates git commit with conventional commit format, and
#   creates annotated git tag with changelog excerpt.
#
# USAGE:
#   ./scripts/bump-version.sh <major|minor|patch|X.Y.Z>
#
# EXAMPLES:
#   ./scripts/bump-version.sh patch      # 1.0.0 -> 1.0.1
#   ./scripts/bump-version.sh minor      # 1.0.0 -> 1.1.0
#   ./scripts/bump-version.sh major      # 1.0.0 -> 2.0.0
#   ./scripts/bump-version.sh 1.2.3      # explicit version
#
# BEHAVIOR:
#   1. Validates input: major/minor/patch or explicit X.Y.Z semver format
#   2. Checks for duplicate git tags to prevent version collisions
#   3. Updates pyproject.toml version field
#   4. Updates __version__ variable in src/mapify_cli/__init__.py
#   5. Updates CHANGELOG.md with new version section and current date
#   6. Creates git commit with conventional commit message
#   7. Creates annotated git tag with changelog excerpt in tag message
#
# VALIDATION GATES (following impl-0026):
#   - Tag format matches semver (X.Y.Z)
#   - Tag version matches package metadata (pyproject.toml)
#   - No duplicate tags exist
#   - CHANGELOG.md has [Unreleased] section to move
#   - Git working directory is clean
#
# EXIT CODES:
#   0 - Success
#   1 - Invalid arguments or validation failure
#   2 - Git operation failure
#   3 - File operation failure
#
# REQUIREMENTS:
#   - bash 4.0+
#   - git 2.0+
#   - sed (GNU or BSD)
#   - Standard Unix tools (awk, grep, date)
#
# NOTES:
#   - Script must be run from repository root or scripts/ directory
#   - Creates commit and tag but does NOT push (user must push manually)
#   - CHANGELOG.md must have [Unreleased] section to move to new version
#   - If CHANGELOG.md doesn't exist, creates basic structure
#
# AUTHOR:
#   MAP Framework Contributors
#
# VERSION:
#   1.1.1 - Extract tag notes from the versioned changelog section
#
################################################################################

set -euo pipefail

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Repository paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYPROJECT_FILE="${REPO_ROOT}/pyproject.toml"
CHANGELOG_FILE="${REPO_ROOT}/CHANGELOG.md"

# Error handling
error() {
    echo -e "${RED}ERROR: $*${NC}" >&2
}

warn() {
    echo -e "${YELLOW}WARNING: $*${NC}" >&2
}

info() {
    echo -e "${BLUE}INFO: $*${NC}"
}

success() {
    echo -e "${GREEN}SUCCESS: $*${NC}"
}

die() {
    error "$@"
    exit 1
}

# Usage information
usage() {
    cat << EOF
Usage: $(basename "$0") <major|minor|patch|X.Y.Z>

Arguments:
  major         Bump major version (X.0.0)
  minor         Bump minor version (x.Y.0)
  patch         Bump patch version (x.y.Z)
  X.Y.Z         Explicit version (e.g., 1.2.3)

Examples:
  $(basename "$0") patch      # 1.0.0 -> 1.0.1
  $(basename "$0") minor      # 1.0.0 -> 1.1.0
  $(basename "$0") major      # 1.0.0 -> 2.0.0
  $(basename "$0") 1.2.3      # explicit version

Description:
  Automates version bumping by:
  1. Validating version format (semantic versioning)
  2. Checking for duplicate git tags
  3. Updating pyproject.toml version field
  4. Updating __version__ in src/mapify_cli/__init__.py
  5. Updating CHANGELOG.md with new version section
  6. Creating git commit with conventional commit format
  7. Creating annotated git tag with changelog excerpt

Notes:
  - Must be run from repository root or scripts/ directory
  - Git working directory must be clean
  - Creates commit and tag but does NOT push
  - CHANGELOG.md must have [Unreleased] section

EOF
    exit 1
}

# Validate semantic version format
validate_semver() {
    local version="$1"
    # Semver 2.0.0 spec: version numbers MUST NOT contain leading zeroes
    if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
        die "Invalid version format: $version (expected X.Y.Z without leading zeros)"
    fi
}

# Get current version from pyproject.toml
get_current_version() {
    if [[ ! -f "$PYPROJECT_FILE" ]]; then
        die "pyproject.toml not found at: $PYPROJECT_FILE"
    fi

    local version
    version=$(grep -E '^version = ' "$PYPROJECT_FILE" | head -1 | sed -E 's/version = "(.*)"/\1/')

    if [[ -z "$version" ]]; then
        die "Could not extract version from pyproject.toml"
    fi

    echo "$version"
}

# Calculate new version based on bump type
calculate_new_version() {
    local current="$1"
    local bump_type="$2"

    # Parse current version
    IFS='.' read -r major minor patch <<< "$current"

    case "$bump_type" in
        major)
            echo "$((major + 1)).0.0"
            ;;
        minor)
            echo "${major}.$((minor + 1)).0"
            ;;
        patch)
            echo "${major}.${minor}.$((patch + 1))"
            ;;
        *)
            die "Invalid bump type: $bump_type"
            ;;
    esac
}

# Check if git tag already exists
check_tag_exists() {
    local version="$1"
    local tag="v${version}"

    if git rev-parse "$tag" >/dev/null 2>&1; then
        die "Git tag already exists: $tag (version conflict)"
    fi
}

# Check git working directory is clean
check_git_clean() {
    if [[ -n "$(git status --porcelain)" ]]; then
        die "Git working directory is not clean. Commit or stash changes first."
    fi
}

# Update version in pyproject.toml
update_pyproject_version() {
    local new_version="$1"

    info "Updating pyproject.toml: version = \"${new_version}\""

    # Escape version string for sed (defense in depth)
    local escaped_version
    escaped_version=$(printf '%s' "$new_version" | sed 's/[&/\]/\\&/g')

    # Use sed to update version field
    # Works with both GNU sed and BSD sed (macOS)
    if sed --version 2>/dev/null | grep -q GNU; then
        # GNU sed
        sed -i "s/^version = \".*\"/version = \"${escaped_version}\"/" "$PYPROJECT_FILE"
    else
        # BSD sed (macOS)
        sed -i '' "s/^version = \".*\"/version = \"${escaped_version}\"/" "$PYPROJECT_FILE"
    fi

    # Verify update
    local updated_version
    updated_version=$(get_current_version)
    if [[ "$updated_version" != "$new_version" ]]; then
        die "Failed to update pyproject.toml version (expected: $new_version, got: $updated_version)"
    fi

    success "Updated pyproject.toml to version ${new_version}"
}

# Update __version__ in src/mapify_cli/__init__.py
update_init_version() {
    local new_version="$1"
    local init_file="${REPO_ROOT}/src/mapify_cli/__init__.py"

    if [[ ! -f "$init_file" ]]; then
        die "__init__.py not found at: $init_file"
    fi

    info "Updating __init__.py: __version__ = \"${new_version}\""

    # Escape version string for sed (defense in depth)
    local escaped_version
    escaped_version=$(printf '%s' "$new_version" | sed 's/[&/\]/\\&/g')

    # Use sed to update __version__ field
    # Works with both GNU sed and BSD sed (macOS)
    if sed --version 2>/dev/null | grep -q GNU; then
        # GNU sed
        sed -i "s/^__version__ = \".*\"/__version__ = \"${escaped_version}\"/" "$init_file"
    else
        # BSD sed (macOS)
        sed -i '' "s/^__version__ = \".*\"/__version__ = \"${escaped_version}\"/" "$init_file"
    fi

    # Verify update
    local updated_version
    updated_version=$(grep -E '^__version__ = ' "$init_file" | head -1 | sed -E 's/__version__ = "(.*)"/\1/')
    if [[ "$updated_version" != "$new_version" ]]; then
        die "Failed to update __init__.py version (expected: $new_version, got: $updated_version)"
    fi

    success "Updated __init__.py to version ${new_version}"
}

# Create CHANGELOG.md if it doesn't exist
create_changelog_if_missing() {
    if [[ ! -f "$CHANGELOG_FILE" ]]; then
        warn "CHANGELOG.md not found, creating basic structure"

        cat > "$CHANGELOG_FILE" << 'EOF'
# MAP Framework Changelog

All notable changes to the MAP Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial release

EOF
        success "Created CHANGELOG.md"
    fi
}

# Extract changelog excerpt for version
extract_changelog_excerpt() {
    local version="$1"
    local excerpt=""
    local in_section=false
    local line_count=0
    local max_lines=50  # Limit excerpt to 50 lines for tag message
    local escaped_version

    escaped_version=${version//./\\.}

    # Read CHANGELOG.md and extract content between [version] and next ##
    while IFS= read -r line; do
        if [[ "$line" =~ ^\#\#[[:space:]]\[${escaped_version}\]([[:space:]]|$) ]]; then
            in_section=true
            continue
        fi

        if [[ "$in_section" == true ]]; then
            # Stop at next version section
            if [[ "$line" =~ ^\#\#[[:space:]]\[ ]]; then
                break
            fi

            # Add line to excerpt (skip empty header lines)
            if [[ -n "$line" || -n "$excerpt" ]]; then
                excerpt="${excerpt}${line}"$'\n'
                ((line_count++))

                # Limit excerpt length
                if [[ $line_count -ge $max_lines ]]; then
                    excerpt="${excerpt}... (truncated, see CHANGELOG.md for full details)"$'\n'
                    break
                fi
            fi
        fi
    done < "$CHANGELOG_FILE"

    # Trim leading/trailing whitespace
    excerpt=$(echo "$excerpt" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')

    if [[ -z "$excerpt" ]]; then
        warn "No content found in [${version}] section, using default message"
        excerpt="Release version ${version}"
    fi

    echo "$excerpt"
}

# Update CHANGELOG.md with new version
update_changelog() {
    local new_version="$1"
    local current_date
    current_date=$(date +%Y-%m-%d)

    info "Updating CHANGELOG.md: [${new_version}] - ${current_date}"

    # Check if [Unreleased] section exists
    if ! grep -q "## \[Unreleased\]" "$CHANGELOG_FILE"; then
        die "CHANGELOG.md missing [Unreleased] section. Add changes to release before bumping version."
    fi

    # Replace [Unreleased] with [X.Y.Z] - YYYY-MM-DD
    # Then add new [Unreleased] section at the top

    # Create temporary file for sed operations
    local temp_file="${CHANGELOG_FILE}.tmp"

    # Use awk for more complex text replacement (works on both GNU and BSD)
    awk -v version="$new_version" -v date="$current_date" '
    /^## \[Unreleased\]/ {
        # Print new Unreleased section
        print "## [Unreleased]"
        print ""
        # Print version section with current date
        print "## [" version "] - " date
        next
    }
    { print }
    ' "$CHANGELOG_FILE" > "$temp_file"

    # Replace original file
    mv "$temp_file" "$CHANGELOG_FILE"

    success "Updated CHANGELOG.md with version ${new_version}"
}

# Create git commit
create_git_commit() {
    local new_version="$1"
    local init_file="${REPO_ROOT}/src/mapify_cli/__init__.py"

    info "Creating git commit"

    # Stage changes
    git add "$PYPROJECT_FILE" "$CHANGELOG_FILE" "$init_file"

    # Create commit with conventional commit format
    local commit_message="chore(release): bump version to ${new_version}

- Updated pyproject.toml version field
- Updated __init__.py __version__ variable
- Updated CHANGELOG.md with release date
"

    git commit -m "$commit_message"

    success "Created git commit"
}

# Create annotated git tag
create_git_tag() {
    local new_version="$1"
    local tag="v${new_version}"

    info "Creating annotated git tag: ${tag}"

    # Extract changelog excerpt for tag message
    local changelog_excerpt
    changelog_excerpt=$(extract_changelog_excerpt "$new_version")

    # Create tag message
    local tag_message="Release ${new_version}

${changelog_excerpt}
"

    # Create annotated tag
    git tag -a "$tag" -m "$tag_message"

    success "Created git tag: ${tag}"
}

# Main execution
main() {
    # Check arguments
    if [[ $# -ne 1 ]]; then
        usage
    fi

    local input="$1"
    local current_version
    local new_version

    # Change to repository root
    cd "$REPO_ROOT"

    info "Starting version bump process"
    info "Repository: $REPO_ROOT"

    # Validate we're in a git repository
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        die "Not a git repository. Script must run in MAP Framework repo."
    fi

    # Get current version
    current_version=$(get_current_version)
    info "Current version: ${current_version}"

    # Determine new version
    case "$input" in
        major|minor|patch)
            new_version=$(calculate_new_version "$current_version" "$input")
            ;;
        *)
            # Assume explicit version
            new_version="$input"
            validate_semver "$new_version"
            ;;
    esac

    info "New version: ${new_version}"

    # Validation gates (following impl-0026)
    info "Running validation gates..."

    # Gate 1: Validate semver format
    validate_semver "$new_version"
    success "✓ Version format valid (semver)"

    # Gate 2: Check for duplicate tags
    check_tag_exists "$new_version"
    success "✓ No duplicate git tag"

    # Gate 3: Check git working directory is clean
    check_git_clean
    success "✓ Git working directory clean"

    # Gate 4: Ensure CHANGELOG.md exists
    create_changelog_if_missing

    # Gate 5: Verify [Unreleased] section exists
    if ! grep -q "## \[Unreleased\]" "$CHANGELOG_FILE"; then
        die "CHANGELOG.md missing [Unreleased] section"
    fi
    success "✓ CHANGELOG.md has [Unreleased] section"

    # Confirmation prompt
    echo ""
    echo -e "${YELLOW}Ready to bump version:${NC}"
    echo "  Current: ${current_version}"
    echo "  New:     ${new_version}"
    echo ""
    echo -e "${YELLOW}This will:${NC}"
    echo "  1. Update pyproject.toml"
    echo "  2. Update CHANGELOG.md"
    echo "  3. Create git commit"
    echo "  4. Create git tag v${new_version}"
    echo ""
    read -t 30 -p "Continue? [y/N] " -n 1 -r || true
    echo

    if [[ -z "$REPLY" ]]; then
        warn "Version bump cancelled (no response: timed out after 30 seconds)"
        exit 0
    elif [[ ! $REPLY =~ ^[Yy]$ ]]; then
        warn "Version bump cancelled (explicitly declined)"
        exit 0
    fi

    # Execute version bump
    echo ""
    info "Executing version bump..."

    update_pyproject_version "$new_version"
    update_init_version "$new_version"
    update_changelog "$new_version"
    create_git_commit "$new_version"
    create_git_tag "$new_version"

    # Summary
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    success "Version bump complete!"
    echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
    echo ""
    echo "Summary:"
    echo "  Version: ${current_version} → ${new_version}"
    echo "  Commit:  $(git log -1 --oneline)"
    echo "  Tag:     v${new_version}"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Review changes: git show"
    echo "  2. Push commit:    git push origin main"
    echo "  3. Push tag:       git push origin v${new_version}"
    echo ""
}

# Execute main function
main "$@"
