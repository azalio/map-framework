# Troubleshooting

Common issues during Cipher quick start setup and their solutions.

## Categories

- [Docker Infrastructure](#docker-infrastructure)
- [PostgreSQL](#postgresql)
- [Qdrant](#qdrant)
- [Neo4j](#neo4j)
- [Cipher](#cipher)
- [Claude Code MCP](#claude-code-mcp)

---

## Docker Infrastructure

### Containers won't start

```bash
docker compose up -d
# ERROR: ...
```

**Check Docker daemon:**
```bash
docker info
```

If `Cannot connect to the Docker daemon`:
- macOS: Open Docker Desktop
- Linux: `sudo systemctl start docker`

**Check docker-compose.yml syntax:**
```bash
docker compose config
```

**Port conflicts:**
```bash
lsof -i :5432  # PostgreSQL
lsof -i :6333  # Qdrant
lsof -i :7687  # Neo4j
```

If port is occupied:
- Stop conflicting process: `kill -9 <PID>`
- Or change port in docker-compose.yml

### Containers restart immediately

```bash
docker compose ps
# STATE: Restarting
```

**Check logs:**
```bash
docker compose logs postgres
docker compose logs qdrant
docker compose logs neo4j
```

**Memory issues:**
```
FATAL: could not map anonymous shared memory
```

Solution: Docker Desktop → Settings → Resources → Memory → 4GB+

**Volume problems:**
```bash
docker compose down -v
docker compose up -d
```

---

## PostgreSQL

### Connection refused

```
psql: connection to server failed: Connection refused
```

**Check container status:**
```bash
docker compose ps postgres
# Should show: Up, healthy
```

**Check logs:**
```bash
docker compose logs postgres --tail=50
```

**Wait for startup:**
PostgreSQL takes 10-30 seconds to initialize. Check `docker compose ps` until status is `healthy`.

### Authentication failed

```
FATAL: password authentication failed
```

**Verify credentials match .env:**
```bash
docker compose exec postgres env | grep POSTGRES
```

**Recreate with correct credentials:**
```bash
docker compose down -v  # WARNING: deletes data
docker compose up -d
```

### Permission denied

```
ERROR: permission denied for table memories
```

**Grant permissions:**
```bash
docker exec -it cipher-postgres psql -U cipher -d cipher -c "ALTER USER cipher CREATEDB;"
```

---

## Qdrant

### Cannot connect to Qdrant

```
Failed to connect to Qdrant at http://localhost:6333
```

**Check container:**
```bash
docker compose ps qdrant
```

**Check health:**
```bash
curl http://localhost:6333/healthz
# Should return: {"title":"qdrant - vector search engine","version":"..."}
```

**Check logs:**
```bash
docker compose logs qdrant --tail=50
```

### Dimension mismatch

```
ERROR: Dimension mismatch: expected 1024, got 1536
```

**Ensure cipher.yml and Claude Code config match:**
- cipher.yml: `dimensions: 1024`
- ~/.claude.json: `VECTOR_STORE_DIMENSION: "1024"`

**Recreate collection:**
```bash
curl -X DELETE http://localhost:6333/collections/cipher_memory
# Restart Cipher to recreate
```

---

## Neo4j

### Cannot connect to Neo4j

```bash
# Check container
docker compose ps neo4j

# Check logs
docker compose logs neo4j --tail=50
```

**Common issues:**

1. **Container still starting:** Neo4j takes 30-60 seconds. Wait for `healthy` status.

2. **Wrong credentials:** Check .env file matches ~/.claude.json `KNOWLEDGE_GRAPH_PASSWORD`.

3. **Port conflict:**
```bash
lsof -i :7687
lsof -i :7474
```

### Browser connection fails

Open http://localhost:7474

**Login:**
- Username: `neo4j`
- Password: from .env (`NEO4J_PASSWORD`)

If fails, restart container:
```bash
docker compose restart neo4j
```

---

## Cipher

### Cipher command not found

```bash
cipher --version
# command not found
```

**Verify installation:**
```bash
npm list -g @byterover/cipher
```

**Reinstall:**
```bash
npm install -g @byterover/cipher
```

### Environment variables not loaded

```
Error: OLLAMA_BASE_URL is not set
```

**Export variables before running cipher:**
```bash
export OLLAMA_BASE_URL="http://localhost:11434"
# ... other variables from 05-verification.md
```

### YAML syntax error

```
Error parsing cipher.yml: invalid YAML
```

**Validate YAML:**
```bash
cat ~/.cipher/cipher.yml | head -20
```

**Check common issues:**
- Indentation (use spaces, not tabs)
- Quotes around special characters
- Correct multiline syntax for systemPrompt

### Ollama models not found

```
Error: model qwen2.5-coder:7b not found
```

**List models:**
```bash
ollama list
```

**Pull missing models:**
```bash
ollama pull qwen2.5-coder:7b
ollama pull mxbai-embed-large
```

---

## Claude Code MCP

### MCP server fails to load

**Check Claude Code logs:**

macOS/Linux:
```bash
tail -f ~/.config/Claude/logs/mcp*.log
```

**Common issues:**

1. **cipher command not in PATH:**
   - Verify: `which cipher`
   - Ensure global npm bin is in PATH

2. **Wrong cipher.yml path:**
   - Use `${HOME}` in ~/.claude.json, not `~`
   - Example: `${HOME}/.cipher/cipher.yml`

3. **Environment variables missing:**
   - All vars in ~/.claude.json `env` section required
   - Check for typos in variable names

### MCP tools not visible

**Restart Claude Code completely:**
- Quit application
- Wait 5 seconds
- Restart

**Check ~/.claude.json syntax:**
```bash
cat ~/.claude.json | jq .
# Should parse without errors
```

### Connection timeouts

```
MCP server timeout after 30s
```

**Verify infrastructure running:**
```bash
docker compose ps
# All containers should be Up and healthy
```

**Check cipher can connect:**
```bash
cipher --mode mcp --agent ~/.cipher/cipher.yml
# Should show successful connections
```

---

## Diagnostic Script

Quick health check for all components:

```bash
#!/bin/bash
echo "=== Cipher Setup Diagnostic ==="

echo -e "\n1. Docker Containers:"
docker compose ps

echo -e "\n2. Qdrant Health:"
curl -s http://localhost:6333/healthz | jq .

echo -e "\n3. PostgreSQL Connection:"
psql "postgresql://cipher:YOUR_PASSWORD@localhost:5432/cipher" -c "SELECT 1" 2>&1

echo -e "\n4. Neo4j Connection:"
curl -s http://localhost:7474 > /dev/null && echo "Neo4j responding" || echo "Neo4j NOT responding"

echo -e "\n5. Ollama Models:"
ollama list | grep -E 'qwen2.5-coder|mxbai-embed-large'

echo -e "\n6. Cipher Installation:"
cipher --version

echo -e "\n7. Cipher Config:"
test -f ~/.cipher/cipher.yml && echo "Config exists" || echo "Config MISSING"

echo -e "\n=== Diagnostic Complete ==="
```

Save as `check-cipher.sh`, make executable: `chmod +x check-cipher.sh`, run: `./check-cipher.sh`

---

## Getting Help

If issues persist:

1. **Collect diagnostic information:**
   ```bash
   docker compose logs > docker-logs.txt
   cipher --version > cipher-info.txt
   cat ~/.claude.json > claude-config.txt  # Remove passwords before sharing!
   ```

2. **Check documentation:**
   - [Cipher Documentation](https://docs.byterover.dev/cipher/overview)
   - [MAP Framework Repository](https://github.com/azalio/map-framework)

3. **Ask for help:**
   - Create issue in MAP Framework repository
   - Include diagnostic output (remove sensitive data first)
