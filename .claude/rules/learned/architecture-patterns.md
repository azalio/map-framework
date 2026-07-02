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

- **Install-Time Marker Double-Application: Source Artifacts Must Not Pre-Contain Installer Output** (2026-05-31): When an install step is responsible for injecting a structural marker (e.g. `map:start`/`map:end` fences, a generated header, a version stamp) into a file at install time, the source artifact the installer consumes must NOT already contain that marker. If the marker is pre-baked into the source (injected into a `.jinja` template or a `templates_src` file) AND the installer also wraps the content, every installed file ends up with TWO marker pairs; a parser expecting exactly one pair sees malformed/duplicate structure, fails, and falls back to a safe-but-wrong default (e.g. treating the whole file as user-owned and silently skipping the managed refresh). Invariant: a transformation that is the installer's responsibility has exactly one application site — the installer. Keep source + generated trees marker-free; the installer adds the marker once at write time. Generalises to any idempotency concern where a transform has two application sites. [workflow: map-efficient]
  ```python
  # WRONG: fence baked into template AND added by copier -> double fence -> parse fallback
  # CORRECT: templates_src is fence-free; copier injects exactly once:
  wrapped = f"# map:start\n{rendered}\n# map:end\n" if fenced else rendered
  ```

- **Dotted-YAML-Key to Snake-Case Dataclass Dead-Toggle: Always Alias Before Field Mapping** (2026-06-12): When a YAML config file uses dotted hierarchical notation for a key (e.g. `sofa.enabled: true`) but the consuming Python dataclass uses flat snake_case (`sofa_enabled`), the field is a silent dead toggle unless the loader inserts an explicit key alias BEFORE the generic field-mapping loop. The loader sees `data['sofa.enabled']` and finds no dataclass field named `sofa.enabled`, so it silently skips the value; the field stays at its default (False) regardless of what the YAML says. This is distinct from type-coercion validation and from inter-component JSON contracts — it is specifically the YAML→dataclass key-name translation boundary where dotted notation does not automatically become underscore notation. [workflow: map-efficient]
  ```python
  # WRONG — loader maps field names by exact dict key; 'sofa.enabled' never matches 'sofa_enabled'
  def load_map_config(path: Path) -> MapConfig:
      data = yaml.safe_load(path.read_text()) or {}
      return MapConfig(**{k: v for k, v in data.items() if k in MapConfig.__dataclass_fields__})
      # sofa_enabled stays False even when YAML says 'sofa.enabled: true'

  # CORRECT — alias the dotted key to snake_case BEFORE the generic mapping loop
  def load_map_config(path: Path) -> MapConfig:
      data = yaml.safe_load(path.read_text()) or {}
      # Alias dotted YAML keys to their dataclass field names
      if 'sofa.enabled' in data:
          data['sofa_enabled'] = data.pop('sofa.enabled')
      return MapConfig(**{k: v for k, v in data.items() if k in MapConfig.__dataclass_fields__})
  ```

- **OR-not-AND Idempotent Presence Check: Use Disjunction to Prevent Duplicate Injection** (2026-06-12): When deciding whether to append a line to a config file (gitignore, requirements.txt, any append-once config), the guard condition must be OR (marker-present OR line-already-present), never AND (marker-present AND line-already-present). AND requires BOTH conditions to suppress the append; if the user already has the line without your marker, AND evaluates False and appends a duplicate. OR suppresses the append whenever EITHER condition holds, making the operation truly idempotent regardless of how the user got the line there. This is a subtle correctness inversion: AND feels "precise" but is the wrong operator for a "do not add if already present" guarantee. [workflow: map-efficient]
  ```python
  # WRONG — AND guard: if user has '.sofa/' line but not our marker, appends a duplicate
  def ensure_sofa_ignored(gitignore: Path) -> None:
      text = gitignore.read_text() if gitignore.exists() else ''
      marker_present = '# map:sofa' in text
      line_present = '.sofa/' in text
      if marker_present and line_present:   # AND: both must be true to skip
          return
      gitignore.write_text(text + '\n# map:sofa\n.sofa/\n')
      # If user already has '.sofa/' without the marker -> appends DUPLICATE

  # CORRECT — OR guard: skip if EITHER condition holds
  def ensure_sofa_ignored(gitignore: Path) -> None:
      text = gitignore.read_text() if gitignore.exists() else ''
      if '# map:sofa' in text or '.sofa/' in text:  # OR: skip if line exists by any means
          return
      gitignore.write_text(text + '\n# map:sofa\n.sofa/\n')
  ```

