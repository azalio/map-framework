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

- **Dual-Copy Template-Sync Testability Invariant** (2026-05-27): When a project ships a template copy of runtime code (e.g., `src/mapify_cli/templates/map/scripts/`) that is ALSO the copy imported by pytest, code changes in the dev copy (`.map/scripts/`) are invisible to the test suite until an explicit sync command (`make sync-templates`) is run. Document this as a named invariant and enforce it mechanically: run sync before tests, or add a CI step that diffs the two copies and fails on divergence. Without the documented invariant, developers iterate on the dev copy, run tests, see failures, and spend time debugging the wrong copy. [workflow: map-efficient]
  ```bash
  # WRONG — edit dev copy, run tests, observe mysterious failures:
  vim .map/scripts/map_step_runner.py
  pytest tests/test_map_step_runner.py  # imports from templates/ — sees OLD code!

  # CORRECT — sync first, then test:
  vim .map/scripts/map_step_runner.py
  make sync-templates                   # mirrors dev -> templates/
  pytest tests/test_map_step_runner.py  # now sees the updated copy

  # CI enforcement: add diff gate to Makefile check target:
  # diff -q .map/scripts/map_step_runner.py \
  #   src/mapify_cli/templates/map/scripts/map_step_runner.py
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
