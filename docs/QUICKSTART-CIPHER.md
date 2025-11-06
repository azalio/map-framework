# Cipher MCP Quick Start

Краткая инструкция для запуска Cipher MCP с Qdrant + PostgreSQL + Neo4j на основе работающей установки.

> **Для пошаговой документации:** См. [cipher-setup-guide/](cipher-setup-guide/) с отдельными руководствами для каждого шага.

## Prerequisites

```bash
# Docker/Podman
docker --version  # или podman --version

# Ollama с моделями
ollama list  # должны быть qwen2.5-coder:7b и mxbai-embed-large

# Node.js и npm
node --version  # v16+
npm --version
```

## 1. Infrastructure Setup

### Create directory

```bash
mkdir -p ~/cipher-infra
cd ~/cipher-infra
```

### Create .env file

```bash
cat > .env <<'EOF'
POSTGRES_USER=cipher
POSTGRES_PASSWORD=R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG
POSTGRES_DB=cipher

NEO4J_USER=neo4j
NEO4J_PASSWORD=kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+
EOF
```

### Create docker-compose.yml

```bash
cat > docker-compose.yml <<'EOF'
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: cipher-qdrant
    ports:
      - "127.0.0.1:6333:6333"
      - "127.0.0.1:6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 30s
      timeout: 10s
      retries: 3

  postgres:
    image: pgvector/pgvector:pg16
    container_name: cipher-postgres
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-cipher}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB:-cipher}
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cipher"]
      interval: 10s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:latest
    container_name: cipher-neo4j
    ports:
      - "127.0.0.1:7687:7687"
      - "127.0.0.1:7474:7474"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_security_procedures_unrestricted: apoc.*
      NEO4J_dbms_memory_heap_initial__size: 512m
      NEO4J_dbms_memory_heap_max__size: 2g
      NEO4J_server_jvm_additional: "-Xint"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:7474 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 40s

volumes:
  qdrant_storage:
    driver: local
  postgres_data:
    driver: local
  neo4j_data:
    driver: local
  neo4j_logs:
    driver: local

networks:
  default:
    name: cipher-network
EOF
```

### Start infrastructure

```bash
docker compose up -d
# или для podman:
# podman compose up -d
```

## 2. Cipher Configuration

### Install Cipher globally

```bash
npm install -g @byterover/cipher
```

### Create Cipher config

```bash
mkdir -p ~/.cipher

cat > ~/.cipher/cipher.yml <<'EOF'
mcpServers: {}

llm:
  provider: ollama
  model: qwen2.5-coder:7b
  maxIterations: 50
  baseURL: $OLLAMA_BASE_URL

embedding:
  type: ollama
  model: mxbai-embed-large
  baseUrl: $OLLAMA_BASE_URL
  dimensions: 1024

systemPrompt:
  enabled: true
  content: |
    You are Cipher, a knowledge management and reasoning system integrated with MAP Framework.

    Your core capabilities:
    - Knowledge Management: Extract, store, and retrieve semantic knowledge across sessions
    - Reasoning Analysis: Capture and evaluate multi-step thought processes
    - Pattern Recognition: Identify recurring patterns in problem-solving approaches
    - Context Integration: Connect related knowledge from different domains

    MAP Framework Integration:
    - Support ACE (Acquire, Curate, Extract) learning patterns
    - Enable MAP (Modular Agentic Planner) workflow memory persistence
    - Facilitate cross-session knowledge continuity
    - Track reasoning evolution across tasks

    Operating Principles:
    - Semantic search over exact matches (use embeddings effectively)
    - Deduplication before storage (avoid redundant knowledge)
    - Quality scoring for knowledge entries (helpful_count matters)
    - Cross-project knowledge sharing (not project-siloed)

    Knowledge Domains You Handle:
    - Software architecture and design patterns
    - Technical documentation and specifications
    - Problem-solving approaches and trade-offs
    - Testing strategies and verification methods
    - Code quality principles and best practices
    - Security considerations and threat models
    - API design and integration patterns
    - System debugging and troubleshooting

    When Processing Interactions:
    1. Extract actionable knowledge (not conversational fluff)
    2. Identify reasoning patterns (not just conclusions)
    3. Classify domain appropriately (frontend, backend, devops, etc.)
    4. Score confidence accurately (0.0-1.0 scale)
    5. Suggest operation (ADD/UPDATE/DELETE/NONE) based on similarity

    Response Style:
    - Concise and structured (not verbose)
    - Focus on "why" and "when" (not just "what")
    - Include trade-offs and alternatives
    - Cite source when retrieving knowledge
    - Admit uncertainty rather than hallucinate

memoryOptions:
  similarityThreshold: 0.85
  useLLMDecisions: false
  confidenceThreshold: 0.7
  maxSimilarResults: 5
  enableBatchProcessing: true
  enableDeleteOperations: true
EOF
```

## 3. Claude Code MCP Configuration

### Add to ~/.claude.json

Добавьте этот блок в секцию `mcpServers` вашего `~/.claude.json`:

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

### Restart Claude Code

Полностью перезапустите Claude Code для применения конфигурации.

## 4. Verification

### Check infrastructure

```bash
# All containers running
docker ps

# Qdrant health
curl http://localhost:6333/healthz

# PostgreSQL connection
psql "postgresql://cipher:R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG@localhost:5432/cipher" -c "SELECT 1"

# Neo4j Browser (open in browser)
open http://localhost:7474
# Login: neo4j / kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+

# Ollama models
ollama list | grep -E 'qwen2.5-coder|mxbai-embed-large'
```

### Test Cipher standalone

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

### Test in Claude Code

После перезапуска Claude Code должны появиться Cipher MCP tools:

- `cipher_extract_and_operate_memory`
- `cipher_memory_search`
- `cipher_extract_reasoning_steps`
- `cipher_evaluate_reasoning`
- `cipher_store_reasoning_memory`
- `cipher_search_reasoning_patterns`
- `cipher_bash`
