# Validation Logs Directory

This directory stores validation logs from MAP Framework agent contract validation.

## Log Format

Validation logs are JSON files containing:
- Timestamp
- Agent name
- Validation type (input/output/mcp-tools)
- Validation result (pass/fail)
- Error details (if failed)

## Retention Policy

- Logs are **not committed** to git (see `.gitignore`)
- Old logs can be safely deleted
- Logs are created automatically during workflow execution

## Example Log File

```json
{
  "timestamp": "2025-11-18T21:45:00Z",
  "agent": "actor",
  "validation_type": "input",
  "result": "pass"
}
```

## Manual Cleanup

```bash
# Remove all validation logs
rm -f .map/validation_logs/*.json .map/validation_logs/*.log

# Remove logs older than 7 days
find .map/validation_logs -name "*.json" -mtime +7 -delete
```
