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

Or install globally:
    uv tool install --from git+https://github.com/azalio/map-framework.git mapify-cli
    mapify init <project-name>
    mapify check
"""

__version__ = "2.2.0"

import copy
import os
import subprocess
import sys
import shutil
import json
import sqlite3
import uuid
from datetime import datetime
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
    "none": "Skip MCP setup",
}

INDIVIDUAL_MCP_SERVERS = {
    "cipher": "Knowledge management system",
    "claude-reviewer": "Professional code review",
    "sequential-thinking": "Chain-of-thought reasoning",
    "context7": "Library documentation",
    "deepwiki": "GitHub repository intelligence",
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
        self.steps: List[Dict[str, Any]] = (
            []
        )  # list of dicts: {key, label, status, detail}
        self._refresh_cb = None

    def attach_refresh(self, cb):
        self._refresh_cb = cb

    def add(self, key: str, label: str):
        if key not in [s["key"] for s in self.steps]:
            self.steps.append(
                {"key": key, "label": label, "status": "pending", "detail": ""}
            )
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
        self.steps.append(
            {"key": key, "label": key, "status": status, "detail": detail}
        )
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
                    line = (
                        f"{symbol} [bright_black]{label} ({detail_text})[/bright_black]"
                    )
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
        return "up"
    if key == readchar.key.DOWN or key == readchar.key.CTRL_N:
        return "down"

    # Enter/Return - support multiple variants for cross-platform compatibility
    if key == readchar.key.ENTER or key == "\r" or key == "\n":
        return "enter"
    # Also check for readchar.key.CR (carriage return) if it exists
    if hasattr(readchar.key, "CR") and key == readchar.key.CR:
        return "enter"
    if hasattr(readchar.key, "LF") and key == readchar.key.LF:
        return "enter"

    # Space for toggle
    if key == " ":
        return "space"

    # Escape
    if key == readchar.key.ESC:
        return "escape"

    # Ctrl+C
    if key == readchar.key.CTRL_C:
        raise KeyboardInterrupt

    return key


def select_with_arrows(
    options: dict,
    prompt_text: str = "Select an option",
    default_key: Optional[str] = None,
) -> str:
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
        table.add_row(
            "", "[dim]Use ↑/↓ to navigate, Enter to select, Esc to cancel[/dim]"
        )

        return Panel(
            table,
            title=f"[bold]{prompt_text}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )

    console.print()

    with Live(
        create_selection_panel(), console=console, transient=True, auto_refresh=False
    ) as live:
        while True:
            try:
                key = get_key()
                if key == "up":
                    selected_index = (selected_index - 1) % len(option_keys)
                elif key == "down":
                    selected_index = (selected_index + 1) % len(option_keys)
                elif key == "enter":
                    selected_key = option_keys[selected_index]
                    break
                elif key == "escape":
                    console.print("\n[yellow]Selection cancelled[/yellow]")
                    raise typer.Exit(1)

                live.update(create_selection_panel(), refresh=True)

            except KeyboardInterrupt:
                console.print("\n[yellow]Selection cancelled[/yellow]")
                raise typer.Exit(1)

    return selected_key


def select_multiple_with_arrows(
    options: dict, prompt_text: str = "Select options"
) -> List[str]:
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
                table.add_row(
                    "▶", f"{checkbox} [cyan]{key}[/cyan] [dim]({options[key]})[/dim]"
                )
            else:
                table.add_row(
                    " ", f"{checkbox} [cyan]{key}[/cyan] [dim]({options[key]})[/dim]"
                )

        table.add_row("", "")
        table.add_row("", f"[dim]Selected: {len(selected_items)}/{len(options)}[/dim]")
        table.add_row(
            "",
            "[dim]Use ↑/↓ to navigate, Space to toggle, Enter to confirm, Esc to cancel[/dim]",
        )

        return Panel(
            table,
            title=f"[bold]{prompt_text}[/bold]",
            border_style="cyan",
            padding=(1, 2),
        )

    console.print()

    with Live(
        create_selection_panel(), console=console, transient=True, auto_refresh=False
    ) as live:
        while True:
            try:
                key = get_key()
                if key == "up":
                    selected_index = (selected_index - 1) % len(option_keys)
                elif key == "down":
                    selected_index = (selected_index + 1) % len(option_keys)
                elif key == "space":
                    current_key = option_keys[selected_index]
                    if current_key in selected_items:
                        selected_items.remove(current_key)
                    else:
                        selected_items.add(current_key)
                elif key == "enter":
                    break
                elif key == "escape":
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

# Create subcommand groups
playbook_app = typer.Typer(name="playbook", help="Manage and search playbook patterns")
validate_app = typer.Typer(name="validate", help="Validate task dependency graphs")

app.add_typer(playbook_app, name="playbook")
app.add_typer(validate_app, name="validate")


def show_banner():
    """Display the ASCII art banner."""
    banner_lines = BANNER.strip().split("\n")
    colors = ["bright_blue", "blue", "cyan"]

    styled_banner = Text()
    for i, line in enumerate(banner_lines):
        color = colors[i % len(colors)]
        styled_banner.append(line + "\n", style=color)

    console.print(Align.center(styled_banner))
    console.print(Align.center(Text(TAGLINE, style="italic bright_yellow")))
    console.print()


def version_callback(value: bool):
    """Callback to show version and exit."""
    if value:
        console.print(f"mapify-cli version {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
):
    """Show banner when no subcommand is provided."""
    if (
        ctx.invoked_subcommand is None
        and "--help" not in sys.argv
        and "-h" not in sys.argv
        and not version
    ):
        show_banner()
        console.print(
            Align.center("[dim]Run 'mapify --help' for usage information[/dim]")
        )
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


def is_debug_enabled(debug_flag: Optional[bool] = None) -> bool:
    """
    Check if debug mode is enabled via CLI flag or environment variable.

    Args:
        debug_flag: CLI --debug flag value (None, True, or False)

    Returns:
        True if debug logging should be enabled
    """
    # CLI flag takes precedence over environment variable
    if debug_flag is not None:
        return debug_flag

    # Check MAP_DEBUG environment variable
    env_debug = os.environ.get("MAP_DEBUG", "").lower()
    return env_debug in ("true", "1", "yes", "on")


def get_templates_dir() -> Path:
    """Get the path to bundled templates directory."""
    import importlib.resources

    try:
        # Python 3.11+ with importlib.resources.files
        if hasattr(importlib.resources, "files"):
            return Path(str(importlib.resources.files("mapify_cli") / "templates"))
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

    # Get templates directory
    templates_dir = get_templates_dir()
    agents_template_dir = templates_dir / "agents"

    if agents_template_dir.exists():
        # Copy original agent files from templates (preserves template variables!)
        import shutil

        # Files to exclude from agent directory (documentation, not agents)
        exclude_files = {"README.md", "CHANGELOG.md", "MCP-PATTERNS.md"}

        for agent_template in agents_template_dir.glob("*.md"):
            # Skip documentation files - they're not agents
            if agent_template.name in exclude_files:
                continue
            dest_file = agents_dir / agent_template.name
            shutil.copy2(agent_template, dest_file)
    else:
        # Fallback: generate simplified versions if templates not found
        # NOTE: orchestrator removed (moved to slash commands in production architecture)
        agents = {
            "task-decomposer": create_task_decomposer_content(mcp_servers),
            "actor": create_actor_content(mcp_servers),
            "monitor": create_monitor_content(mcp_servers),
            "predictor": create_predictor_content(mcp_servers),
            "evaluator": create_evaluator_content(mcp_servers),
            "reflector": create_reflector_content(mcp_servers),
            "curator": create_curator_content(mcp_servers),
            "documentation-reviewer": create_documentation_reviewer_content(
                mcp_servers
            ),
        }

        for name, content in agents.items():
            agent_file = agents_dir / f"{name}.md"
            agent_file.write_text(content)


def create_task_decomposer_content(mcp_servers: List[str]) -> str:
    """Create task-decomposer agent content"""
    mcp_section = ""
    if any(
        s in mcp_servers
        for s in ["cipher", "sequential-thinking", "deepwiki", "context7"]
    ):
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
    if any(s in mcp_servers for s in ["cipher", "context7", "deepwiki"]):
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
        if "context7" in mcp_servers:
            mcp_section += """
