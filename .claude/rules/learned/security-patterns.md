# Security Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Security Gate Check Ordering: Blocklist Before Allowlist** (2026-04-20): In security enforcement hooks that combine an allowlist (safe command prefixes) and a blocklist (harmful patterns such as redirects, destructive subcommands), always evaluate the blocklist FIRST, before any allowlist prefix check. Allowlist-first creates a structural bypass: a command that starts with an allowed prefix (e.g., 'git ') is approved before harmful sub-patterns ('>>' redirect, 'git restore', 'sed -i') are ever evaluated. The allowlist should only be consulted after confirming no modifying pattern matched. [workflow: map-efficient]
  ```python
  # WRONG — allowlist-first: 'git restore foo' starts with 'git ', returns False
  def command_modifies_files(command: str) -> bool:
      for prefix in ALWAYS_ALLOWED_PREFIXES:
          if command.startswith(prefix):
              return False  # exits before modifying-pattern scan!
      for pattern in FILE_MODIFYING_PATTERNS:
          if re.search(pattern, command):
              return True
      return False

  # CORRECT — blocklist-first: no bypass possible regardless of prefix
  def command_modifies_files(command: str) -> bool:
      for pattern in FILE_MODIFYING_PATTERNS:
          if re.search(pattern, command):
              return True
      for prefix in ALWAYS_ALLOWED_PREFIXES:
          if command.startswith(prefix):
              return False
      return False
  ```
