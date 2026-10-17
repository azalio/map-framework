# Review receipt capability spike

Date: 2026-10-17. Scope: #521 PR 1b. Baseline: c0cd4f0 (#525).
Time budget: approximately 30 minutes. No release or deployment.

## Existing-binding audit

The audit preceded production changes and inspected issue #521 with all comments.

| Existing surface | Verified behavior | Missing contract |
| --- | --- | --- |
| `map_step_runner.py.jinja`, `begin_review_run` | Roster admission, durable round identity, retries and three-round cap | Effective policy and receipt binding |
| `_review_target` | HEAD, resolved base, tracked dirty diff/status and untracked content digest | Explicit reviewed-diff digest and byte-safe manifest coverage |
| `review_round_scope` | Conservative static dependency closure; missing baseline falls back to full review | Current policy and explicit required-scope receipts |
| `capture_review_output` / `_complete_review_round` | Roster/order fencing; target check at initial completion | Capture freshness and completed-verdict consumption freshness |
| `_check_review_ledger_binding` | Computed verdict and convergence gate | Current snapshot/policy/receipt validation |
| `run_test_gate` | Runner-owned subprocess execution | Durable command/output/snapshot receipts |
| Approval holds | Separate persisted decisions | No implicit equivalence to review approval or check success |
| `tests/test_review_verdict_ledger.py` | Restart, cap, retries, dirty/untracked changes, dependency coverage | Receipt completeness and capability regressions |

Source paths are relative to `src/mapify_cli/templates_src/map/scripts/` unless otherwise stated. Extend these APIs and the existing ledger; do not introduce another orchestrator.

## Claude Code: observed host behavior

Installed host: Claude Code 2.1.301. The configured model was reported by the host as `claude-codex/gpt-6.1-sol`; this probe tests host tool exposure, not model identity or quality.

The following command ran from the receipts worktree (prompt shortened only by removing presentation requests):

```sh
claude -p --restricted --strict-mcp-config --permission-mode dontAsk \
  --no-session-persistence \
  --agents '{"receipt-reviewer":{"description":"Read-only receipt reviewer probe","prompt":"Read requested files and report unavailable tools honestly. Never substitute shell or writes.","tools":["Read","Glob","Grep"]}}' \
  --agent receipt-reviewer --verbose --output-format stream-json \
  'Read the first line of Makefile; report whether shell, write or delegation tools are available. Do not modify anything.'
```

Observed facts:

- Host `system/init` event: `tools=["Read","Glob","Grep"]`, `mcp_servers=[]`.
- Actual `Read` invocation returned the first line of the worktree Makefile.
- Shell, mutation and delegation tools were absent from the host inventory. This is stronger evidence than the model's final self-report; no forbidden operation was executed.
- A separate `--tools Read,Glob,Grep` probe successfully read Makefile and found it with Glob.
- The profile probe completed successfully in two turns, with zero subagents spawned.
- This verifies the explicit CLI custom-agent launch boundary, not every parent-session dispatch path.

A subsequent installed-profile discovery probe passed:

```sh
MAP_LIVE_REVIEW_READER=1 .venv/bin/python -m pytest \
  tests/test_review_reader_capabilities.py::test_installed_claude_reader_host_inventory_and_discovery \
  --basetemp=.map/review-reader-live-probe -q
```

Recorded result of the earlier strict discovery probe: `1 passed in 11.86s`. The current test invokes `--agent review-reader` without a `--agents` override, observes the host inventory exactly Read/Glob/Grep, witnesses Read of a fixture marker, and confirms the marker was unchanged. It uses normal discovery with `dontAsk`, without `--restricted` or `--strict-mcp-config`, and does not assert absence of connected MCP servers. This tests installed CLI profile discovery, not parent Task/Agent dispatch. `--restricted` hides project custom agents; no claim is made that restricted mode loads project profiles. Static profile tests are separate from live host evidence.

Follow-up without `--strict-mcp-config`: the host still exposed exactly Read/Glob/Grep, but connected a project MCP server. Thus `mcpServers: []` is **not** proof of no host-level server connection. The capability guarantee is no MCP **tool access** (the actual tool inventory), not network/server isolation. The initial assertion that normal discovery had zero connected servers was incorrect and was corrected; no shell/write/delegation tools appeared. Managed refresh tests also restore altered managed profile restrictions for both providers while preserving user-owned tails.