2. **mcp__context7__get-library-docs** - Get current library documentation
   - Essential when using external libraries/frameworks
"""
        if "deepwiki" in mcp_servers:
            mcp_section += """
3. **mcp__deepwiki__read_wiki_contents** - Study implementation patterns
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
    if any(s in mcp_servers for s in ["cipher", "deepwiki", "context7"]):
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
        if "deepwiki" in mcp_servers:
            mcp_section += """
2. **mcp__deepwiki__ask_question** - Check how repos handle similar changes
   - Ask: "What breaks when changing [component]?"
"""
        if "context7" in mcp_servers:
            mcp_section += """
3. **mcp__context7__get-library-docs** - Check library compatibility
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


def create_reflector_content(mcp_servers: List[str]) -> str:
    """Create reflector agent content"""
    mcp_section = ""
    if "cipher" in mcp_servers:
        mcp_section = """
# MCP INTEGRATION

**ALWAYS use cipher for knowledge management:**

1. **mcp__cipher__cipher_memory_search** - Check existing patterns
   - Query: "lesson learned [topic]"
   - Avoid duplicating existing knowledge
"""

    return f"""---
name: reflector
description: Extracts structured lessons from execution attempts (ACE)
tools: Read, Grep, Glob
model: sonnet
---

# IDENTITY

You are a reflection specialist who analyzes execution attempts to extract structured, actionable lessons learned.
{mcp_section}
# ROLE

Analyze Actor implementations and Monitor feedback to identify:
- What worked well (success patterns)
- What failed and why (failure patterns)
- Reusable insights for future implementations
- Anti-patterns to avoid

## Output Format (JSON)

Return JSON with:
- key_insight: Main lesson learned
- success_patterns: What worked well
- failure_patterns: What went wrong
- suggested_new_bullets: Playbook entries to add
- confidence: How reliable this insight is
"""


def create_curator_content(mcp_servers: List[str]) -> str:
    """Create curator agent content"""
    mcp_section = ""
    if "cipher" in mcp_servers:
        mcp_section = """
# MCP INTEGRATION

**Use cipher for deduplication:**

1. **mcp__cipher__cipher_memory_search** - Check for duplicate patterns
   - Prevents adding redundant playbook entries
"""

    return f"""---
name: curator
description: Manages structured playbook with incremental updates (ACE)
tools: Read, Write, Edit
model: sonnet
---

# IDENTITY

You are a knowledge curator who maintains the ACE playbook by integrating Reflector insights.
{mcp_section}
# ROLE

Integrate Reflector insights into playbook using delta operations:
- ADD: New pattern bullets
- UPDATE: Increment helpful/harmful counters
- DEPRECATE: Remove harmful patterns

## Quality Gates

- Content length ≥ 100 characters
- Code examples for technical patterns
- Deduplication via semantic similarity
- Technology-specific (not generic advice)

## Output Format (JSON)

Return JSON with:
- reasoning: Why these operations improve playbook
- operations: Array of ADD/UPDATE/DEPRECATE operations
- deduplication_check: What duplicates were found
"""


# Note: test-generator agent removed


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


def create_reference_files(project_path: Path) -> int:
    """Create MAP reference files in .claude/references/

    Returns:
        Number of reference files installed
    """
    references_dir = project_path / ".claude" / "references"
    references_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    references_template_dir = templates_dir / "references"

    count = 0
    if references_template_dir.exists():
        import shutil

        for ref_file in references_template_dir.glob("*.md"):
            dest_file = references_dir / ref_file.name
            shutil.copy2(ref_file, dest_file)
            count += 1

    return count


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
            "map-efficient": """---
description: Implement features with optimized workflow (recommended)
---

Implement the following with efficient MAP workflow:

$ARGUMENTS

Start with task decomposition (task-decomposer), then iterate through actor-monitor for each subtask.
Predictor is called conditionally for high-risk subtasks only.
Run /map-learn after workflow if you want to preserve lessons learned.
""",
            "map-debug": """---
description: Debug issue using MAP analysis
---

Debug the following issue using MAP workflow:

$ARGUMENTS

Decompose the debugging process (task-decomposer), implement fixes (actor), validate with monitor, and assess impact (predictor).
""",
            "map-fast": """---
description: Quick implementation with minimal validation
---

Use minimal workflow to implement:

$ARGUMENTS

Implement quickly with basic monitor validation only. No learning, no predictor.
Use for throwaway code, prototypes, or low-risk changes.
""",
            "map-learn": """---
description: Extract lessons from completed workflows
---

Extract and preserve lessons from recent workflow:

$ARGUMENTS

