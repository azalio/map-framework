# Infrastructure Setup

Set up Qdrant (vector store), PostgreSQL (relational storage), and Neo4j (knowledge graph) for Cipher MCP.

## Prerequisites Check

```bash
# Docker/Podman
docker --version  # или podman --version

# Ollama с моделями
ollama list  # должны быть qwen2.5-coder:7b и mxbai-embed-large

# Node.js и npm
node --version  # v16+
npm --version
```

## Create Infrastructure Directory

```bash
mkdir -p ~/cipher-infra
cd ~/cipher-infra
```

## Create .env File

```bash
cat > .env <<'EOF'
POSTGRES_USER=cipher
POSTGRES_PASSWORD=R8ozJURa5Ba9NdB5S5R8NzpPEjgC3iyG
POSTGRES_DB=cipher

NEO4J_USER=neo4j
NEO4J_PASSWORD=kqQUsRXiXNI3o0zcsdiCqwZyu1X7zjT+
EOF
```

## Create docker-compose.yml

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

## Start Infrastructure

```bash
docker compose up -d
# или для podman:
# podman compose up -d
```

## Next Steps

Proceed to [02-cipher-installation.md](02-cipher-installation.md) to install Cipher globally.
