"""CLI UI components for mapify.

Extracted from __init__.py to reduce module size.
Contains interactive selection widgets, progress tracking, and banner display.
"""

from typing import Any

import readchar
import typer
from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from typer.core import TyperGroup

# ASCII Art Banner
BANNER = """
╔╦╗╔═╗╔═╗  ╦╔═╦╔╦╗
║║║╠═╣╠═╝  ╠╩╗║ ║
╩ ╩╩ ╩╩    ╩ ╩╩ ╩
"""

TAGLINE = "Modular Agentic Planner — plan-then-build AI coding"
SUBTITLE = "/map-plan  →  /map-efficient  →  /map-check  →  /map-review  →  /map-learn"

console = Console()


class StepTracker:
    """Track and render hierarchical steps as a tree"""

    def __init__(self, title: str):
        self.title = title
        self.steps: list[dict[str, Any]] = (
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
            except Exception:  # noqa: BLE001, S110 -- deliberate fallback/resilience boundary, must not propagate
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
    default_key: str | None = None,
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
) -> list[str]:
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
    console.print(Align.center(Text(SUBTITLE, style="dim cyan")))
    console.print()
