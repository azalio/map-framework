#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "typer",
#     "rich",
#     "platformdirs",
#     "readchar",
#     "httpx",
#     "truststore",
# ]
# ///
"""
Mapify CLI - Setup tool for MAP Framework projects

Usage:
    uvx mapify init <project-name>
    uvx mapify init .
    uvx mapify init --here

Or install globally:
    uv tool install mapify-cli --from git+https://github.com/azalio/map-framework.git
    mapify init <project-name>
    mapify check
"""

__version__ = "1.0.0"

import os
import subprocess
import sys
import shutil
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

import typer
import httpx
import readchar
import ssl
try:
    import truststore
    HAS_TRUSTSTORE = True
except ImportError:
    HAS_TRUSTSTORE = False

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.align import Align
from rich.table import Table
from rich.tree import Tree
from typer.core import TyperGroup

# Create secure SSL context with proper fallback
def create_ssl_context():
    """Create SSL context with proper certificate validation."""
    try:
        if HAS_TRUSTSTORE:
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            return context
    except Exception:
        pass

    # Fallback to standard SSL context
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context

ssl_context = create_ssl_context()

# Constants
MCP_SERVER_CHOICES = {
    "all": "All available MCP servers",
    "essential": "Essential (cipher, claude-reviewer, sequential-thinking)",
    "docs": "Documentation (context7, deepwiki)",
    "custom": "Select individually",
    "none": "Skip MCP setup"
}

INDIVIDUAL_MCP_SERVERS = {
    "cipher": "Knowledge management system",
    "claude-reviewer": "Professional code review",
    "sequential-thinking": "Chain-of-thought reasoning",
    "codex-bridge": "AI code generation",
    "context7": "Library documentation",
    "deepwiki": "GitHub repository intelligence"
}

# ASCII Art Banner
BANNER = """
╔╦╗╔═╗╔═╗  ╦╔═╦╔╦╗
║║║╠═╣╠═╝  ╠╩╗║ ║
╩ ╩╩ ╩╩    ╩ ╩╩ ╩
"""

TAGLINE = "MAP Kit - Modular Agentic Planner Framework for Claude Code"

console = Console()

class StepTracker:
    """Track and render hierarchical steps as a tree"""
    def __init__(self, title: str):
        self.title = title
        self.steps: List[Dict[str, Any]] = []  # list of dicts: {key, label, status, detail}
        self._refresh_cb = None

    def attach_refresh(self, cb):
        self._refresh_cb = cb

    def add(self, key: str, label: str):
        if key not in [s["key"] for s in self.steps]:
            self.steps.append({"key": key, "label": label, "status": "pending", "detail": ""})
            self._maybe_refresh()

    def start(self, key: str, detail: str = ""):
        self._update(key, status="running", detail=detail)

    def complete(self, key: str, detail: str = ""):
        self._update(key, status="done", detail=detail)

    def error(self, key: str, detail: str = ""):
        self._update(key, status="error", detail=detail)

    def skip(self, key: str, detail: str = ""):
        self._update(key, status="skipped", detail=detail)

    def _update(self, key: str, status: str, detail: str):
        for s in self.steps:
            if s["key"] == key:
                s["status"] = status
                if detail:
                    s["detail"] = detail
                self._maybe_refresh()
                return
        # If not present, add it
        self.steps.append({"key": key, "label": key, "status": status, "detail": detail})
        self._maybe_refresh()

    def _maybe_refresh(self):
        if self._refresh_cb:
            try:
                self._refresh_cb()
            except Exception:
                pass

    def render(self):
        tree = Tree(f"[cyan]{self.title}[/cyan]", guide_style="grey50")
        for step in self.steps:
            label = step["label"]
            detail_text = step["detail"].strip() if step["detail"] else ""

            # Status symbols
            status = step["status"]
            if status == "done":
                symbol = "[green]●[/green]"
            elif status == "pending":
                symbol = "[green dim]○[/green dim]"
            elif status == "running":
                symbol = "[cyan]○[/cyan]"
            elif status == "error":
                symbol = "[red]●[/red]"
            elif status == "skipped":
                symbol = "[yellow]○[/yellow]"
            else:
                symbol = " "

            if status == "pending":
                # Entire line light gray (pending)
                if detail_text:
                    line = f"{symbol} [bright_black]{label} ({detail_text})[/bright_black]"
                else:
                    line = f"{symbol} [bright_black]{label}[/bright_black]"
            else:
                # Label white, detail light gray in parentheses
                if detail_text:
                    line = f"{symbol} [white]{label}[/white] [bright_black]({detail_text})[/bright_black]"
                else:
                    line = f"{symbol} [white]{label}[/white]"

            tree.add(line)
        return tree


def get_key():
    """Get a single keypress in a cross-platform way"""
    key = readchar.readkey()

    # Arrow keys
    if key == readchar.key.UP or key == readchar.key.CTRL_P:
        return 'up'
    if key == readchar.key.DOWN or key == readchar.key.CTRL_N:
        return 'down'

    # Enter/Return
    if key == readchar.key.ENTER:
        return 'enter'

    # Space for toggle
    if key == ' ':
        return 'space'

    # Escape
    if key == readchar.key.ESC:
        return 'escape'

    # Ctrl+C
    if key == readchar.key.CTRL_C:
        raise KeyboardInterrupt

    return key