Diagnostics: the external host warned that its configured auth source overrides Claude.ai connectors and emitted `unrecognized_model` for the configured model. Calls nevertheless completed successfully. No authentication/model configuration or secret values were read or changed.

An earlier attempt to run a Python-driven probe in a temporary directory was refused by worktree isolation before execution. It is not capability evidence; subsequent probes stayed in the current worktree.

## Codex: initial evidence

Installed executable: `codex-cli 0.163.0`; `~/.local/bin/codex` points to `~/.codex/packages/standalone/current/bin/codex`.

Sources:

- [Official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
- [Version-pinned configuration schema](https://raw.githubusercontent.com/openai/codex/rust-v0.163.0/codex-rs/core/config.schema.json).
- Local `codex --version`, `codex --help`, `codex exec --help`.

Confirmed configuration facts, not runtime enforcement proof:

- `features.shell_tool=false` is documented to disable command-execution tools.
- `sandbox_mode="read-only"` constrains shell filesystem effects; it does not remove shell tools.
- Per-agent `agents.<name>.config_file` is supported.
- `agents.enabled=false` alone is insufficient when `features.multi_agent_v2` takes precedence.
- The schema does not expose a general per-agent tool allowlist. This does not prove that native shell-free repository reading is unavailable.

### Bounded spike result

Finished within the approximately 30-minute budget. Stock 0.163.0 source confirms partial restrictions, but the complete capability contract remains **unverified**. No live Codex model probe was run: a supported shell-free read/search route and complete tool boundary were not established.

| Setting / capability | Source inspected | Fact |
| --- | --- | --- |
| `features.shell_tool=false` | [spec_plan.rs:1245–1284](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/tools/spec_plan.rs#L1245-L1284) | `add_shell_tools` returns before native command tool registration. |
| `agents.enabled=false` with `features.multi_agent_v2=false` | [config/mod.rs:1637–1664](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/config/mod.rs#L1637-L1664), [spec_plan.rs:728–741](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/tools/spec_plan.rs#L728-L741) | Explicit Disabled overrides model metadata; V2 must also be disabled. |
| Patch tools | [spec_plan.rs:1432–1435](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/tools/spec_plan.rs#L1432-L1435) | `apply_patch` registration is independent of shell-tool registration and controlled by model capability. Shell-off alone is not no-write enforcement. |
| Host tool policy | [spec_plan.rs:138–149](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/tools/spec_plan.rs#L138-L149) | Runtime ToolPolicy exists, but a supported CLI/per-agent allowlist route was not established. |
| Native text read/search | [handlers/mod.rs:1–37](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/src/tools/handlers/mod.rs#L1-L37) | Core registry has no ordinary `read_file`/`grep_files`/`list_dir` handlers. This does not exclude host extensions. |

Source discovery used the [complete version-pinned release tree](https://api.github.com/repos/openai/codex/git/trees/rust-v0.163.0?recursive=1), reported as non-truncated. No user/global configuration or credentials were inspected or modified.

Decision: use the source-verified shell/delegation disabling settings as defense in depth, supply source evidence through the runner bundle, and retain Codex finding publication. Until installed enforcement is verified, record `capability_enforcement=unverified` with the missing no-write/read-search boundary as its reason; the result is INCOMPLETE and cannot approve. Read-only sandbox is additional protection, not a claim that all write-capable tools are absent.

## Binding strategy

The runner owns execution and supplies a snapshot-bound attribution bundle: diff against base, base versions of affected files, and changed-hunk blame or equivalent line mapping. Reviewers do not need shell for attribution. Existing source lines alone do not prove a defect predates a PR; behavioral context must support that claim, otherwise attribution remains unknown.

If Codex demonstrably enforces the boundary, use the verified capability profile. If enforcement remains unverified at the time limit, keep review and finding publication available, record `capability_enforcement=unverified` with the concrete reason, and derive `INCOMPLETE` rather than COMPLETE/approval. This does not weaken the Claude path. Do not silently restore reviewer shell access. The remaining Codex enforcement work is tracked in [#526](https://github.com/azalio/map-framework/issues/526), created after searching open and closed issues for `Codex reviewer capability enforcement` and `Codex read-only`.
