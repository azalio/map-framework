# Error Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Idempotent File Backups Need Timestamps** (2026-03-26): When creating backup files during upgrade operations, always use a timestamp suffix (not fixed .bak), because repeated upgrades silently overwrite previous backups, destroying the user's customizations permanently. [workflow: map-learn-improvement]
  ```python
  # WRONG: backup = dest.with_suffix(".bak")  # overwritten next run
  # CORRECT:
  ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
  backup = dest.with_suffix(f"{dest.suffix}.{ts}.bak")
  ```

- **Sanitize Control Characters Before External Tools** (2026-03-26, hardened 2026-05-04): When building JSON that will be consumed by `jq`, log aggregators, or APIs via a bash pipeline (``$(...)`` substitution), strip the ENTIRE C0 control range U+0000-U+001F plus U+007F from string values before serialization — including `\t`, `\n`, `\r`. Python `json.dumps` escapes them correctly for strict JSON, but bash command substitution does not preserve byte-perfect roundtrip in all locales: jq then receives raw control bytes and aborts with `Invalid string: control characters from U+0000 through U+001F must be escaped`. Initial 2026-03-26 fix excepted `\n \r \t` and the bug recurred on multi-line artifact bodies. [workflow: behavior-fix]
  ```python
  # WRONG — keeps \n \r \t, jq still breaks via bash pipeline
  return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

  # CORRECT — flatten newlines first, then strip every control char
  text = text.replace("\r\n", "\n").replace("\r", "\n")
  text = text.replace("\n", " ").replace("\t", " ")
  return re.sub(r"[\x00-\x1f\x7f]", "", text)
  ```

- **Pre-existing Surfaced Failures Are Not Out-of-Scope** (2026-05-04): When a quality gate (`make lint`, `make check`, `pytest`, type-check) emits errors during a workflow, Actor must fix EVERY error the gate reports — including ones on pre-existing code outside the current subtask's diff. The gate is failing in the current run; the failure is not historical. Writing "pre-existing failure unrelated to ST-XXX" as a one-line dismissal silently disables the gate and accumulates broken-windows debt. Distinguish from pre-existing DORMANT tech debt (code smell that does not surface in current gate runs), which legitimately stays out of scope. Genuinely-deferrable surfaced failures require explicit user approval, not in-output justification. [workflow: behavior-fix]
  ```
  WRONG (Actor output):
    "Pre-existing lint failure unrelated to ST-001. Skipping."
    → gate still red; Monitor should reject this run.

  CORRECT (Actor output):
    Either: fix the failure as part of the subtask, OR
    Stop and emit CLARIFICATION_NEEDED:
      "make lint reports <error> on <file:line>, predates ST-001.
       Fix here, defer with user approval, or treat as new subtask?"
  ```
