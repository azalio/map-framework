# Claude Code MCP Configuration

After infrastructure is running and Cipher is configured, integrate Cipher as an MCP server in Claude Code.

## Configuration File

Edit your Claude Code configuration file:

```
~/.claude.json
```

## Add MCP Server

Add this block to the `mcpServers` section of your `~/.claude.json`:

```json
{
  "mcpServers": {
    "cipher": {
      "command": "cipher",
      "args": [
        "--mode", "mcp",
        "--agent", "${HOME}/.cipher/cipher.yml"
      ],
      "env": {
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "VECTOR_STORE_TYPE": "qdrant",
        "VECTOR_STORE_URL": "http://localhost:6333",
        "VECTOR_STORE_HOST": "localhost",
        "VECTOR_STORE_PORT": "6333",
        "VECTOR_STORE_DIMENSION": "1024",
        "MCP_SERVER_MODE": "aggregator",
        "STORAGE_DATABASE_TYPE": "postgresql",
        "CIPHER_PG_URL": "postgresql://cipher:R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG@localhost:5432/cipher",
        "KNOWLEDGE_GRAPH_ENABLED": "true",
        "KNOWLEDGE_GRAPH_TYPE": "neo4j",
        "KNOWLEDGE_GRAPH_HOST": "localhost",
        "KNOWLEDGE_GRAPH_PORT": "7687",
        "KNOWLEDGE_GRAPH_USERNAME": "neo4j",
        "KNOWLEDGE_GRAPH_PASSWORD": "kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+"
      }
    }
  }
}
```

**Important:** Use exact credentials from [01-infrastructure-setup.md](01-infrastructure-setup.md) (.env file).

## Restart Claude Code

Completely restart Claude Code for the configuration to take effect.

## Next Steps

Continue to [05-verification.md](05-verification.md) to verify the setup.