def select_with_arrows(options: dict, prompt_text: str = "Select an option", default_key: Optional[str] = None) -> str:
    """Interactive selection using arrow keys"""
    option_keys = list(options.keys())
    if default_key and default_key in option_keys:
        selected_index = option_keys.index(default_key)
    else:
        selected_index = 0

    selected_key = None

    def create_selection_panel():
        """Create the selection panel with current selection highlighted."""
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan", justify="left", width=3)
        table.add_column(style="white", justify="left")

        for i, key in enumerate(option_keys):
            if i == selected_index:
                table.add_row("▶", f"[cyan]{key}[/cyan] [dim]({options[key]})[/dim]")
            else:
                table.add_row(" ", f"[cyan]{key}[/cyan] [dim]({options[key]})[/dim]")

        table.add_row("", "")
        table.add_row("", "[dim]Use ↑/↓ to navigate, Enter to select, Esc to cancel[/dim]")

        return Panel(
            table,
            title=f"[bold]{prompt_text}[/bold]",
            border_style="cyan",
            padding=(1, 2)
        )

    console.print()

    with Live(create_selection_panel(), console=console, transient=True, auto_refresh=False) as live:
        while True:
            try:
                key = get_key()
                if key == 'up':
                    selected_index = (selected_index - 1) % len(option_keys)
                elif key == 'down':
                    selected_index = (selected_index + 1) % len(option_keys)
                elif key == 'enter':
                    selected_key = option_keys[selected_index]
                    break
                elif key == 'escape':
                    console.print("\n[yellow]Selection cancelled[/yellow]")
                    raise typer.Exit(1)

                live.update(create_selection_panel(), refresh=True)

            except KeyboardInterrupt:
                console.print("\n[yellow]Selection cancelled[/yellow]")
                raise typer.Exit(1)

    return selected_key


def select_multiple_with_arrows(options: dict, prompt_text: str = "Select options") -> List[str]:
    """Interactive multiple selection using arrow keys and space"""
    option_keys = list(options.keys())
    selected_index = 0
    selected_items: set[str] = set()

    def create_selection_panel():
        """Create the selection panel with checkboxes"""
        table = Table.grid(padding=(0, 2))
        table.add_column(style="cyan", justify="left", width=3)
        table.add_column(style="white", justify="left")

        for i, key in enumerate(option_keys):
            checkbox = "[x]" if key in selected_items else "[ ]"
            if i == selected_index:
                table.add_row("▶", f"{checkbox} [cyan]{key}[/cyan] [dim]({options[key]})[/dim]")
            else:
                table.add_row(" ", f"{checkbox} [cyan]{key}[/cyan] [dim]({options[key]})[/dim]")

        table.add_row("", "")
        table.add_row("", f"[dim]Selected: {len(selected_items)}/{len(options)}[/dim]")
        table.add_row("", "[dim]Use ↑/↓ to navigate, Space to toggle, Enter to confirm, Esc to cancel[/dim]")

        return Panel(
            table,
            title=f"[bold]{prompt_text}[/bold]",
            border_style="cyan",
            padding=(1, 2)
        )

    console.print()

    with Live(create_selection_panel(), console=console, transient=True, auto_refresh=False) as live:
        while True:
            try:
                key = get_key()
                if key == 'up':
                    selected_index = (selected_index - 1) % len(option_keys)
                elif key == 'down':
                    selected_index = (selected_index + 1) % len(option_keys)
                elif key == 'space':
                    current_key = option_keys[selected_index]
                    if current_key in selected_items:
                        selected_items.remove(current_key)
                    else:
                        selected_items.add(current_key)
                elif key == 'enter':
                    break
                elif key == 'escape':
                    console.print("\n[yellow]Selection cancelled[/yellow]")
                    raise typer.Exit(1)

                live.update(create_selection_panel(), refresh=True)

            except KeyboardInterrupt:
                console.print("\n[yellow]Selection cancelled[/yellow]")
                raise typer.Exit(1)

    return list(selected_items)


class BannerGroup(TyperGroup):
    """Custom group that shows banner before help."""

    def format_help(self, ctx, formatter):
        # Show banner before help
        show_banner()
        super().format_help(ctx, formatter)


app = typer.Typer(
    name="mapify",
    help="Setup tool for MAP Framework projects",
    add_completion=False,
    invoke_without_command=True,
    cls=BannerGroup,
)


def show_banner():
    """Display the ASCII art banner."""
    banner_lines = BANNER.strip().split('\n')
    colors = ["bright_blue", "blue", "cyan"]

    styled_banner = Text()
    for i, line in enumerate(banner_lines):
        color = colors[i % len(colors)]
        styled_banner.append(line + "\n", style=color)

    console.print(Align.center(styled_banner))
    console.print(Align.center(Text(TAGLINE, style="italic bright_yellow")))
    console.print()


@app.callback()
def callback(ctx: typer.Context):
    """Show banner when no subcommand is provided."""
    if ctx.invoked_subcommand is None and "--help" not in sys.argv and "-h" not in sys.argv:
        show_banner()
        console.print(Align.center("[dim]Run 'mapify --help' for usage information[/dim]"))
        console.print()


def check_tool(tool: str) -> bool:
    """Check if a tool is installed."""
    # Special handling for Claude CLI
    if tool == "claude":
        claude_local_path = Path.home() / ".claude" / "local" / "claude"
        if claude_local_path.exists() and claude_local_path.is_file():
            return True

    return shutil.which(tool) is not None


def check_mcp_server(server: str) -> bool:
    """Check if an MCP server is available/configured"""
    # For now, we'll assume MCP servers are available if configured
    # In a real implementation, you'd check actual MCP configuration
    return True


def get_templates_dir() -> Path:
    """Get the path to bundled templates directory."""
    import importlib.resources
    try:
        # Python 3.11+ with importlib.resources.files
        if hasattr(importlib.resources, 'files'):
            return Path(str(importlib.resources.files('mapify_cli') / 'templates'))
    except Exception:
        pass

    # Fallback to module directory
    module_dir = Path(__file__).parent
    templates_dir = module_dir / "templates"
    if templates_dir.exists():
        return templates_dir

    # Development mode - check parent directories
    for parent in [module_dir.parent, module_dir.parent.parent]:
        templates_dir = parent / "templates"
        if templates_dir.exists():
            return templates_dir

    raise RuntimeError("Templates directory not found. Please reinstall mapify-cli.")