- **Spike-First Gating: High-Risk Binding Decisions Require a Docs-Only Artifact Before Implementation** (2026-06-04): When a subtask's answer would bind downstream implementation (which channel carries a value, which API call is idempotent, what schema a subprocess emits), run it FIRST as a docs-only spike that writes an artifact naming the empirical answer + the binding strategy, and commits ZERO production code. Downstream subtasks reference the artifact by name and consume it, not assumptions. A wrong assumption that is not spiked propagates into every component built on it and forces a rewrite cascade. In this workflow a research-agent wrongly claimed skill-activation wasn't recoverable from `claude -p`; the ST-001 spike empirically corrected it before any dispatcher code existed. The spike artifact MUST contain a named "binding strategy" section, not just findings (Monitor hard-stopped once for a missing strategy section). [workflow: map-efficient]

- **Producer-Owns-Parse: The Component That Owns the Subprocess Owns All Derived Fields; Consumers Read the Typed Result** (2026-06-04): When component A launches a subprocess (or owns a raw source) and component B consumes the result, ALL parsing/derivation (transcript reads, field extraction, signal combination) lives in A; B reads only the typed result struct and never re-implements parsing. Two payoffs: (1) a single parse site that a Mock producer can supply directly, so consumer tests need no subprocess/transcript fixture; (2) when the raw output schema changes, only A changes. Putting any parse in B re-couples the modules through the raw format. Extends "Contract-First Inter-Component JSON Schemas": the contract is A's typed struct, and the parse-to-struct boundary is A's responsibility exclusively. [workflow: map-efficient]
  ```python
  # WRONG — runner re-parses a transcript it does not own (couples to raw format)
  result = dispatcher.dispatch(cell)            # raw proc output
  skill = extract_skill_from_transcript(read_jsonl(result.session_id))

  # CORRECT — dispatcher parses once into a typed field; runner just reads it
  @dataclass
  class DispatchResult:
      triggered_skill: str | None   # parsed by dispatcher, NOT by runner
      token_usage: TokenUsage | None
  # tests inject MockDispatcher(triggered_skill="map-plan") — no subprocess needed
  ```

- **Bidirectional Mapping Completeness: Forward AND Reverse Checks Required** (2026-06-21): When validating a mapping structure (coverage_map, import registry, ID→item dict, any key→value store), enforce BOTH directions: REVERSE (every key in the map is legitimately cited by its owning source) AND FORWARD (every item in the authoritative source set appears as a key in the map). Reverse-only validation silently passes dropped entries — an item removed from both the source set and the map in the same commit is invisible to a reverse scan because there is no key to check. The forward check requires an authoritative source-of-truth list independent of the map itself. [workflow: map-efficient]
  ```python
  # WRONG — reverse-only: a dropped AC absent from both spec and coverage_map is never detected.
  def validate_coverage(bp):
      return [f'{k} not cited by {sid}' for k, sids in bp['coverage_map'].items()
              for sid in sids if k not in bp['subtasks'][sid].get('requirements', [])]
  # CORRECT — forward uses an upstream req_index set independent of coverage_map:
  def validate_coverage(bp, req_index: set[str]):
      missing = req_index - set(bp['coverage_map'].keys())   # FORWARD: dropped items surface here
      errors = [f'FORWARD: {r} in index but absent from coverage_map' for r in sorted(missing)]
      # ... plus the REVERSE cite-check as before
      return errors
  ```