Call Reflector to extract patterns, then Curator to update playbook.
""",
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


def create_skill_files(project_path: Path) -> int:
    """Create MAP skills in .claude/skills/

    Returns:
        Number of skills installed
    """
    skills_dir = project_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    skills_template_dir = templates_dir / "skills"

    count = 0

    if skills_template_dir.exists():
        # Copy README.md and skill-rules.json to .claude/skills/
        if (skills_template_dir / "README.md").exists():
            shutil.copy2(skills_template_dir / "README.md", skills_dir / "README.md")

        if (skills_template_dir / "skill-rules.json").exists():
            shutil.copy2(
                skills_template_dir / "skill-rules.json",
                skills_dir / "skill-rules.json",
            )

        # Copy each skill directory
        for skill_template in skills_template_dir.iterdir():
            if skill_template.is_dir() and skill_template.name != "__pycache__":
                target = skills_dir / skill_template.name
                shutil.copytree(skill_template, target, dirs_exist_ok=True)
                count += 1

    return count


def create_map_tools(project_path: Path) -> int:
    """Create .map/ directory with static analysis tools."""
    import shutil

    map_dir = project_path / ".map"
    map_dir.mkdir(parents=True, exist_ok=True)

    # Get templates directory
    templates_dir = get_templates_dir()
    map_template_dir = templates_dir / "map"

    count = 0
    if map_template_dir.exists():
        # Copy static-analysis directory
        static_analysis_src = map_template_dir / "static-analysis"
        if static_analysis_src.exists():
            static_analysis_dest = map_dir / "static-analysis"
            if static_analysis_dest.exists():
                try:
                    shutil.rmtree(static_analysis_dest)
                except (OSError, PermissionError) as e:
                    # Log warning but continue - old scripts may be in use
                    import sys

                    print(
                        f"Warning: Could not remove existing {static_analysis_dest}: {e}",
                        file=sys.stderr,
                    )
            shutil.copytree(
                static_analysis_src, static_analysis_dest, dirs_exist_ok=True
            )
            # Make scripts executable
            for script in static_analysis_dest.rglob("*.sh"):
                script.chmod(script.stat().st_mode | 0o755)
                count += 1

    return count


def configure_global_permissions() -> None:
    """Configure global Claude Code permissions for read-only commands"""
    claude_dir = Path.home() / ".claude"
    settings_file = claude_dir / "settings.json"

    # Create .claude directory if it doesn't exist
    claude_dir.mkdir(exist_ok=True)

    # Default permissions for read-only commands
    default_permissions = {
        "allow": [
            "Bash(git status:*)",
            "Bash(git log:*)",
            "Bash(git diff:*)",
            "Bash(git show:*)",
            "Bash(git check-ignore:*)",
            "Bash(git branch --show-current:*)",
            "Bash(git branch -a:*)",
            "Bash(git ls-files:*)",
            "Bash(ls :*)",
            "Bash(cat :*)",
            "Bash(head :*)",
            "Bash(tail :*)",
            "Bash(wc :*)",
            "Bash(grep :*)",
            "Bash(find :*)",
            "Bash(sort :*)",
            "Bash(uniq :*)",
            "Bash(jq :*)",
            "Bash(which :*)",
            "Bash(echo :*)",
            "Bash(pwd:*)",
            "Bash(whoami:*)",
            "Bash(ruby -c :*)",
            "Bash(go fmt /tmp/:*)",
            "Bash(gofmt -l :*)",
            "Bash(gofmt -d :*)",
            "Bash(go vet :*)",
            "Bash(go build:*)",
            "Bash(go test -c:*)",
            "Bash(go mod download:*)",
            "Bash(go mod tidy:*)",
            "Bash(chmod +x:*)",
            "Read(//Users/**)",
            "Read(//private/tmp/**)",
            "Glob(**)",
        ],
        "deny": [],
    }

    # Read existing settings or create new
    if settings_file.exists():
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            console.print(
                "[yellow]Warning:[/yellow] Corrupted settings.json, will recreate"
            )
            settings = {}
    else:
        settings = {}

    # Merge permissions (preserve user's custom permissions)
    if "permissions" not in settings:
        settings["permissions"] = default_permissions
    else:
        # Add new permissions if they don't exist
        existing_allow = set(settings["permissions"].get("allow", []))
        for perm in default_permissions["allow"]:
            if perm not in existing_allow:
                settings["permissions"].setdefault("allow", []).append(perm)

    # Write back
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)

    console.print(f"[green]✓[/green] Configured global permissions in {settings_file}")
    console.print(
        f"[dim]  Added {len(default_permissions['allow'])} read-only command patterns[/dim]"
    )


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
            "reflector": [],
            "curator": [],
            "documentation-reviewer": [],
        },
        "workflow_settings": {
            "always_retrieve_knowledge": True,
            "store_successful_patterns": True,
            "use_professional_review": True,
            "enable_sequential_thinking": True,
            "knowledge_cache_ttl": 3600,
        },
    }

    # Add server configurations
    server_configs = {
        "claude-reviewer": {
            "enabled": True,
            "description": "Professional AI code review",
            "config": {
                "auto_review": True,
                "focus_areas": ["security", "performance", "testing"],
                "severity_threshold": "medium",
            },
        },
        "sequential-thinking": {
            "enabled": True,
            "description": "Chain-of-thought reasoning",
            "config": {
                "max_thoughts": 10,
                "branch_exploration": True,
                "hypothesis_verification": True,
            },
        },
        "cipher": {
            "enabled": True,
            "description": "Knowledge management system",
            "config": {
                "auto_store": True,
                "retrieval_limit": 5,
                "conflict_resolution": "manual",
            },
        },
        "context7": {
            "enabled": True,
            "description": "Up-to-date library documentation",
            "config": {"tokens": 5000, "auto_resolve": True, "cache_duration": 3600},
        },
        "deepwiki": {
            "enabled": True,
            "description": "GitHub repository intelligence",
            "config": {"auto_structure": True, "max_depth": 3, "cache_repos": True},
        },
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
        for agent in [
            "task-decomposer",
            "monitor",
            "evaluator",
            "orchestrator",
            "reflector",
        ]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("sequential-thinking")

    if "claude-reviewer" in mcp_servers:
        for agent in ["monitor", "evaluator", "orchestrator"]:
            if agent in config["agent_mcp_mappings"]:
                config["agent_mcp_mappings"][agent].append("claude-reviewer")

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


# =============================================================================
# Project-level .mcp.json functions (for Claude Code MCP server configuration)
# =============================================================================


def build_standard_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """Build standard MCP server configurations for Claude Code .mcp.json format.

    Returns dict mapping server names to their Claude Code MCP configurations.
    Uses verified configurations from production installations.

    Note: These configs are for the project-level .mcp.json file that Claude Code
    reads, separate from the internal .claude/mcp_config.json.
    """
    return {
        "sequential-thinking": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        },
        "context7": {
            "type": "http",
            "url": "https://mcp.context7.com/mcp",
        },
        "deepwiki": {
            "type": "http",
            "url": "https://mcp.deepwiki.com/mcp",
        },
    }


def read_project_mcp_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read .mcp.json from project root.

    Args:
        path: Path to .mcp.json file

    Returns:
        Parsed JSON dict if file exists and is valid, None otherwise

    Handles:
        - File not found (returns None)
        - Invalid JSON (logs warning, creates backup, returns None)
        - Permission errors (logs warning, returns None)
    """
    if not path.exists():
        return None

    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError as e:
        console.print(f"[yellow]Warning:[/yellow] Invalid JSON in {path.name}: {e}")
        # Create backup with timestamp + UUID to prevent race conditions
        # UUID ensures unique names even with concurrent processes
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        backup_path = path.with_suffix(f".backup.{timestamp}_{unique_id}.json")
        try:
            if path.exists():  # Check before rename to handle concurrent processes
                path.rename(backup_path)
                console.print(
                    f"[dim]Backed up corrupted file to {backup_path.name}[/dim]"
                )
            else:
                console.print(
                    "[dim]Corrupted file already removed by another process[/dim]"
                )
        except OSError as backup_error:
            console.print(
                f"[yellow]Warning:[/yellow] Could not create backup: {backup_error}"
            )
        return None
    except (OSError, PermissionError) as e:
        console.print(f"[yellow]Warning:[/yellow] Cannot read {path.name}: {e}")
        return None


