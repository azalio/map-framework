# Cipher Setup Guide

Quick start guide for setting up Cipher MCP with Qdrant, PostgreSQL, and Neo4j for MAP Framework.

## Guide Structure

Follow these guides in order:

1. **[Infrastructure Setup](01-infrastructure-setup.md)** (~5 min)
   - Docker Compose setup for Qdrant, PostgreSQL, Neo4j
   - Prerequisites check
   - Service startup

2. **[Cipher Installation](02-cipher-installation.md)** (~2 min)
   - Global npm installation
   - Version verification

3. **[Cipher Configuration](03-cipher-configuration.md)** (~5 min)
   - Create cipher.yml with Ollama integration
   - System prompt for MAP Framework

4. **[Claude Code Setup](04-claude-code-setup.md)** (~3 min)
   - MCP server configuration in ~/.claude.json
   - Environment variables

5. **[Verification](05-verification.md)** (~5 min)
   - Infrastructure health checks
   - Cipher standalone test
   - Claude Code MCP tools verification

6. **[Troubleshooting](06-troubleshooting.md)** (as needed)
   - Common issues and solutions

## Total Time

**~20 minutes** to complete full setup.

## Alternative

For a single-page guide, see [QUICKSTART-CIPHER.md](../QUICKSTART-CIPHER.md).

## Requirements

- Docker or Podman
- Node.js 16+ and npm
- Ollama with `qwen2.5-coder:7b` and `mxbai-embed-large` models
- Claude Code CLI

## Support

Issues? See [06-troubleshooting.md](06-troubleshooting.md) or create an issue in the [MAP Framework repository](https://github.com/azalio/map-framework).