def create_agent_files(project_path: Path, mcp_servers: List[str]) -> None:
    """Create MAP agent files in .claude/agents/"""
    agents_dir = project_path / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Always generate the 9 MAP agents with correct content
    agents = {
        "task-decomposer": create_task_decomposer_content(mcp_servers),
        "actor": create_actor_content(mcp_servers),
        "monitor": create_monitor_content(mcp_servers),
        "predictor": create_predictor_content(mcp_servers),
        "evaluator": create_evaluator_content(mcp_servers),
        "orchestrator": create_orchestrator_content(mcp_servers),
        "documentation-reviewer": create_documentation_reviewer_content(mcp_servers)
    }

    for name, content in agents.items():
        agent_file = agents_dir / f"{name}.md"
        agent_file.write_text(content)


def create_task_decomposer_content(mcp_servers: List[str]) -> str:
    """Create task-decomposer agent content"""
    mcp_section = ""
    if any(s in mcp_servers for s in ["cipher", "sequential-thinking", "deepwiki", "context7"]):
        mcp_section = """
## MCP Integration

**ALWAYS use these MCP tools:**
"""
        if "cipher" in mcp_servers:
            mcp_section += """
1. **mcp__cipher__cipher_memory_search** - Search for similar features/patterns
   - Query: "feature implementation [feature_name]"
   - Query: "task decomposition [similar_goal]"
"""
        if "sequential-thinking" in mcp_servers:
            mcp_section += """
2. **mcp__sequential-thinking__sequentialthinking** - For complex planning
   - Use when goal is ambiguous or has many dependencies
"""
        if "deepwiki" in mcp_servers:
            mcp_section += """
3. **mcp__deepwiki__ask_question** - Get insights from GitHub repositories
   - Ask: "How does [repo] implement [feature]?"
"""
        if "context7" in mcp_servers:
            mcp_section += """
4. **mcp__context7__get-library-docs** - Get up-to-date library documentation
   - First use resolve-library-id to find the library
"""

    return f"""---
name: task-decomposer
description: Breaks complex goals into atomic, testable subtasks (MAP)
tools: Read, Grep, Glob
model: sonnet
---

# Role: Task Decomposition Specialist (MAP)

You are a software architect who turns high-level feature goals into clear, atomic, testable subtasks with explicit dependencies and acceptance criteria.
{mcp_section}
## Responsibilities

- Analyze the goal and repository context
- Identify prerequisites and dependencies
- Produce a logically ordered list of atomic subtasks
- Include affected files, risks, and acceptance criteria

## Output Format (JSON only)

Return a valid JSON document with subtasks, dependencies, and acceptance criteria.
"""


def create_actor_content(mcp_servers: List[str]) -> str:
    """Create actor agent content"""
    mcp_section = ""
    if any(s in mcp_servers for s in ["cipher", "codex-bridge", "context7", "deepwiki"]):
        mcp_section = """
# MCP INTEGRATION

**ALWAYS use these MCP tools:**
"""
        if "cipher" in mcp_servers:
            mcp_section += """
1. **mcp__cipher__cipher_memory_search** - Search for code patterns
   - Query: "implementation pattern [feature_type]"
   - Store successful implementations after validation
"""
        if "codex-bridge" in mcp_servers:
            mcp_section += """
2. **mcp__codex-bridge__consult_codex** - Generate optimized code solutions
   - Use for complex algorithms or unfamiliar APIs
   - NOTE: Set timeout=600 (10 minutes) for complex operations
   - Example: consult_codex(query="...", directory=".", timeout=600)
"""
        if "context7" in mcp_servers:
            mcp_section += """
3. **mcp__context7__get-library-docs** - Get current library documentation
   - Essential when using external libraries/frameworks
"""
        if "deepwiki" in mcp_servers:
            mcp_section += """
4. **mcp__deepwiki__read_wiki_contents** - Study implementation patterns
   - Learn from production code examples
"""

    return f"""---
name: actor
description: Generates production-ready implementation proposals (MAP)
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

# IDENTITY

You are a senior software engineer who writes clean, efficient, production-ready code.
{mcp_section}
# SOURCE OF TRUTH (CRITICAL FOR DOCUMENTATION)

**IF writing or updating documentation, ALWAYS find and read source documents FIRST:**

## Discovery Process

1. **Find design documents** via Glob:
   - **/tech-design.md, **/architecture.md, **/design-doc.md, **/api-spec.md
   - Look in: docs/, docs/private/, docs/architecture/, project root
   - Check parent directories if in decomposition subfolder

2. **Read source BEFORE writing**:
   - Extract API structures (spec, status fields, exact types)
   - Extract lifecycle logic (enabled/disabled, install/uninstall triggers)
   - Extract component responsibilities (who installs, who owns CRDs)
   - Extract integration patterns (data flows, adapters needed)

3. **Use source as authority**:
   - DON'T generalize from examples or DOD scenarios
   - DON'T assume partial patterns apply globally
   - DON'T write critical sections without verifying against source
   - DO quote exact field names, types, logic from source

## Common Mistakes to Avoid

❌ Wrong: Using presets: [] (empty array for one engine) when source defines engines: {{}} (empty map for all engines)
❌ Wrong: Generalizing from DOD scenario to Uninstallation logic
❌ Wrong: Writing "triggers deletion" without checking what exactly gets deleted

✅ Right: Read tech-design.md → Find definitions → Use exact syntax
✅ Right: Check lifecycle section in source → Verify behavior → Document accurately
✅ Right: Look up component responsibilities → State correctly if source says so

## When Writing Documentation

- Step 1: Find source documents (Glob for **/tech-design.md, etc.)
- Step 2: Read source completely (don't just search for keywords)
- Step 3: Extract authoritative definitions (API, lifecycle, responsibilities)
- Step 4: Write section using source definitions
- Step 5: Cross-reference: Does my text match source? Line by line?

Remember: tech-design.md is source of truth, NOT DOD scenarios, NOT examples, NOT your interpretation.

# TASK

Implement the subtask with clean, testable code following project patterns.

# OUTPUT FORMAT

Provide implementation with approach, code changes, trade-offs, and testing considerations.
"""


