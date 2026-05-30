# Architecture Patterns (Learned)

<!-- MAP-LEARN: populated by /map-learn. Edit freely, commit with project. -->

- **Contract-First Inter-Component JSON Schemas** (2026-03-26): When two components share a JSON data format (file, IPC, API), always define the schema once as a Python TypedDict or dataclass and import it in both producer and consumer, because organic field names cause silent KeyError failures that only surface in production. [workflow: map-learn-improvement]
  ```python
  from typing import TypedDict

  class StepState(TypedDict):
      current_step_phase: str  # canonical name, one definition
      current_subtask_id: str | None

  # Producer and consumer both import StepState
  ```

- **Monolith Decomposition: Extract Shared Helpers First** (2026-03-26): When decomposing a large Python module into submodules, always identify helpers shared by multiple extraction targets and extract them to a utility module FIRST, because copy-pasting helpers creates DRY violations that diverge silently. Re-export all extracted symbols from the original module to preserve backward compatibility. [workflow: map-learn-improvement]

- **State Machine Transition Completeness: Reset All Sub-State Atomically** (2026-04-11): When implementing a state machine transition function, reset EVERY state variable owned by the departing state in a single atomic operation, not just the primary state indicator. Partial resets leave stale sub-state (e.g., pending_steps, current_step_id, retry_count) that corrupts the entering state's query results. [workflow: map-learn-bugfix]
  ```python
  # WRONG: advance_wave updates only the wave counter
  def advance_wave(self):
      self.current_wave += 1
      # pending_steps / current_step_id still hold prior-wave values!

  # CORRECT: atomically reset all sub-state owned by the wave context
  def advance_wave(self):
      self.current_wave += 1
      self.pending_steps = []
      self.current_step_id = None
      self.completed_steps = []
      self.retry_count = 0
  ```

- **Agentic Prompt Emphasis Uniformity** (2026-04-11): In multi-phase agentic prompts, every non-negotiable phase must carry identical emphasis markers (MANDATORY, CRITICAL). Selective marking — applying markers to some phases but not others — implicitly signals that unmarked phases are optional. Under cost or confidence pressure ("tests already passed"), agents skip unmarked phases. [workflow: map-learn-bugfix]

- **Orchestrator Prompts Must Prohibit Direct State File Modification** (2026-04-11): When an orchestrator manages workflow state through a structured file (e.g., step_state.json), the agent prompt must contain an explicit NEVER-MODIFY rule naming the file. Without this rule, agents that encounter API limitations will write directly to the state file as a fallback, bypassing all validation the API maintains. The rule must specify what to do instead: call a specific API function, or stop and ask the user. [workflow: map-learn-bugfix]

- **Provider Install Scope Isolation: Each Variant Self-Contains Its Resource Decisions** (2026-04-20): When implementing a multi-provider installation dispatch (Strategy pattern), each provider's install() method must be fully self-contained — it installs only the resources it owns and never invokes helpers belonging to sibling providers. Caller-level dispatch code that calls shared helpers before or after branching leaks those helpers into all variants, including variants that must not receive those resources. Place every resource-allocation decision inside install(). [workflow: map-efficient]
  ```python
  # WRONG — caller leaks create_map_tools() into CodexProvider
  def init(project_path, provider='claude'):
      create_map_tools(project_path)  # always runs — overwrites for codex too!
      _get_provider(provider).install(project_path)

  # CORRECT — each provider owns its full installation scope
  class CodexProvider(BaseProvider):
      def install(self, project_path, **kw):
          return create_codex_files(project_path)  # handles .map/scripts/ internally
  ```