- **Upstream-Owned Reference Set: Self-Check Authority Must Be External to the Checked Component** (2026-06-21): When building a completeness gate that checks whether a component (decomposer, code generator, schema migrator) processed every required item, the authoritative list of required items must live UPSTREAM of that component in the data-flow — never be declared by the component itself. If the component declares BOTH the list it must cover AND the coverage map, it can silently drop an item from both simultaneously, producing a consistent-but-incomplete output that passes every check. The upstream artifact (spec, schema definition, API contract) is owned by a different actor and is the only tamper-resistant source. [workflow: map-efficient]
  ```python
  # WRONG — decomposer owns its own authoritative list; dropping AC-007 from both passes.
  # blueprint = {'declared_requirements': [...], 'coverage_map': {...}}  # same author
  # CORRECT — spec markdown (upstream of decomposer) carries a versioned fenced index;
  # the validator reads the index from the SPEC, not from blueprint.json.
  def validate(bp, spec_path):
      req_index = parse_requirements_index(spec_path)   # authoritative, upstream, human-visible
      return req_index - set(bp['coverage_map'].keys()) # {AC-007} even if decomposer never named it
  ```

- **Per-Subtask Render Propagation in Agentic Loops: Commit Generated Trees at Each .jinja-Editing Subtask Close** (2026-06-21): In a per-subtask agentic loop where subtasks edit `.jinja` sources and a render step propagates to N generated trees, never defer all render+commit work to a final subtask. Deferral leaves every intermediate commit with stale generated trees; when Monitor runs `make check-render` mid-loop it sees a non-empty diff and HARD-STOPS with valid=false even though all logic VCs passed — a false blocking failure. Invariant: any subtask that edits a `.jinja` source must also `make render-templates` and commit the rendered output before Monitor sees the commit. After each close, call `refresh_blueprint_affected_files` to register the generated trees (render touches files outside the declared affected_files and trips the mutation-boundary check otherwise). This is N-Output-Tree Parity applied at subtask-loop granularity, not just feature granularity. [workflow: map-efficient]
  ```bash
  # WRONG: ST-001..ST-012 commit .jinja only; ST-013 renders -> Monitor hard-stops at ST-006.
  # CORRECT: at each .jinja-editing subtask close:
  make render-templates
  git add src/mapify_cli/templates_src/ src/mapify_cli/templates/ .claude/ .codex/
  git commit -m "ST-006: ..."
  python3 .map/scripts/map_step_runner.py refresh_blueprint_affected_files "$BRANCH" ST-006
  ```

- **Reserve-Parameter Forward-Compat: Pin a Public Function Signature Early With Unused Params to Prevent Caller-Rewrite Cascades Across Subtasks** (2026-06-29): In a multi-subtask agentic workflow where subtask N defines a function and subtasks N+1..N+K extend it, pin the FINAL intended public signature in subtask N even if some parameters are unused until a later subtask. Suppress unused-parameter warnings with `del param` in the function body (valid in `def`, not `lambda` — see [[del-is-illegal-inside-a-python-lambda-body]]). Without early pinning, each subtask that adds a parameter forces callers and tests from all previous subtasks to be rewritten — a cascade that risks regressions in already-validated outputs and forces Monitor re-validation of untouched subtasks. The unused-param comment must name the subtask that will consume it so Monitor can verify the suppression is intentional; remove the `del` and comment when the parameter becomes live. [workflow: map-efficient]
  ```python
  # WRONG: add parameters one subtask at a time; each addition cascades to all callers
  # ST-006:  def lint_dependency_graph(graph): ...
  # ST-007:  def lint_dependency_graph(graph, affected_files_map, node_io, enforcement, auto_prune): ...  # rewrites every ST-006 caller/test

  # CORRECT: pin the final signature in ST-006; del-suppress params consumed later
  def lint_dependency_graph(graph, affected_files_map=None, node_io=None,
                            enforcement="warn", auto_prune=False) -> list[str]:
      del affected_files_map, node_io, enforcement, auto_prune  # consumed in ST-007 (Layer B)
      return _lint_layer_a(graph)
  # ST-006 callers/tests already call the full signature; ST-007 just removes the del.
  ```