def create_monitor_content(mcp_servers: List[str]) -> str:
    """Create monitor agent content"""
    mcp_section = ""
    if "claude-reviewer" in mcp_servers:
        mcp_section = """
# MCP INTEGRATION

**ALWAYS use these MCP tools for comprehensive review:**

1. **mcp__claude-reviewer__request_review** - Get professional AI code review
   - Use FIRST to get baseline review, then add your analysis
"""

    return f"""---
name: monitor
description: Reviews code for correctness, standards, security, and testability (MAP)
tools: Read, Grep, Bash, Glob
model: sonnet
---

# IDENTITY

You are a meticulous code reviewer and security expert. Your mission is to catch bugs, vulnerabilities, and violations before code reaches production.
{mcp_section}
# REVIEW CHECKLIST

Work through: Correctness, Security, Code Quality, Performance, Testability, Maintainability

## DOCUMENTATION CONSISTENCY (CRITICAL)

**When reviewing decomposition/implementation documents:**

- Find source of truth (tech-design.md, architecture.md):
  * Use Glob: **/tech-design.md, **/architecture.md, **/design-doc.md
  * Look in parent directories if reviewing decomposition

- Read source document FIRST
- Verify API consistency:
  * All spec fields match source?
  * All status fields match source?
  * Field types and defaults consistent?
  * Example: engines: {{}} vs presets: [] - different semantics!

- Verify lifecycle consistency:
  * Does enabled: false behavior match source?
  * Are uninstallation triggers correct?
  * Are state transitions consistent?
  * Check two-level patterns (e.g., enabled: false vs engines: {{}})

- Verify component responsibilities:
  * Installation ownership matches source?
  * CRD ownership consistent?
  * Integration patterns same as source?

Red flags - mark as CRITICAL issue:
- Decomposition contradicts tech-design on lifecycle logic
- Missing critical spec/status fields from source
- Wrong component ownership
- Lifecycle levels confused (partial vs global state)
- Not using tech-design definitions (generalizing from examples instead)

# OUTPUT FORMAT (JSON)

Return strictly valid JSON with validation results and specific issues.
"""


def create_predictor_content(mcp_servers: List[str]) -> str:
    """Create predictor agent content"""
    mcp_section = ""
    if any(s in mcp_servers for s in ["cipher", "codex-bridge", "deepwiki", "context7"]):
        mcp_section = """
## MCP Integration

**ALWAYS use these MCP tools:**
"""
        if "cipher" in mcp_servers:
            mcp_section += """
1. **mcp__cipher__cipher_memory_search** - Find similar impact patterns
   - Query: "impact analysis [change_type]"
   - Learn from past breaking changes
"""
        if "codex-bridge" in mcp_servers:
            mcp_section += """
2. **mcp__codex-bridge__consult_codex** - Analyze complex dependency chains
   - Use for deep code analysis and impact prediction
   - NOTE: Set timeout=600 (10 minutes) for thorough analysis
   - Example: consult_codex(query="analyze impact of...", directory=".", timeout=600)
"""
        if "deepwiki" in mcp_servers:
            mcp_section += """
3. **mcp__deepwiki__ask_question** - Check how repos handle similar changes
   - Ask: "What breaks when changing [component]?"
"""
        if "context7" in mcp_servers:
            mcp_section += """
4. **mcp__context7__get-library-docs** - Check library compatibility
   - Verify API changes against current documentation
"""

    return f"""---
name: predictor
description: Predicts consequences and dependency impact of changes (MAP)
tools: Read, Grep, Glob, Bash
model: sonnet
---

# Role: Impact Analysis Specialist (MAP)

You analyze proposed changes to predict their effects across the codebase.
{mcp_section}
## Analysis Process

1. Read the proposed code changes
2. Identify directly modified files and APIs
3. Trace dependencies using Grep/Glob
4. Predict the resulting state and risks

## Output Format (JSON only)

Return JSON with predicted state, affected components, breaking changes, and risk assessment.
"""


def create_evaluator_content(mcp_servers: List[str]) -> str:
    """Create evaluator agent content"""
    return """---
name: evaluator
description: Evaluates solution quality and completeness (MAP)
tools: Read, Bash, Grep
model: sonnet
---

# Role: Solution Quality Evaluator (MAP)

You provide objective scoring based on multi-dimensional quality criteria.

## Evaluation Criteria (0–10)

1. Functionality — meets requirements
2. Code Quality — readability, maintainability
3. Performance — efficiency
4. Security — best practices
5. Testability — ease of testing
6. Completeness — tests/docs/error handling

## Output Format (JSON only)

Return JSON with scores, strengths, weaknesses, and recommendation (proceed|improve|reconsider).
"""


def create_orchestrator_content(mcp_servers: List[str]) -> str:
    """Create orchestrator agent content"""
    return """---
name: orchestrator
description: Manages the MAP workflow with Claude Code subagents
tools: Read, Write, Bash
model: sonnet
---

# Role: Development Workflow Orchestrator (MAP)

Coordinate TaskDecomposer → Actor ↔ Monitor → Predictor → Evaluator to achieve the stated goal efficiently with high quality.

## Orchestration Pattern

```
DECOMPOSE(goal)
FOR each subtask in plan:
  REPEAT up to N iterations:
    solution = IMPLEMENT(subtask)
    review = VALIDATE(solution)
    if !review.valid: feedback→Actor; CONTINUE
    impact = PREDICT(solution)
    eval = EVALUATE(solution, impact)
    if eval.recommendation == "proceed": ACCEPT and APPLY changes; BREAK
    else: feedback→Actor; CONTINUE
  if not accepted: ESCALATE (human clarifications)
```

## Status Output

Regularly summarize current subtask, decisions, and next actions.
"""