- **Single-Source Render Testability Invariant** (2026-05-27, updated 2026-05-31): When a project generates multiple output trees (`.claude/`, `.codex/`, `src/mapify_cli/templates/`, `.agents/skills/`) from a single `.jinja` source tree (`src/mapify_cli/templates_src/`), changes to a `.jinja` source are invisible to all generated consumers until `make render-templates` is run. Document this as a named invariant and enforce it mechanically: always run `make render-templates` before tests (or before commit), and wire `make check-render` into CI to fail on stale generated trees. Without the invariant, developers edit a source file, run tests, see failures, and spend time debugging the generated copies that still hold the old content. [workflow: map-efficient]
  ```bash
  # WRONG — edit .jinja source, run tests, observe mysterious failures:
  vim src/mapify_cli/templates_src/CLAUDE.md.jinja
  pytest tests/test_template_render.py  # generated .claude/CLAUDE.md is still OLD!

  # CORRECT — render first, then test:
  vim src/mapify_cli/templates_src/CLAUDE.md.jinja
  make render-templates                 # propagates .jinja -> all generated trees
  pytest tests/test_template_render.py  # now sees the updated copies

  # CI enforcement (already wired into `make check` via check-render target):
  make check-render   # renders + git diff --exit-code; fails on any stale output
  ```

- **Single-Source Schema Dict with Derived Consumer Lists** (2026-05-27): When multiple consumers (monitor, predictor, evaluator, retry-prompt builder) each need the required fields for a shared agent output format, define ONE module-level dict as the authority and derive ALL per-consumer field lists from it via comprehension. Never let consumers maintain their own hardcoded lists — they drift silently. A field added to the schema for monitor is not added to the retry-prompt builder, so the retry prompt asks for a field the retry validator never checks. The dict also serves as the skeleton source for prompt injection. This is the intra-module application of the existing 'Contract-First Inter-Component JSON Schemas' rule. [workflow: map-efficient]
  ```python
  # WRONG — three consumers, three hardcoded lists that drift:
  MONITOR_REQUIRED = ('severity', 'justification', 'was_present_before_pr')
  PREDICTOR_REQUIRED = ('risk_score', 'landmine_evidence')  # forgot 'confidence'
  RETRY_FIELDS = ['severity', 'justification']              # forgot 'was_present_before_pr'

  # CORRECT — one dict, all consumers derived:
  AGENT_OUTPUT_SCHEMAS: dict[str, dict] = {
      'monitor': {
          'severity': '',
          'justification': '',
          'was_present_before_pr': '',
          'sibling_comparison': '[CONDITIONAL]',  # excluded from required_keys
      },
  }
  _MONITOR_REQUIRED_KEYS = tuple(
      k for k, v in AGENT_OUTPUT_SCHEMAS['monitor'].items()
      if v != '[CONDITIONAL]'
  )  # ('severity', 'justification', 'was_present_before_pr')
  ```

- **Long-Running Operations Need Durable State by Default** (2026-04-28): Any operation lasting longer than a single request-response cycle (>5 s) MUST persist its state to durable storage (DB, queue, KV with persistence) — never to in-process memory or class attributes. Process restart, redeploy, autoscaler eviction, OOM kill, and crash all happen during a 5-minute call in production; in-memory state silently evaporates. The default question for any async API is "what survives `kill -9` mid-call?" not "where is this convenient to put?" — provide a stable resume identifier (e.g., `run_id`) so callers can recover results across the process boundary. [workflow: map-learn-improvement]
  ```python
  # WRONG — state evaporates on restart, results lost mid-call
  class ToolRunner:
      _runs: dict[str, Result] = {}  # in-memory, lost on redeploy

      def run(self, payload):
          run_id = uuid4().hex
          self._runs[run_id] = Result(status="running")
          return run_id

  # CORRECT — state lives outside the process, survives restart
  class ToolRunner:
      def __init__(self, db):
          self.db = db

      def run(self, payload):
          run_id = uuid4().hex
          self.db.insert("runs", run_id=run_id, status="running",
                         started_at=now(), payload=payload)
          return run_id  # caller can poll get_result(run_id) after redeploy

      def get_result(self, run_id):
          return self.db.fetch_one("runs", run_id=run_id)
  ```

