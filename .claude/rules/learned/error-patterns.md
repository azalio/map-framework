# Error Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Idempotent File Backups Need Timestamps** (2026-03-26): When creating backup files during upgrade operations, always use a timestamp suffix (not fixed .bak), because repeated upgrades silently overwrite previous backups, destroying the user's customizations permanently. [workflow: map-learn-improvement]
  ```python
  # WRONG: backup = dest.with_suffix(".bak")  # overwritten next run
  # CORRECT:
  ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
  backup = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
  ```

- **Sanitize Control Characters Before External Tools** (2026-03-26): When building JSON that will be consumed by jq, log aggregators, or APIs, always strip ASCII control characters (U+0000-U+001F except \n \r \t) from string values before serialization, because Python json.dumps escapes them correctly but bash variable expansion and external parsers can corrupt them. [workflow: map-learn-improvement]