def create_documentation_reviewer_content(mcp_servers: List[str]) -> str:
    """Create documentation-reviewer agent content"""
    mcp_section = ""
    if any(s in mcp_servers for s in ["cipher", "context7", "deepwiki"]):
        mcp_section = """
# MCP INTEGRATION

**ALWAYS use these tools for documentation review:**
"""
        if "cipher" in mcp_servers:
            mcp_section += """
1. **mcp__cipher__cipher_memory_search** - Check for known patterns
   - Query: "external dependency detection [technology]"
   - Query: "CRD installation pattern [project]"
"""
        if "context7" in mcp_servers:
            mcp_section += """
2. **mcp__context7__get-library-docs** - Verify library requirements
   - Check official docs for installation requirements
   - Validate version compatibility
"""
        if "deepwiki" in mcp_servers:
            mcp_section += """
3. **mcp__deepwiki__ask_question** - Compare with similar projects
   - Ask: "How do other projects handle [integration]?"
   - Learn from successful implementations
"""

    return f"""---
name: documentation-reviewer
description: Reviews technical documentation for completeness, external dependencies, and architectural consistency
tools: Read, Grep, Glob, Fetch
model: sonnet
---

# IDENTITY

You are a technical documentation expert specialized in architecture reviews and dependency analysis.
{mcp_section}
# REVIEW CHECKLIST

## 1. EXTERNAL DEPENDENCIES SCAN
- Extract all URLs via pattern matching
- Use Fetch tool (10s timeout) to verify each URL
- Check for CRDs, Helm charts, installation instructions
- Determine installation responsibility
- Verify documentation completeness

## 2. CRD DETECTION LOGIC
Look for:
- YAML with apiVersion: apiextensions.k8s.io/v1
- kind: CustomResourceDefinition
- Mentions of "custom resource"
- Controller/operator projects

## 3. CONSISTENCY WITH SOURCE OF TRUTH (CRITICAL)

**ALWAYS verify decomposition documents against tech-design/architecture:**

### Source of Truth Discovery
- Find source documents via Glob: **/tech-design.md, **/architecture.md, **/design-doc.md
- Look in parent directories: docs/, docs/private/, project root
- Read source documents FIRST before reviewing decomposition
- Extract key concepts: API structures, lifecycle states, component responsibilities, integration patterns

### Consistency Validation
For each section in target document, verify against source:
- API fields match exactly (all spec and status fields present, types consistent)
  * Example: engines: {{}} (empty map) vs engines.kyverno.presets: [] (empty array) - different semantics!
- Lifecycle logic matches (installation/uninstallation triggers same as in source)
  * Check: Does enabled: false delete all? Does engines: {{}} delete ClusterPolicySet only?
- Component responsibilities match (who installs what, who owns CRDs, who triggers actions)
- Integration patterns match (data flow direction, adapter requirements, API versions)

### Red Flags (Auto-fail if found)
❌ Critical inconsistencies:
- Target document contradicts source on lifecycle logic
- Missing critical spec/status fields from source
- Wrong component ownership (e.g., "User installs" when source says "Component Manager installs")
- Lifecycle levels confused (e.g., using presets: [] when should be engines: {{}})

❌ Common mistakes to catch:
- Generalizing from DOD scenarios instead of using tech-design definitions
- Mixing partial state (presets: [] for one engine) with global state (engines: {{}} for all)
- Missing "two-level" patterns (e.g., enabled: false vs engines: {{}})
- Not reading tech-design before writing critical sections

## OUTPUT FORMAT (JSON)

Return strictly valid JSON with:
- valid: boolean
- summary: string
- external_dependencies_checked: array
- missing_requirements: array
- consistency_check: object with source_document, sections_verified, overall_consistency
- score: number (0-10)
- recommendation: "proceed|improve|reconsider"

# DECISION RULES

Return valid=false if:
- Any critical issues found
- External dependencies cannot be verified and are critical
- CRD installation completely undefined
- **Consistency check fails** (overall_consistency: "inconsistent")
- **Source document not read** before reviewing decomposition
- **Critical lifecycle logic mismatch** with source

# CONSTRAINTS

- Be PROACTIVE: Fetch EVERY external URL (with timeout protection)
- Handle errors gracefully: Don't fail on transient network issues
- Security conscious: Validate URLs (no private IPs, localhost)
- Performance aware: Cache results, parallel fetch up to 5 URLs
- Output strictly JSON
"""


def create_command_files(project_path: Path) -> None:
    """Create MAP slash commands in .claude/commands/"""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    commands_template_dir = templates_dir / "commands"

    if not commands_template_dir.exists():
        # Fallback to inline generation if templates not found
        commands = {
            "map-feature": """---
description: Implement new feature using full MAP workflow
---

Use the orchestrator agent to implement the following feature:

$ARGUMENTS

Start with task decomposition, then iterate through actor-monitor-predictor-evaluator for each subtask.
Store successful patterns in knowledge base for future reuse.
""",
            "map-debug": """---
description: Debug issue using MAP analysis
---

Use the orchestrator agent to debug the following issue:

$ARGUMENTS

Decompose the debugging process, implement fixes, validate with monitor, and assess impact.
""",
            "map-refactor": """---
description: Refactor code with MAP impact analysis
---

Use the orchestrator agent to refactor:

$ARGUMENTS

Use predictor to analyze all dependencies, actor to refactor, and evaluator to ensure quality.
""",
            "map-review": """---
description: Comprehensive MAP review of changes
---

Use monitor, predictor, and evaluator agents to review current changes.

Provide detailed analysis of code quality, potential impacts, and quality scores.
"""
        }

        for name, content in commands.items():
            command_file = commands_dir / f"{name}.md"
            command_file.write_text(content)
    else:
        # Copy templates from bundled directory
        import shutil
        for command_template in commands_template_dir.glob("*.md"):
            dest_file = commands_dir / command_template.name
            shutil.copy2(command_template, dest_file)


