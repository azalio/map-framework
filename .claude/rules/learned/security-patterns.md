# Security Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Single-Emit-Site Rule for Untrusted External Content: Route Own-Status Through a Separate Return Path** (2026-06-12): When a function wraps external content in an UNTRUSTED block before emitting it to an LLM context, any status or diagnostic message that originates from YOUR OWN code must NOT pass through the same block-emitting path. Mixing own-status into the external-content wrapper path creates two failure modes: (1) if the wrapper is applied uniformly, your own status message carries an UNTRUSTED label — misleading the Agent into treating your diagnostic as potentially hostile; (2) if the wrapper is conditionally skipped for status messages, the skip logic creates a gap that can emit an unfenced block — a security regression. The invariant: keep a SINGLE block-emitting site that accepts only verified-external content and always wraps it; route all own-status (zero-results, error, rate-limit) through a separate noop/reason return path that never emits a block. [workflow: map-efficient]
  ```python
  # WRONG — status string routed through the block emitter; either UNTRUSTED-labelled or unfenced
  ZERO_POSTS_MESSAGE = 'No results found for this query.'

  def emit_results(posts):
      if not posts:
          return {'blocks': [ZERO_POSTS_MESSAGE]}   # unfenced own-status in blocks list!
      return {'blocks': [wrap_untrusted(p) for p in posts]}

  # CORRECT — own-status returned as noop/reason; blocks emitted ONLY for external content
  def emit_results(posts):
      if not posts:
          return {'action': 'noop', 'reason': 'No results found for this query.'}
      return {'blocks': [_render_post_block(p) for p in posts]}

  def _render_post_block(post):
      # The ONLY site that calls wrap_untrusted — all content here is external
      return wrap_untrusted(format_post(post))
  ```

- **Never Auto-Persist a User Secret: Return Credential Placement to the User Explicitly** (2026-06-12): When a user provides an API key or credential file path during a workflow, do NOT automatically write it to shell profiles (`.zshrc`, `.bash_profile`), dotfiles, or copy credential files into the repository tree. The harness deny rules (`Write(**/*credentials*)`) and the auto-mode classifier exist precisely to prevent this. Even if persisting the credential would make the integration "just work", auto-persistence violates the user's security posture and may expose the credential in git history, log files, or shared dotfiles. The correct protocol: detect that a credential is needed, state explicitly what the user must do (e.g. `export SOFA_API_KEY=<value>` in their profile, or place the file at a specific path), and wait for the user to confirm before continuing. Never interpolate a secret value into a file you write. [workflow: map-efficient]
  ```python
  # WRONG — writing the literal API key into a shell profile or config file
  def configure_sofa_key(api_key: str, profile_path: Path) -> None:
      with profile_path.open('a') as f:
          f.write(f'\nexport SOFA_API_KEY={api_key}\n')  # persists secret in dotfile!

  # ALSO WRONG — copying a credentials file into the repo tree
  def install_credentials(src: Path, repo: Path) -> None:
      shutil.copy(src, repo / '.sofa' / 'credentials.json')  # secret in repo!

  # CORRECT — detect need, emit instructions, return control to the user
  def configure_sofa_key_instructions(profile_path: Path) -> str:
      return (
          f"Add the following line to {profile_path} manually, "
          f"then restart your shell:\n"
          f"  export SOFA_API_KEY=<your-key-here>\n"
          f"Do NOT share this value or commit it to the repository."
      )
  ```

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
