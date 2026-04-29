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