def install_hooks(project_path: Path, with_hooks: bool = True) -> None:
    """Install Claude Code hooks in .claude/hooks/"""
    if not with_hooks:
        return

    hooks_dir = project_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    hooks_template_dir = templates_dir / "hooks"

    if not hooks_template_dir.exists():
        # Hooks templates not found, skip installation
        return

    # Copy all hook scripts
    import shutil
    import stat

    for hook_file in hooks_template_dir.glob("*.sh"):
        dest_file = hooks_dir / hook_file.name
        shutil.copy2(hook_file, dest_file)
        # Make executable
        dest_file.chmod(dest_file.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Copy README.md
    readme_src = hooks_template_dir / "README.md"
    if readme_src.exists():
        readme_dest = hooks_dir / "README.md"
        shutil.copy2(readme_src, readme_dest)

    # Copy settings.hooks.json to .claude/
    settings_hooks_src = templates_dir / "settings.hooks.json"
    if settings_hooks_src.exists():
        settings_hooks_dest = project_path / ".claude" / "settings.hooks.json"
        shutil.copy2(settings_hooks_src, settings_hooks_dest)


def create_mcp_config(project_path: Path, mcp_servers: List[str]) -> None:
    """Create MCP configuration file"""
    config: Dict[str, Any] = {
        "mcp_servers": {},
        "agent_mcp_mappings": {
            "task-decomposer": [],
            "actor": [],
            "monitor": [],
            "predictor": [],
            "evaluator": [],
            "orchestrator": [],
            "documentation-reviewer": []
        },
        "workflow_settings": {
            "always_retrieve_knowledge": True,
            "store_successful_patterns": True,
            "use_professional_review": True,
            "enable_sequential_thinking": True,
            "knowledge_cache_ttl": 3600
        }
    }

    # Add server configurations
    server_configs = {
        "claude-reviewer": {
            "enabled": True,
            "description": "Professional AI code review",
            "config": {
                "auto_review": True,
                "focus_areas": ["security", "performance", "testing"],
                "severity_threshold": "medium"
            }
        },
        "sequential-thinking": {
            "enabled": True,
            "description": "Chain-of-thought reasoning",
            "config": {
                "max_thoughts": 10,
                "branch_exploration": True,
                "hypothesis_verification": True
            }
        },
        "cipher": {
            "enabled": True,
            "description": "Knowledge management system",
            "config": {
                "auto_store": True,
                "retrieval_limit": 5,
                "conflict_resolution": "manual"
            }
        },
        "codex-bridge": {
            "enabled": True,
            "description": "AI code generation",
            "config": {
                "format": "json",
                "timeout": 600,  # 10 minutes required for complex operations
                "batch_size": 5
            }
        },
        "context7": {
            "enabled": True,
            "description": "Up-to-date library documentation",
            "config": {
                "tokens": 5000,
                "auto_resolve": True,
                "cache_duration": 3600
            }
        },
        "deepwiki": {
            "enabled": True,
            "description": "GitHub repository intelligence",
            "config": {
                "auto_structure": True,
                "max_depth": 3,
                "cache_repos": True
            }
        }
    }

    # Add selected servers
    for server in mcp_servers:
        if server in server_configs:
            config["mcp_servers"][server] = server_configs[server]

    # Update agent mappings based on selected servers
    if "cipher" in mcp_servers:
        for agent in config["agent_mcp_mappings"]:
            config["agent_mcp_mappings"][agent].append("cipher")

    if "sequential-thinking" in mcp_servers:
        for agent in ["task-decomposer", "monitor", "evaluator", "orchestrator"]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("sequential-thinking")

    if "claude-reviewer" in mcp_servers:
        for agent in ["monitor", "evaluator", "orchestrator"]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("claude-reviewer")

    if "codex-bridge" in mcp_servers:
        for agent in ["actor", "predictor"]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("codex-bridge")

    if "context7" in mcp_servers:
        for agent in config["agent_mcp_mappings"]:
            config["agent_mcp_mappings"][agent].append("context7")

    if "deepwiki" in mcp_servers:
        for agent in config["agent_mcp_mappings"]:
            config["agent_mcp_mappings"][agent].append("deepwiki")

    # Write config file
    config_file = project_path / ".claude" / "mcp_config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2))


def init_git_repo(project_path: Path, quiet: bool = False) -> bool:
    """Initialize a git repository"""
    try:
        original_cwd = Path.cwd()
        os.chdir(project_path)
        if not quiet:
            console.print("[cyan]Initializing git repository...[/cyan]")

        # Initialize repository
        subprocess.run(["git", "init"], check=True, capture_output=True)

        # Check if user has configured git identity
        try:
            user_email = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()

            user_name = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True,
                text=True,
                check=False
            ).stdout.strip()

            if not user_email or not user_name:
                if not quiet:
                    console.print("[yellow]Git identity not configured.[/yellow]")
                    console.print("Setting temporary git identity for initial commit...")

                # Set temporary identity for this repository only
                subprocess.run(
                    ["git", "config", "--local", "user.email", "map-framework@example.com"],
                    check=True,
                    capture_output=True
                )
                subprocess.run(
                    ["git", "config", "--local", "user.name", "MAP Framework"],
                    check=True,
                    capture_output=True
                )

                if not quiet:
                    console.print("[yellow]Note: Please configure your git identity with:[/yellow]")
                    console.print("  git config --global user.email 'your.email@example.com'")
                    console.print("  git config --global user.name 'Your Name'")
        except subprocess.CalledProcessError:
            # If we can't check config, set temporary values
            subprocess.run(
                ["git", "config", "--local", "user.email", "map-framework@example.com"],
                check=False,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "--local", "user.name", "MAP Framework"],
                check=False,
                capture_output=True
            )

        # Add files and create initial commit
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Try to commit
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit from MAP Framework"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # Check if it's because there are no changes (all files might be ignored)
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                if not quiet:
                    console.print("[yellow]⚠[/yellow] No files to commit (check .gitignore)")
                return True
            else:
                raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)

        if not quiet:
            console.print("[green]✓[/green] Git repository initialized")
        return True
    except subprocess.CalledProcessError as e:
        if not quiet:
            error_msg = str(e)
            if hasattr(e, 'stderr') and e.stderr:
                error_msg = e.stderr
            console.print(f"[red]Error initializing git repository:[/red] {error_msg}")
            console.print("[yellow]Tip: You can skip git initialization with --no-git[/yellow]")
        return False
    except FileNotFoundError:
        if not quiet:
            console.print("[red]Git is not installed or not in PATH.[/red]")
            console.print("[yellow]Please install git or use --no-git to skip repository initialization[/yellow]")
        return False
    finally:
        os.chdir(original_cwd)