def write_project_mcp_json(path: Path, config: Dict[str, Any]) -> None:
    """Write .mcp.json to project root with proper formatting.

    Args:
        path: Path to .mcp.json file
        config: Configuration dict to write

    Raises:
        OSError: If write fails (permission, disk space, etc.)

    Format:
        - indent=2 for readability
        - UTF-8 encoding
        - Newline at end of file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config, indent=2, ensure_ascii=False)
    path.write_text(content + "\n", encoding="utf-8")


def merge_mcp_json(
    existing: Dict[str, Any], new_servers: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Merge new MCP servers into existing .mcp.json configuration.

    Args:
        existing: Existing .mcp.json content (may be empty dict)
        new_servers: Dict mapping server names to their configs

    Returns:
        Merged configuration with existing servers preserved

    Behavior:
        - Preserves existing mcpServers entries (user customizations)
        - Only adds new servers that don't exist
        - Preserves other top-level keys (e.g., custom settings)
    """
    result = copy.deepcopy(existing)

    # Ensure mcpServers key exists
    if "mcpServers" not in result:
        result["mcpServers"] = {}

    # Merge servers - existing entries take precedence (never overwrite user configs)
    for server_name, server_config in new_servers.items():
        if server_name not in result["mcpServers"]:
            result["mcpServers"][server_name] = server_config

    return result


