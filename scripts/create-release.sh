#!/bin/bash

# Create release package for MAP Framework
# This script creates a distributable package with all MAP agents and commands

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}MAP Framework Release Builder${NC}"
echo "================================"

# Get version from pyproject.toml or use default
VERSION=${1:-"1.0.0"}
echo -e "${YELLOW}Building version: ${VERSION}${NC}"

# Create temp directory for packaging
TEMP_DIR=$(mktemp -d)
RELEASE_DIR="$TEMP_DIR/map-framework"

echo "Creating release structure..."

# Create directory structure
mkdir -p "$RELEASE_DIR/.claude/agents"
mkdir -p "$RELEASE_DIR/.claude/commands"
mkdir -p "$RELEASE_DIR/templates"

# Copy agents
echo "Copying MAP agents..."
cp -r .claude/agents/* "$RELEASE_DIR/.claude/agents/" 2>/dev/null || echo "No agents found in .claude/agents/"

# Copy commands (if they exist)
if [ -d ".claude/commands" ]; then
    echo "Copying slash commands..."
    cp -r .claude/commands/* "$RELEASE_DIR/.claude/commands/"
fi

# Copy MCP configuration
if [ -f "mcp_config.json" ]; then
    echo "Copying MCP configuration..."
    cp mcp_config.json "$RELEASE_DIR/.claude/"
fi

# Copy documentation
if [ -f "README.md" ]; then
    cp README.md "$RELEASE_DIR/"
fi

# Create template structure for different AI assistants
ASSISTANTS=("claude")

for AI in "${ASSISTANTS[@]}"; do
    echo -e "${YELLOW}Creating package for: $AI${NC}"

    # Create AI-specific package
    AI_DIR="$TEMP_DIR/map-kit-template-$AI"
    cp -r "$RELEASE_DIR" "$AI_DIR"

    # Create version info
    echo "{
  \"version\": \"$VERSION\",
  \"ai_assistant\": \"$AI\",
  \"framework\": \"MAP Framework\",
  \"created\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
}" > "$AI_DIR/map-kit-info.json"

    # Create ZIP file
    OUTPUT_FILE="dist/map-kit-template-$AI.zip"
    mkdir -p dist

    (cd "$TEMP_DIR" && zip -qr - "map-kit-template-$AI") > "$OUTPUT_FILE"
    echo -e "${GREEN}✓${NC} Created: $OUTPUT_FILE ($(du -h "$OUTPUT_FILE" | cut -f1))"
done

# Clean up
rm -rf "$TEMP_DIR"

echo ""
echo -e "${GREEN}Release packages created successfully!${NC}"
echo "Files are in the 'dist/' directory"
echo ""
echo "To create a GitHub release:"
echo "1. git tag v$VERSION"
echo "2. git push origin v$VERSION"
echo "3. Create release on GitHub and upload the ZIP files from dist/"