def is_git_repo(path: Optional[Path] = None) -> bool:
    """Check if the specified path is inside a git repository"""
    if path is None:
        path = Path.cwd()

    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            cwd=path,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def is_command(cmd_list: List[str]) -> bool:
    """Check if a command exists on the system."""
    if not cmd_list:
        return False
    try:
        subprocess.run(
            ["which", cmd_list[0]],
            check=True,
            capture_output=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_latest_release(owner: str, repo: str) -> Optional[Dict[str, Any]]:
    """Get the latest release from GitHub."""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        with httpx.Client(verify=create_ssl_context()) as client:
            response = client.get(url)
            if response.status_code == 200:
                return response.json()
    except Exception:
        pass
    return None


def create_commands_dir(project_path: Path) -> None:
    """Create commands directory with README."""
    commands_dir = project_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    readme = commands_dir / "README.md"
    readme.write_text("""# Claude Code Commands

This directory contains custom slash commands for Claude Code.

## Available Commands

- `/map-review` - Comprehensive review of changes using MAP framework
- `/map-refactor` - Refactor code with MAP impact analysis
- `/map-debug` - Debug issues using MAP analysis
- `/map-feature` - Implement new features using full MAP workflow

## Creating Custom Commands

Create a new `.md` file in this directory with the following format:

```markdown
---
description: Brief description of your command
---

Your command prompt here
```

The filename becomes the command name (without the `.md` extension).
""")


@app.command()
def init(
    project_name: Optional[str] = typer.Argument(None, help="Name for your new project directory (use '.' for current directory)"),
    mcp: Optional[str] = typer.Option(None, "--mcp", help="MCP servers to enable: all, essential, docs, none, or comma-separated list"),
    no_git: bool = typer.Option(False, "--no-git", help="Skip git repository initialization"),
    here: bool = typer.Option(False, "--here", help="Initialize project in the current directory"),
    force: bool = typer.Option(False, "--force", help="Force merge/overwrite when using --here"),
    with_hooks: bool = typer.Option(True, "--with-hooks/--no-hooks", help="Install Claude Code hooks (default: yes)"),
):
    """
    Initialize a new MAP Framework project.

    This command will:
    1. Check that required tools are installed
    2. Configure MCP servers
    3. Create MAP agents and commands
    4. Initialize a git repository (optional)

    Examples:
        mapify init my-project
        mapify init my-project --mcp all
        mapify init my-project --mcp "cipher,context7"
        mapify init .
        mapify init --here
    """
    # Show banner
    show_banner()

    # Handle '.' as shorthand for current directory
    if project_name == ".":
        here = True
        project_name = None

    # Validate arguments
    if here and project_name:
        console.print("[red]Error:[/red] Cannot specify both project name and --here flag")
        raise typer.Exit(1)

    if not here and not project_name:
        console.print("[red]Error:[/red] Must specify either a project name, use '.' for current directory, or use --here flag")
        raise typer.Exit(1)

    # Determine project directory
    if here:
        project_name = Path.cwd().name
        project_path = Path.cwd()

        # Check if current directory has any files
        existing_items = list(project_path.iterdir())
        if existing_items:
            console.print(f"[yellow]Warning:[/yellow] Current directory is not empty ({len(existing_items)} items)")
            if not force:
                response = typer.confirm("Do you want to continue?")
                if not response:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    raise typer.Exit(0)
    else:
        project_path = Path(project_name).resolve()
        if project_path.exists():
            console.print(f"[red]Error:[/red] Directory '{project_name}' already exists")
            raise typer.Exit(1)
        project_path.mkdir(parents=True)

    # Setup tracker
    tracker = StepTracker("Initialize MAP Framework Project")

    # Check tools
    tracker.add("check-tools", "Check required tools")
    tracker.start("check-tools")

    git_available = check_tool("git")
    claude_available = check_tool("claude")

    if claude_available:
        tracker.complete("check-tools", "git, claude")
    elif git_available:
        tracker.complete("check-tools", "git")
    else:
        tracker.complete("check-tools", "minimal")

    # Use Claude Code (the only supported AI assistant)
    tracker.add("ai-select", "Select AI assistant")
    selected_ai = "claude"
    tracker.complete("ai-select", selected_ai)

    # Select MCP servers
    tracker.add("mcp-select", "Configure MCP servers")
    tracker.start("mcp-select")

    selected_mcp_servers = []

    if mcp == "all":
        selected_mcp_servers = list(INDIVIDUAL_MCP_SERVERS.keys())
    elif mcp == "essential":
        selected_mcp_servers = ["cipher", "claude-reviewer", "sequential-thinking"]
    elif mcp == "docs":
        selected_mcp_servers = ["context7", "deepwiki"]
    elif mcp == "none":
        selected_mcp_servers = []
    elif mcp:
        # Parse comma-separated list
        selected_mcp_servers = [s.strip() for s in mcp.split(",") if s.strip() in INDIVIDUAL_MCP_SERVERS]
    else:
        # Interactive selection
        mcp_choice = select_with_arrows(MCP_SERVER_CHOICES, "Choose MCP configuration:", "essential")

        if mcp_choice == "all":
            selected_mcp_servers = list(INDIVIDUAL_MCP_SERVERS.keys())
        elif mcp_choice == "essential":
            selected_mcp_servers = ["cipher", "claude-reviewer", "sequential-thinking"]
        elif mcp_choice == "docs":
            selected_mcp_servers = ["context7", "deepwiki"]
        elif mcp_choice == "custom":
            selected_mcp_servers = select_multiple_with_arrows(INDIVIDUAL_MCP_SERVERS, "Select MCP servers:")
        else:
            selected_mcp_servers = []

    tracker.complete("mcp-select", f"{len(selected_mcp_servers)} servers")

    # Create MAP files
    tracker.add("create-agents", "Create MAP agents")
    tracker.start("create-agents")
    create_agent_files(project_path, selected_mcp_servers)
    tracker.complete("create-agents", "9 agents")

    tracker.add("create-commands", "Create slash commands")
    tracker.start("create-commands")
    create_command_files(project_path)
    tracker.complete("create-commands", "4 commands")

    # Install Claude Code hooks
    if with_hooks:
        tracker.add("install-hooks", "Install Claude Code hooks")
        tracker.start("install-hooks")
        install_hooks(project_path, with_hooks=True)
        tracker.complete("install-hooks", "5 hooks installed")

    if selected_mcp_servers:
        tracker.add("mcp-config", "Configure MCP servers")
        tracker.start("mcp-config")
        create_mcp_config(project_path, selected_mcp_servers)
        tracker.complete("mcp-config", f"{len(selected_mcp_servers)} configured")

    # Initialize git
    if not no_git and git_available:
        tracker.add("git", "Initialize git repository")
        tracker.start("git")
        if is_git_repo(project_path):
            tracker.complete("git", "existing repo")
        else:
            if init_git_repo(project_path, quiet=True):
                tracker.complete("git", "initialized")
            else:
                tracker.error("git", "failed")

    tracker.add("finalize", "Finalize")
    tracker.complete("finalize", "project ready")

    # Show final tree
    with Live(tracker.render(), console=console, transient=True) as live:
        tracker.attach_refresh(lambda: live.update(tracker.render()))

    console.print(tracker.render())
    console.print("\n[bold green]✅ Project ready![/bold green]")

    # Next steps
    steps_lines = []
    if not here:
        steps_lines.append(f"1. Go to the project folder: [cyan]cd {project_name}[/cyan]")
        step_num = 2
    else:
        steps_lines.append("1. You're already in the project directory!")
        step_num = 2

    steps_lines.append(f"{step_num}. Start using MAP commands with Claude Code:")
    steps_lines.append("   • [cyan]/map-feature[/] - Implement new feature with MAP workflow")
    steps_lines.append("   • [cyan]/map-debug[/] - Debug issue using MAP analysis")
    steps_lines.append("   • [cyan]/map-refactor[/] - Refactor with impact analysis")
    steps_lines.append("   • [cyan]/map-review[/] - Full MAP review of changes")
    steps_lines.append(f"{step_num + 1}. Or use orchestrator directly:")
    steps_lines.append('   [cyan]"Use orchestrator agent to implement [feature]"[/]')

    steps_panel = Panel("\n".join(steps_lines), title="Next Steps", border_style="cyan", padding=(1, 2))
    console.print()
    console.print(steps_panel)


@app.command()
def check():
    """Check that all required tools are installed."""
    show_banner()
    console.print("[bold]Checking for installed tools...[/bold]\n")

    tracker = StepTracker("Check Available Tools")

    tools = [
        ("git", "Git version control"),
        ("claude", "Claude Code CLI"),
    ]

    # Add tools to tracker
    for tool, description in tools:
        tracker.add(tool, description)

    # Check each tool
    results = {}
    for tool, description in tools:
        if check_tool(tool):
            tracker.complete(tool, "available")
            results[tool] = True
        else:
            tracker.error(tool, "not found")
            results[tool] = False

    console.print(tracker.render())
    console.print()

    if all(results.values()):
        console.print("[bold green]All tools are installed! MAP Framework is ready to use.[/bold green]")
    else:
        console.print("[yellow]Some tools are missing:[/yellow]")
        if not results.get("git"):
            console.print("  • Install git: https://git-scm.com/downloads")
        if not results.get("claude"):
            console.print("  • Install Claude Code: https://docs.anthropic.com/en/docs/claude-code/setup")


@app.command()
def upgrade():
    """Upgrade MAP agents to the latest version."""
    show_banner()
    console.print("[cyan]Checking for updates...[/cyan]")

    # In a real implementation, this would:
    # 1. Fetch latest release from GitHub
    # 2. Compare versions
    # 3. Update agents if newer version available

    console.print("[yellow]Upgrade feature coming soon![/yellow]")
    console.print("For now, run: [cyan]mapify init . --force[/cyan] to update agents")


def main():
    app()


if __name__ == "__main__":
    main()