- **Monitor Scope-Correction via Same-Thread Re-Argument, Not Actor Retry, for Forward-Reference False Positives** (2026-07-02): When a Monitor/reviewer agent issues a completeness-style CRITICAL (dangling reference, missing file, unimplemented link) against work that spans a multi-subtask blueprint, do not immediately dispatch Actor rework. First check whether the referenced artifact is a DECLARED deliverable of a LATER subtask (per blueprint.json dependencies and the current subtask's own VC list) — if so, the dangling reference is complete-by-design, not a defect, and forward-reference patterns may already be an established convention in the workflow. The correct recovery is to re-send the SAME Monitor agent thread (via SendMessage, not a fresh dispatch) with quoted blueprint evidence — the subtask's own dependency list and VC scope — so Monitor can re-evaluate against the correct reference frame rather than a whole-file completeness bar. This preserves Monitor's context and avoids wasted Actor rework on code that was never wrong. Only dispatch Actor rework when the missing artifact is NOT a later subtask's declared deliverable. [workflow: map-efficient]
  ```python
  # WRONG: any Monitor CRITICAL about a dangling ref -> immediate Actor retry
  if monitor_result['valid'] == False:
      dispatch_agent('actor', subtask_prompt_with_fix_instructions)

  # CORRECT: check blueprint scope first; re-argue to the SAME Monitor if it's a scope error
  finding = monitor_result['findings'][0]
  referenced_file = extract_referenced_path(finding)  # e.g. 'review-reference.md'
  later_subtask = find_subtask_declaring_deliverable(blueprint, referenced_file)
  current_deps = blueprint['subtasks'][current_id]['dependencies']
  current_vcs = blueprint['subtasks'][current_id]['verification_criteria']

  if later_subtask and later_subtask not in current_deps and referenced_file not in ' '.join(current_vcs):
      # Forward reference is by design -- re-send SAME Monitor thread with evidence
      send_message(to=monitor_agent_id, content=(
          f"Re-check: ST-005 deps={current_deps} (not {later_subtask}); "
          f"VC1-VC4={current_vcs} never mention {referenced_file}. "
          f"{referenced_file} is {later_subtask}'s own declared deliverable, sequenced after this one."
      ))
  else:
      dispatch_agent('actor', subtask_prompt_with_fix_instructions)  # genuine defect
  ```

- **Three-Way Spec/Source/Output Text Drift: Satisfy the Machine-Checkable Contract, Log the Disagreement** (2026-07-02): When porting content between two variants of the same document (e.g. a canonical source and its ported counterpart), a three-way inconsistency can exist simultaneously between the machine-checkable spec (blueprint VC wording), the human-authored source-of-truth being ported FROM, and the actual output being ported TO — all three can use different literal text for the same conceptual element (e.g. `## Architecture` vs `### Section: Architecture` vs `### Architecture`), and none of the three may agree. When this is discovered mid-subtask, resolve by satisfying the machine-checkable contract (the blueprint VC's literal wording) over source-fidelity, because the VC is what downstream automation (dispatch parsing, section-based diffing) actually depends on — but explicitly log the three-way disagreement so a follow-up can reconcile the spec and the human source, since silently picking one without noting the drift leaves the other two inconsistent for the next port. [workflow: map-efficient]
  ```markdown
  <!-- Discovered during a Codex port: -->
  <!-- Canonical source-of-truth:                 ### Section: Architecture -->
  <!-- Blueprint VC1 (machine-checkable):          ## Architecture -->
  <!-- Actor's first attempt (nested heading):     ### Architecture -->

  <!-- Resolution: match the blueprint VC literally (machine-checkable contract wins) -->
  ## Architecture
  ...
  ## Code Quality
  ...
  <!-- Follow-up note (not blocking this subtask): file a doc-drift note so the
       canonical source and the blueprint spec text get reconciled to agree with
       each other, not just with this one port -->
  ```