def create_or_merge_project_mcp_json(
    project_path: Path, mcp_servers: List[str]
) -> None:
    """Create or merge .mcp.json in project root for Claude Code.

    Args:
        project_path: Project root directory
        mcp_servers: List of MCP server names to configure (e.g., ["cipher", "context7"])

    Behavior:
        - If mcp_servers is empty: No file created/modified (early return)
        - If .mcp.json exists: merge new servers (preserve existing)
        - If .mcp.json missing: create new with selected servers
        - Console output shows whether created or merged
        - Existing user servers NEVER overwritten
        - System directories (/etc, /sys, etc.) are rejected for safety

    This creates the project-level .mcp.json that Claude Code uses,
    separate from the internal .claude/mcp_config.json.

    Raises:
        typer.Exit(1): On file write errors or invalid paths
    """
    # Path validation - resolve to prevent traversal
    resolved_path = project_path.resolve()

    # Validate against system directories (defense-in-depth)
    forbidden_prefixes = ["/etc", "/sys", "/proc", "/boot", "/dev", "/var/run"]
    resolved_str = str(resolved_path)
    for forbidden in forbidden_prefixes:
        if resolved_str == forbidden or resolved_str.startswith(forbidden + "/"):
            console.print(
                f"[red]Error:[/red] Cannot initialize in system directory {forbidden}"
            )
            raise typer.Exit(1)

    mcp_json_path = resolved_path / ".mcp.json"

    # Build standard server configs for requested servers
    all_standard_servers = build_standard_mcp_servers()
    selected_servers = {
        name: config
        for name, config in all_standard_servers.items()
        if name in mcp_servers
    }

    if not selected_servers:
        # No servers to configure
        return

    # Read existing config if present
    existing_config = read_project_mcp_json(mcp_json_path)

    try:
        if existing_config is not None:
            # Merge mode - preserve existing entries
            merged_config = merge_mcp_json(existing_config, selected_servers)
            write_project_mcp_json(mcp_json_path, merged_config)

            # Count how many new servers were added
            existing_servers = existing_config.get("mcpServers", {})
            new_count = len([s for s in selected_servers if s not in existing_servers])
            if new_count > 0:
                console.print(
                    f"[green]✓[/green] Merged {new_count} new server(s) into .mcp.json"
                )
            else:
                console.print(
                    "[green]✓[/green] .mcp.json already contains all requested servers"
                )
        else:
            # Create mode - new file
            new_config: Dict[str, Any] = {"mcpServers": selected_servers}
            write_project_mcp_json(mcp_json_path, new_config)
            console.print(
                f"[green]✓[/green] Created .mcp.json with {len(selected_servers)} server(s)"
            )

        # Show which servers are configured
        console.print(
            f"[dim]  Configured: {', '.join(sorted(selected_servers.keys()))}[/dim]"
        )
    except OSError as e:
        console.print(f"[red]Error:[/red] Failed to write .mcp.json: {e}")
        raise typer.Exit(1) from e


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
                check=False,
            ).stdout.strip()

            user_name = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()

            if not user_email or not user_name:
                if not quiet:
                    console.print("[yellow]Git identity not configured.[/yellow]")
                    console.print(
                        "Setting temporary git identity for initial commit..."
                    )

                # Set temporary identity for this repository only
                subprocess.run(
                    [
                        "git",
                        "config",
                        "--local",
                        "user.email",
                        "map-framework@example.com",
                    ],
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "config", "--local", "user.name", "MAP Framework"],
                    check=True,
                    capture_output=True,
                )

                if not quiet:
                    console.print(
                        "[yellow]Note: Please configure your git identity with:[/yellow]"
                    )
                    console.print(
                        "  git config --global user.email 'your.email@example.com'"
                    )
                    console.print("  git config --global user.name 'Your Name'")
        except subprocess.CalledProcessError:
            # If we can't check config, set temporary values
            subprocess.run(
                ["git", "config", "--local", "user.email", "map-framework@example.com"],
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "--local", "user.name", "MAP Framework"],
                check=False,
                capture_output=True,
            )

        # Add files and create initial commit
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        # Try to commit
        result = subprocess.run(
            ["git", "commit", "-m", "Initial commit from MAP Framework"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            # Check if it's because there are no changes (all files might be ignored)
            if (
                "nothing to commit" in result.stdout
                or "nothing to commit" in result.stderr
            ):
                if not quiet:
                    console.print(
                        "[yellow]⚠[/yellow] No files to commit (check .gitignore)"
                    )
                return True
            else:
                raise subprocess.CalledProcessError(
                    result.returncode, result.args, result.stdout, result.stderr
                )

        if not quiet:
            console.print("[green]✓[/green] Git repository initialized")
        return True
    except subprocess.CalledProcessError as e:
        if not quiet:
            error_msg = str(e)
            if hasattr(e, "stderr") and e.stderr:
                error_msg = e.stderr
            console.print(f"[red]Error initializing git repository:[/red] {error_msg}")
            console.print(
                "[yellow]Tip: You can skip git initialization with --no-git[/yellow]"
            )
        return False
    except FileNotFoundError:
        if not quiet:
            console.print("[red]Git is not installed or not in PATH.[/red]")
            console.print(
                "[yellow]Please install git or use --no-git to skip repository initialization[/yellow]"
            )
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
        subprocess.run(["which", cmd_list[0]], check=True, capture_output=True)
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
    readme.write_text(
        """# Claude Code Commands

This directory contains custom slash commands for Claude Code.

## Available Commands

- `/map-efficient` - Implement features with optimized workflow (recommended)
- `/map-debug` - Debug issues using MAP analysis
- `/map-fast` - Quick implementation with minimal validation
- `/map-learn` - Extract lessons from completed workflows
- `/map-release` - Execute MAP Framework package release workflow

## Creating Custom Commands

Create a new `.md` file in this directory with the following format:

```markdown
---
description: Brief description of your command
---

Your command prompt here
```

The filename becomes the command name (without the `.md` extension).
"""
    )


@app.command()
def init(
    project_name: Optional[str] = typer.Argument(
        None, help="Name for your new project directory (use '.' for current directory)"
    ),
    mcp: str = typer.Option(
        "all",
        "--mcp",
        help="MCP server installation (default: all). Options: all, essential, docs, none, or comma-separated list (e.g. cipher,context7)",
    ),
    no_git: bool = typer.Option(
        False, "--no-git", help="Skip git repository initialization"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force merge/overwrite when using '.' in non-empty directory",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Enable debug logging (creates .map/logs/workflow_*.log)"
    ),
):
    """
    Initialize a new MAP Framework project.

    This command will:
    1. Check that required tools are installed
    2. Create MCP configuration files
    3. Install MCP servers (defaults to all available servers)
    4. Create MAP agents and commands
    5. Initialize a git repository (optional)

    Examples:
        mapify init my-project              # Installs all MCP servers
        mapify init my-project --mcp none   # Skip MCP installation
        mapify init my-project --mcp essential
        mapify init my-project --mcp "cipher,context7"
        mapify init .
        mapify init . --force  # Force init in non-empty current directory
        mapify init --debug  # Enable workflow logging
    """
    # Show banner
    show_banner()

    # Initialize workflow logger if debug mode is enabled
    workflow_logger = None
    if is_debug_enabled(debug):
        from mapify_cli.workflow_logger import MapWorkflowLogger

        workflow_logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = workflow_logger.start_session(
            task_id=f"mapify_init_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        console.print(f"[dim]Debug logging enabled: {log_file}[/dim]")
        workflow_logger.log_event(
            "command_start",
            f"mapify init {project_name or '.'}",
            metadata={"debug": debug, "mcp": mcp},
        )

    # Handle '.' as shorthand for current directory
    use_current_dir = project_name == "."

    if use_current_dir:
        project_name = None

    # Validate arguments
    if not use_current_dir and not project_name:
        console.print(
            "[red]Error:[/red] Must specify either a project name or use '.' for current directory"
        )
        raise typer.Exit(1)

    # Determine project directory
    if use_current_dir:
        project_name = Path.cwd().name
        project_path = Path.cwd()

        # Check if current directory has any files
        existing_items = list(project_path.iterdir())
        if existing_items:
            console.print(
                f"[yellow]Warning:[/yellow] Current directory is not empty ({len(existing_items)} items)"
            )
            if not force:
                response = typer.confirm("Do you want to continue?")
                if not response:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    raise typer.Exit(0)
    else:
        # Type assertion: flow guarantees project_name is not None here
        # (checked at line 1931, and not in use_current_dir branch)
        assert (
            project_name is not None
        ), "project_name must be set in non-current-dir mode"
        project_path = Path(project_name).resolve()
        if project_path.exists():
            console.print(
                f"[red]Error:[/red] Directory '{project_name}' already exists"
            )
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
    tracker.add("mcp-select", "Select MCP servers")
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
    else:
        # Parse comma-separated list
        requested = [s.strip() for s in mcp.split(",") if s.strip()]
        invalid = [s for s in requested if s not in INDIVIDUAL_MCP_SERVERS]
        if invalid:
            console.print(
                f"[yellow]Warning:[/yellow] Unrecognized MCP servers ignored: {', '.join(invalid)}"
            )
            console.print(f"Valid servers: {', '.join(INDIVIDUAL_MCP_SERVERS.keys())}")
        selected_mcp_servers = [s for s in requested if s in INDIVIDUAL_MCP_SERVERS]

    tracker.complete("mcp-select", f"{len(selected_mcp_servers)} servers")

    # Create MAP files
    tracker.add("create-agents", "Create MAP agents")
    tracker.start("create-agents")
    create_agent_files(project_path, selected_mcp_servers)
    tracker.complete("create-agents", "8 agents")

    tracker.add("create-commands", "Create slash commands")
    tracker.start("create-commands")
    create_command_files(project_path)
    tracker.complete("create-commands", "4 commands")

    tracker.add("create-skills", "Create skills")
    tracker.start("create-skills")
    skill_count = create_skill_files(project_path)
    skill_word = "skill" if skill_count == 1 else "skills"
    tracker.complete("create-skills", f"{skill_count} {skill_word}")

    tracker.add("create-references", "Create reference files")
    tracker.start("create-references")
    ref_count = create_reference_files(project_path)
    ref_word = "file" if ref_count == 1 else "files"
    tracker.complete("create-references", f"{ref_count} {ref_word}")

    tracker.add("create-map-tools", "Create MAP tools")
    tracker.start("create-map-tools")
    tool_count = create_map_tools(project_path)
    tool_word = "script" if tool_count == 1 else "scripts"
    tracker.complete("create-map-tools", f"{tool_count} {tool_word}")

    if selected_mcp_servers:
        # Create internal MCP config (for MAP Framework agent mappings)
        tracker.add("mcp-config", "Create internal MCP config")
        tracker.start("mcp-config")
        create_mcp_config(project_path, selected_mcp_servers)
        tracker.complete("mcp-config", f"{len(selected_mcp_servers)} servers")

        # Create/merge project .mcp.json (for Claude Code MCP server registration)
        tracker.add("mcp-project", "Create/merge .mcp.json")
        tracker.start("mcp-project")
        create_or_merge_project_mcp_json(project_path, selected_mcp_servers)
        tracker.complete("mcp-project", "Claude Code MCP config")

    # Initialize playbook database
    tracker.add("init-playbook", "Initialize playbook database")
    tracker.start("init-playbook")
    try:
        from mapify_cli.playbook_manager import PlaybookManager

        playbook_db_path = project_path / ".claude" / "playbook.db"
        playbook_json_path = project_path / ".claude" / "playbook.json"

        # When --force is used and playbook.json exists, handle migration scenarios
        if force and playbook_json_path.exists() and playbook_db_path.exists():
            # Check if the existing DB has valid schema (requires both bullets and metadata tables)
            db_is_valid = False
            try:
                test_conn = sqlite3.connect(str(playbook_db_path))
                cursor = test_conn.cursor()
                # Check for required tables
                cursor.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('bullets', 'metadata')"
                )
                table_count = cursor.fetchone()[0]
                test_conn.close()
                db_is_valid = table_count == 2  # Both tables must exist
            except sqlite3.Error:
                db_is_valid = False

            if not db_is_valid:
                # DB is missing required schema or corrupted - remove it to allow migration
                try:
                    playbook_db_path.unlink()
                    console.print(
                        "[yellow]Removing incomplete playbook.db to migrate from playbook.json[/yellow]"
                    )
                except OSError:
                    pass  # If we can't remove it, let PlaybookManager handle the error
            else:
                # DB is valid but playbook.json also exists - remove stale JSON to avoid confusion
                # Create backup first in case user needs it
                backup_path = str(playbook_json_path) + ".stale"
                try:
                    import shutil

                    shutil.move(str(playbook_json_path), backup_path)
                    console.print(
                        f"[yellow]Moved stale playbook.json to {backup_path} (valid playbook.db already exists)[/yellow]"
                    )
                except OSError:
                    pass  # If we can't move it, it's not critical

        manager = PlaybookManager(
            db_path=str(playbook_db_path), use_semantic_search=False
        )
        manager.close()
        tracker.complete("init-playbook", "database created")
    except sqlite3.Error as e:
        tracker.error("init-playbook", "database error")
        console.print(f"[red]Error:[/red] Failed to initialize playbook database: {e}")
        console.print("[yellow]Please check disk space and permissions[/yellow]")
        raise typer.Exit(1)
    except PermissionError as e:
        tracker.error("init-playbook", "permission denied")
        console.print(f"[red]Error:[/red] Permission denied creating playbook: {e}")
        console.print(
            "[yellow]Run with appropriate permissions or choose a different directory[/yellow]"
        )
        raise typer.Exit(1)
    except OSError as e:
        tracker.error("init-playbook", "filesystem error")
        console.print(f"[red]Error:[/red] Could not create playbook directory: {e}")
        console.print("[yellow]Please check directory permissions[/yellow]")
        raise typer.Exit(1)
    except json.JSONDecodeError as e:
        tracker.error("init-playbook", "migration error")
        console.print(f"[red]Error:[/red] Failed to migrate legacy playbook.json: {e}")
        console.print(
            "[yellow]Suggestion: Delete corrupted .claude/playbook.json and run 'mapify init' again[/yellow]"
        )
        raise typer.Exit(1)

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

    # Configure global permissions for read-only commands
    console.print()  # Add spacing
    configure_global_permissions()

    # Show final tree
    with Live(tracker.render(), console=console, transient=True) as live:
        tracker.attach_refresh(lambda: live.update(tracker.render()))

    console.print(tracker.render())
    console.print("\n[bold green]✅ Project ready![/bold green]")

    # Next steps
    steps_lines = []
    if not use_current_dir:
        steps_lines.append(
            f"1. Go to the project folder: [cyan]cd {project_name}[/cyan]"
        )
        step_num = 2
    else:
        steps_lines.append("1. You're already in the project directory!")
        step_num = 2

    steps_lines.append(f"{step_num}. Start using MAP commands with Claude Code:")
    steps_lines.append(
        "   • [cyan]/map-efficient[/] - Implement features with optimized workflow (recommended)"
    )
    steps_lines.append("   • [cyan]/map-debug[/] - Debug issue using MAP analysis")
    steps_lines.append(
        "   • [cyan]/map-fast[/] - Quick implementation with minimal validation"
    )
    steps_lines.append(
        "   • [cyan]/map-learn[/] - Extract lessons from completed workflows"
    )

    steps_panel = Panel(
        "\n".join(steps_lines), title="Next Steps", border_style="cyan", padding=(1, 2)
    )
    console.print()
    console.print(steps_panel)


@app.command()
def check(debug: bool = typer.Option(False, "--debug", help="Enable debug logging")):
    """Check that all required tools are installed."""
    # Initialize workflow logger if debug mode is enabled
    if is_debug_enabled(debug):
        from mapify_cli.workflow_logger import MapWorkflowLogger

        workflow_logger = MapWorkflowLogger(Path.cwd(), enabled=True)
        log_file = workflow_logger.start_session(
            task_id=f"mapify_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        console.print(f"[dim]Debug logging enabled: {log_file}[/dim]")
        workflow_logger.log_event(
            "command_start", "mapify check", metadata={"debug": debug}
        )
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
        console.print(
            "[bold green]All tools are installed! MAP Framework is ready to use.[/bold green]"
        )
    else:
        console.print("[yellow]Some tools are missing:[/yellow]")
        if not results.get("git"):
            console.print("  • Install git: https://git-scm.com/downloads")
        if not results.get("claude"):
            console.print(
                "  • Install Claude Code: https://docs.anthropic.com/en/docs/claude-code/setup"
            )


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


# Playbook commands


@playbook_app.command("stats")
def playbook_stats():
    """Show playbook statistics"""
    from mapify_cli.playbook_manager import PlaybookManager

    playbook_db_path = Path.cwd() / ".claude" / "playbook.db"
    playbook_json_path = Path.cwd() / ".claude" / "playbook.json"

    # Check for playbook.db first (primary storage)
    if not playbook_db_path.exists():
        # Backward compatibility: check if old playbook.json exists
        if playbook_json_path.exists():
            console.print_json(
                data={
                    "error": "Found legacy playbook.json. Run 'mapify init' to migrate to playbook.db"
                }
            )
        else:
            console.print_json(
                data={"error": "Playbook not found. Initialize with 'mapify init'"}
            )
        raise typer.Exit(1)

    # Use PlaybookManager with db_path (SQLite backend)
    manager = PlaybookManager(db_path=str(playbook_db_path))
    total = sum(
        len(section["bullets"])
        for section in manager.playbook.get("sections", {}).values()
    )
    stats = {
        "total_bullets": total,
        "sections": len(manager.playbook.get("sections", {})),
        "metadata": manager.playbook.get("metadata", {}),
    }
    console.print_json(data=stats)


@playbook_app.command("search")
def playbook_search(query: str, top_k: int = typer.Option(5, help="Number of results")):
    """Search playbook for relevant patterns"""
    from mapify_cli.playbook_manager import PlaybookManager

    playbook_db_path = Path.cwd() / ".claude" / "playbook.db"
    if not playbook_db_path.exists():
        console.print("No patterns found (playbook not initialized)")
        return
    manager = PlaybookManager(db_path=str(playbook_db_path))
    results = manager.get_relevant_bullets(query, limit=top_k)
    if not results:
        console.print("No patterns found matching your query")
    else:
        console.print_json(
            data={
                "query": query,
                "count": len(results),
                "results": [
                    {
                        "id": b.get("id"),
                        "content": (b.get("content") or "")[:100] + "...",
                    }
                    for b in results
                ],
            }
        )


@playbook_app.command("sync")
def playbook_sync(threshold: int = typer.Option(5, help="Minimum helpful count")):
    """Show high-quality patterns ready for cross-project sync"""
    from mapify_cli.playbook_manager import PlaybookManager

    playbook_db_path = Path.cwd() / ".claude" / "playbook.db"
    playbook_json_path = Path.cwd() / ".claude" / "playbook.json"

    # Check for playbook.db first (primary storage)
    if not playbook_db_path.exists():
        # Backward compatibility: check if old playbook.json exists
        if playbook_json_path.exists():
            console.print_json(
                data={
                    "status": "error",
                    "message": "Found legacy playbook.json. Run 'mapify init' to migrate to playbook.db",
                }
            )
        else:
            console.print_json(
                data={
                    "status": "error",
                    "message": "Playbook not found. Initialize with 'mapify init'",
                }
            )
        raise typer.Exit(1)

    manager = PlaybookManager(db_path=str(playbook_db_path))
    patterns = manager.get_bullets_for_sync(threshold=threshold)
    console.print_json(
        data={
            "threshold": threshold,
            "count": len(patterns),
            "patterns": [
                {"id": p.get("id"), "helpful_count": p.get("helpful_count")}
                for p in patterns
            ],
        }
    )


@playbook_app.command("query")
def playbook_query(
    query_text: str = typer.Argument(..., help="Search query"),
    sections: List[str] = typer.Option(
        [], "--section", help="Filter by section (can specify multiple)"
    ),
    limit: int = typer.Option(5, "--limit", help="Maximum results to return"),
    mode: str = typer.Option(
        "local", "--mode", help="Search mode: local, cipher, or hybrid"
    ),
    format_output: str = typer.Option(
        "markdown", "--format", help="Output format: markdown or json"
    ),
    min_quality: int = typer.Option(
        0, "--min-quality", help="Minimum quality score (helpful - harmful)"
    ),
):
    """Query playbook using FTS5 full-text search with optional cipher integration

    Examples:
        mapify playbook query "JWT authentication" --limit 5
        mapify playbook query "error handling" --mode hybrid --limit 10
        mapify playbook query "API design" --section ARCHITECTURE_PATTERNS --section IMPLEMENTATION_PATTERNS
    """
    from mapify_cli.playbook_manager import PlaybookManager
    from mapify_cli.playbook_query import PlaybookQuery, SearchMode

    playbook_db_path = Path.cwd() / ".claude" / "playbook.db"
    playbook_json_path = Path.cwd() / ".claude" / "playbook.json"

    # Check for playbook.db first (primary storage)
    if not playbook_db_path.exists():
        # Backward compatibility: check if old playbook.json exists
        if playbook_json_path.exists():
            console.print(
                "[yellow]Warning:[/yellow] Found legacy playbook.json. Run 'mapify init' to migrate to playbook.db"
            )
        else:
            console.print(
                "[yellow]Warning:[/yellow] Playbook not found. Initialize with 'mapify init'"
            )
        raise typer.Exit(1)

    try:
        # Map mode string to SearchMode enum
        mode_map = {
            "local": SearchMode.PLAYBOOK_ONLY,
            "cipher": SearchMode.CIPHER_ONLY,
            "hybrid": SearchMode.HYBRID,
        }
        search_mode = mode_map.get(mode.lower(), SearchMode.PLAYBOOK_ONLY)

        # Create query
        query = PlaybookQuery(
            query=query_text,
            sections=list(sections) if sections else None,
            limit=limit,
            search_mode=search_mode,
            min_quality_score=min_quality,
        )

        # Execute query
        manager = PlaybookManager(db_path=str(playbook_db_path))
        response = manager.query(query)

        # Format output
        if format_output == "json":
            # JSON output
            results_json = {
                "query": query_text,
                "metadata": response.metadata,
                "results": [
                    {
                        "id": r.id,
                        "section": r.section,
                        "content": r.content,
                        "code_example": r.code_example,
                        "quality_score": r.quality_score,
                        "relevance_score": r.relevance_score,
                        "combined_score": r.combined_score,
                        "source": r.source,
                    }
                    for r in response.results
                ],
            }
            console.print_json(data=results_json)
        else:
            # Markdown output (default)
            if not response.results:
                console.print("[yellow]No results found[/yellow]")
                return

            console.print(f"# Query Results: {query_text}\n")
            console.print(
                f"**Found {len(response.results)} results in {response.metadata['total_time_ms']}ms**\n"
            )
            console.print(f"*Search method: {response.metadata['search_method']}*\n")

            for i, result in enumerate(response.results, 1):
                console.print(
                    f"## {i}. [{result.id}] Score: {result.combined_score:.2f}\n"
                )
                console.print(f"**Section:** {result.section}\n")
                console.print(
                    f"**Quality:** {result.quality_score} | **Relevance:** {result.relevance_score:.2f} | **Source:** {result.source}\n"
                )
                console.print(f"{result.content}\n")

                if result.code_example:
                    console.print("```")
                    console.print(result.code_example)
                    console.print("```\n")

                console.print("---\n")

    except ValueError as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {str(e)}")
        raise typer.Exit(1)


@playbook_app.command("apply-delta")
def playbook_apply_delta(
    input_file: Optional[Path] = typer.Argument(
        None, help="JSON file containing delta operations (or use stdin)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview changes without applying them"
    ),
):
    """Apply delta operations to playbook (ADD, UPDATE, DEPRECATE)

    Accepts JSON from file or stdin with structure:
    {
      "operations": [
        {
          "type": "ADD",
          "section": "IMPLEMENTATION_PATTERNS",
          "content": "Pattern description...",
          "code_example": "code here",
          "helpful_count": 1,
          "harmful_count": 0
        },
        {
          "type": "UPDATE",
          "bullet_id": "impl-0042",
          "increment_helpful": 1,
          "increment_harmful": 0
        },
        {
          "type": "DEPRECATE",
          "bullet_id": "impl-0099",
          "reason": "Superseded by impl-0105"
        }
      ]
    }

    Examples:
        mapify playbook apply-delta operations.json
        mapify playbook apply-delta operations.json --dry-run
        cat operations.json | mapify playbook apply-delta
        echo '{"operations": [{"type": "UPDATE", "bullet_id": "impl-0001", "increment_helpful": 1}]}' | mapify playbook apply-delta

    Exit codes:
        0 - Operations applied successfully (or dry-run preview completed)
        1 - Validation error or application failure
    """
    from mapify_cli.tools.validate_dependencies import load_input
    from mapify_cli.playbook_manager import PlaybookManager

    playbook_db_path = Path.cwd() / ".claude" / "playbook.db"
    playbook_json_path = Path.cwd() / ".claude" / "playbook.json"

    # Check for playbook.db first (primary storage)
    if not playbook_db_path.exists():
        # Backward compatibility: check if old playbook.json exists
        if playbook_json_path.exists():
            console.print(
                "[red]Error:[/red] Found legacy playbook.json. Run 'mapify init' to migrate to playbook.db"
            )
        else:
            console.print(
                "[red]Error:[/red] Playbook not found. Initialize with 'mapify init'"
            )
        raise typer.Exit(1)

    try:
        # Load input from file or stdin
        data = load_input(str(input_file) if input_file else None)

        # Validate structure
        if not isinstance(data, dict):
            raise ValueError("Input must be a JSON object")

        if "operations" not in data:
            raise ValueError("Missing required field: 'operations'")

        operations = data["operations"]
        if not isinstance(operations, list):
            raise ValueError("'operations' must be an array")

        # Validate each operation
        for i, op in enumerate(operations):
            if not isinstance(op, dict):
                raise ValueError(f"Operation {i} must be a JSON object")

            op_type = op.get("type")
            if not op_type:
                raise ValueError(f"Operation {i} missing required field: 'type'")

            if op_type not in ["ADD", "UPDATE", "DEPRECATE"]:
                raise ValueError(
                    f"Operation {i} has invalid type: {op_type} (must be ADD, UPDATE, or DEPRECATE)"
                )

            # Validate type-specific required fields
            if op_type == "ADD":
                required = ["section", "content"]
                missing = [f for f in required if f not in op]
                if missing:
                    raise ValueError(
                        f"ADD operation {i} missing required fields: {', '.join(missing)}"
                    )

            elif op_type == "UPDATE":
                if "bullet_id" not in op:
                    raise ValueError(
                        f"UPDATE operation {i} missing required field: 'bullet_id'"
                    )
                if "increment_helpful" not in op and "increment_harmful" not in op:
                    raise ValueError(
                        f"UPDATE operation {i} must specify at least one of: increment_helpful, increment_harmful"
                    )

            elif op_type == "DEPRECATE":
                required = ["bullet_id", "reason"]
                missing = [f for f in required if f not in op]
                if missing:
                    raise ValueError(
                        f"DEPRECATE operation {i} missing required fields: {', '.join(missing)}"
                    )

        # Dry-run mode: preview without applying
        if dry_run:
            # Count operations by type
            add_count = sum(1 for op in operations if op.get("type") == "ADD")
            update_count = sum(1 for op in operations if op.get("type") == "UPDATE")
            deprecate_count = sum(
                1 for op in operations if op.get("type") == "DEPRECATE"
            )

            console.print_json(
                data={
                    "status": "dry_run",
                    "message": "DRY RUN - No changes applied",
                    "would_apply": {
                        "total_operations": len(operations),
                        "add": add_count,
                        "update": update_count,
                        "deprecate": deprecate_count,
                    },
                    "operations": operations,
                }
            )
            return

        # Apply operations
        manager = PlaybookManager(db_path=str(playbook_db_path))
        summary = manager.apply_delta(operations)

        # Output JSON summary
        console.print_json(
            data={
                "status": "success",
                "message": "Delta operations applied successfully",
                "summary": summary,
            }
        )

    except ValueError as e:
        console.print_json(
            data={
                "status": "error",
                "error_type": "validation_error",
                "message": str(e),
            }
        )
        raise typer.Exit(1)
    except Exception as e:
        console.print_json(
            data={
                "status": "error",
                "error_type": "unexpected_error",
                "message": str(e),
            }
        )
        raise typer.Exit(1)


# Validate commands


@validate_app.command("graph")
def validate_graph(
    input_file: Optional[Path] = typer.Argument(
        None, help="JSON file to validate (or use stdin)"
    ),
    visualize: bool = typer.Option(
        False, "--visualize", help="Show ASCII dependency tree"
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    format: str = typer.Option(
        "json", "-f", "--format", help="Output format: json or text"
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail on warnings (e.g., orphaned tasks), not just critical errors (cycles, forward refs)",
    ),
):
    """Validate TaskDecomposer dependency graph

    Exit codes:
      0 - Valid graph (no critical errors; warnings allowed unless --strict)
      1 - Invalid graph (critical errors found, or warnings with --strict)
      2 - Malformed input (invalid JSON or missing required fields)
    """
    from mapify_cli.tools.validate_dependencies import (
        load_input,
        DependencyValidator,
        ASCIIGraphRenderer,
        print_report,
    )

    try:
        # Load input
        data = load_input(str(input_file) if input_file else None)

        # Validate
        validator = DependencyValidator(data)
        validator.validate_all()
        report = validator.get_report()

        # Print report
        print_report(report, format)

        # Display visualization if requested
        if visualize:
            console.print()  # Add blank line separator
            renderer = ASCIIGraphRenderer(validator)
            visualization = renderer.render(use_colors=not no_color)
            console.print(visualization)

        # Determine exit code based on issue severity
        has_critical = report.get("critical_issues", 0) > 0
        has_warnings = report.get("warnings", 0) > 0

        if has_critical:
            # Critical errors always fail
            raise typer.Exit(1)
        elif has_warnings and strict:
            # Warnings fail only in strict mode
            raise typer.Exit(1)
        # Otherwise exit 0 (success)

    except ValueError as e:
        # Input validation error (malformed JSON, missing fields)
        error_report = {
            "valid": False,
            "error": str(e),
            "error_type": "input_validation",
        }
        console.print_json(data=error_report)
        raise typer.Exit(2)


def main():
    app()


if __name__ == "__main__":
    main()
