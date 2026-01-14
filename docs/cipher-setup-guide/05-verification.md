# Verification (DEPRECATED)

> **⚠️ DEPRECATED:** As of v4.0, pattern storage has migrated from Cipher to mem0 MCP. This guide is retained for historical reference only.

Verify all components are working correctly.

## Check Infrastructure

```bash
# All containers running
docker ps

# Qdrant health
curl http://localhost:6333/healthz
open http://localhost:6333/dashboard#/collections

# PostgreSQL connection
psql "postgresql://cipher:R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG@localhost:5432/cipher" -c "SELECT 1"

# Neo4j Browser (open in browser)
open http://localhost:7474
# Login: neo4j / kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+

# Ollama models
ollama list | grep -E 'qwen2.5-coder|mxbai-embed-large'
```

## Test Cipher Standalone

```bash
# Export environment variables
export OLLAMA_BASE_URL="http://localhost:11434"
export VECTOR_STORE_TYPE="qdrant"
export VECTOR_STORE_URL="http://localhost:6333"
export VECTOR_STORE_HOST="localhost"
export VECTOR_STORE_PORT="6333"
export VECTOR_STORE_DIMENSION="1024"
export MCP_SERVER_MODE="aggregator"
export STORAGE_DATABASE_TYPE="postgresql"
export CIPHER_PG_URL="postgresql://cipher:R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG@localhost:5432/cipher"
export KNOWLEDGE_GRAPH_ENABLED="true"
export KNOWLEDGE_GRAPH_TYPE="neo4j"
export KNOWLEDGE_GRAPH_HOST="localhost"
export KNOWLEDGE_GRAPH_PORT="7687"
export KNOWLEDGE_GRAPH_USERNAME="neo4j"
export KNOWLEDGE_GRAPH_PASSWORD="kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+"

# Test Cipher
cipher --mode mcp --agent ~/.cipher/cipher.yml
# Should show:
# - [VectorStore:Qdrant] Successfully connected
# - [KG-Neo4j] Connected successfully
# - [StorageManager:Database] Connected successfully
```

## Test in Claude Code

After restarting Claude Code, the following Cipher MCP tools should be available:

- `cipher_extract_and_operate_memory`
- `cipher_memory_search`
- `cipher_extract_reasoning_steps`
- `cipher_evaluate_reasoning`
- `cipher_store_reasoning_memory`
- `cipher_search_reasoning_patterns`
- `cipher_bash`
- `cipher_add_node`
- `cipher_add_edge`
- `cipher_search_graph`
- `cipher_get_neighbors`
- `cipher_extract_entities`

## Troubleshooting

If any checks fail, see [06-troubleshooting.md](06-troubleshooting.md).