- **CLI Gate Reading From stdin Must Distinguish "No Input Piped" From "Invalid Content"** (2026-05-29): When a MANDATORY gate CLI reads its subject from stdin (truncation detector, validator), empty stdin and valid-but-failing content are different failure modes that need different exit behavior. In a Task/Agent flow a bare call with nothing piped means the caller forgot to pipe — a caller error, not a gate verdict. Returning `truncated:true` / nonzero on empty stdin turns every bare invocation into a false-positive hard stop, silently making the gate non-functional (operators learn to ignore the always-red signal). Add a distinct non-blocking `status:"no_input"` (exit 0) for empty stdin; keep the pure function strict (empty→invalid) for programmatic/library callers; and fix the skill docs to actually pipe the captured response. [workflow: map-efficient]
  ```python
  # WRONG — CLI: empty stdin == truncated content == hard stop on every bare call
  text = sys.stdin.read()
  report = detect_truncated(text)          # "" -> {"truncated": True, "reasons": ["empty response"]}
  print(json.dumps(report))

  # CORRECT — CLI distinguishes caller-error from content failure; pure fn stays strict
  text = sys.stdin.read()
  if not text.strip():
      print(json.dumps({"truncated": False, "status": "no_input",
                        "reasons": ["no response on stdin — pipe the captured response"]}))
      sys.exit(0)                          # bare call is non-applicable, not a failure
  report = detect_truncated(text)          # only runs on real content
  print(json.dumps({**report, "status": "ok"}))
  ```

- **Always-Loaded Skill Body Has a Hard Line Budget — Put Detail in the Reference File** (2026-05-29): An always-loaded active skill body (e.g. `SKILL.md`) is guarded by a CI test enforcing a max line count (it loads on every invocation and costs context). Adding even correct, useful prose to it can silently push it over budget and break the test. Architectural rule: the active body holds only a short pointer; detail lives in the bundled reference file (e.g. `efficient-reference.md`), which is not budget-gated. If the budget itself is wrong, change the test and the budget together in a deliberate commit — never grow the active body past it by accident. [workflow: map-efficient]

- **Never Retry a Queued Agent Dispatch on Apparent Non-Response** (2026-05-30): Never retry a queued Agent (Task) dispatch on apparent non-response — "tools temporarily unavailable" or a harness flap is NOT failure. An Agent dispatch is not idempotent: re-sending multiplies running instances rather than retrying a failed one. The calls queue and eventually all execute, producing N parallel agents writing to the same file. In this workflow that launched FOUR `actor` agents simultaneously on one subtask, corrupting the file with duplicate/overlapping edits and a stale unused variable. Correct protocol: dispatch once, wait; if the harness appears unresponsive, inspect the task list before deciding to re-send, and ask the user if in doubt. One agent per file per subtask is an invariant, not a preference. [workflow: map-efficient]
  ```python
  # WRONG — retries on harness flap, queues N actor instances:
  for attempt in range(3):
      response = dispatch_agent(subtask_prompt)
      if not response:
          continue  # flap looks like failure -> 3 queued actors run at once

  # CORRECT — dispatch once; on non-response, inspect state before retrying:
  response = dispatch_agent(subtask_prompt)
  if not response:
      # Do NOT re-send. Check the task list — it may already be queued/running.
      raise PauseAndAsk("Agent dispatch returned no response (harness may be "
                        "flapping). Check TaskList before re-sending.")
  ```

- **N-Output-Tree Parity Requires a Render Gate, Not Manual Copies** (2026-05-30, updated 2026-05-31): When a file must appear identically in N>2 output locations (e.g., `workflow-gate.py` rendered into `.claude/hooks/`, `.codex/hooks/`, `src/mapify_cli/templates/hooks/`, and `src/mapify_cli/templates/codex/hooks/`), manual copy-paste across trees is fragile — any tree drifts silently if the developer edits only the `.jinja` source without re-rendering, or edits a generated output directly. Correct approach: keep ONE `.jinja` source in `templates_src/`, run `make render-templates` to propagate, and enforce parity via `make check-render` (renders + `git diff --exit-code` over all generated trees). Never edit a generated output directly. Generalizes the "Single-Source Render Testability Invariant" to the N-output-tree case. [workflow: map-efficient]
  ```bash
  # Correct edit workflow for the 4-output hook:
  vim src/mapify_cli/templates_src/hooks/workflow-gate.py.jinja  # ONE source of truth
  make render-templates   # propagates to .claude/, .codex/, both templates/ mirrors
  make check-render       # byte-identical gate (already wired into `make check`)
  git add -p              # stage only the intentional delta
  ```
