'''
Developer compliance check for Terminal Casino games.

    python -m casino.check                    # every game in plugins/
    python -m casino.check ai_blackjack       # one installed game, by key
    python -m casino.check ~/code/my_game     # a game folder anywhere, before adding it
    python -m casino.check ~/code/MyGame --key my_game

Runs the same checks the casino runs at startup, plus slower warning-only ones, and prints a
verdict. Exit code is 1 if any game has errors (it would be blocked at startup), so it can
run in CI.

Author: Ian Jackson
'''

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from casino.compliance import ERROR, OK, WARN, Report, accepts_table, check_plugin, top_level_modules
from casino.tables import check_table_config

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"

ICONS = {OK: ("✔", "green"), WARN: ("⚠", "yellow"), ERROR: ("✖", "bold red")}

# Spec §8 items a script can't verify
MANUAL = [
    "Leave table returns to the lobby with the right balance, and the Stats page records it",
    "Opening the game twice in one session works (no leftover state)",
    "Ctrl-C mid-round returns to the lobby with a clean terminal",
    "A forced exception inside the game rolls the balance back",
    "The balance can never go negative; no money is created for the player",
    "All file reads and writes stay inside the game folder",
    "Usable at 80×24 and at ≥100 columns",
    "Footer lists every live key; Esc/Q leaves; ? shows the rules",
    "The game still runs on its own outside the casino",
]


def installed() -> List[Path]:
    if not PLUGINS_DIR.exists():
        return []
    return [d for d in sorted(PLUGINS_DIR.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_")) and (d / "plugin.py").exists()]


def modules_taken_by_others(key: str, path: Path) -> Dict[str, str]:
    '''Modules provided by the other installed games, for collision checks.'''
    taken: Dict[str, str] = {}
    for other in installed():
        if other.name == key or other.resolve() == path.resolve():
            continue
        for mod in top_level_modules(other):
            taken.setdefault(mod, other.name)
    return taken


def check_configured_tables(report: Report) -> None:
    '''Validate the casino's configured tables for this game. A bad table only stops that table opening.'''
    try:
        configured = json.loads((ROOT / "game_settings.json").read_text()).get("tables") or []
    except (OSError, ValueError):
        return
    mine = [c for c in configured if isinstance(c, dict) and c.get("game") == report.key]
    if not mine or report.module is None:
        return
    meta = report.meta
    plugin = SimpleNamespace(key=report.key, name=meta.get("name", report.key), version=meta.get("version", "?"),
                             rules=meta.get("rules") or {}, accepts_table=accepts_table(report.module.run))
    seen = {p.name for p in installed()} - {report.key}
    for cfg in mine:
        problems = check_table_config(cfg, plugin, seen)
        label = f"Table {cfg.get('id', '?')}"
        if problems:
            report.add(WARN, "§6", label, "won't open: " + "; ".join(problems))
        else:
            report.add(OK, "§6", label, f"{cfg['name']} opens")
        seen.add(cfg.get("id"))


def render(report: Report, console: Console) -> None:
    meta = report.meta
    title = Text(meta.get("name") or report.key, "bold")
    if meta.get("version"):
        title.append(f"  v{meta['version']}", "grey62")
    try:
        where = str(report.path.resolve().relative_to(ROOT))
    except ValueError:
        where = str(report.path.resolve()).replace(str(Path.home()), "~", 1)
    if len(where) > 40:
        where = "…" + where[-39:]
    title.append(f"   {where}", "grey50")

    table = Table(box=box.SIMPLE, show_header=True, header_style="bold gold1", pad_edge=False, expand=True)
    table.add_column("", width=1, no_wrap=True)
    table.add_column("Check", style="bold", no_wrap=True)
    table.add_column("Spec", style="grey50", no_wrap=True)
    table.add_column("Result", ratio=1)
    order = {ERROR: 0, WARN: 1, OK: 2}
    for f in sorted(report.findings, key=lambda f: order[f.level]):
        icon, style = ICONS[f.level]
        table.add_row(Text(icon, style), f.check, f.rule,
                      Text(f.message, "grey70" if f.level == OK else style.replace("bold ", "")))

    n_err, n_warn = len(report.errors), len(report.warnings)
    if n_err:
        verdict = Text(f"✖ Not compliant: {n_err} error{'s' if n_err != 1 else ''}"
                       f"{f', {n_warn} warning' + ('s' if n_warn != 1 else '') if n_warn else ''}. "
                       "The casino will not load this game.", "bold red")
        border = "red3"
    elif n_warn:
        verdict = Text(f"✔ Can be added, with {n_warn} warning{'s' if n_warn != 1 else ''} to look at.", "bold yellow")
        border = "yellow3"
    else:
        verdict = Text("✔ Ready to add. All automated checks pass.", "bold green")
        border = "green3"
    console.print(Panel(table, title=title, title_align="left", subtitle=verdict, subtitle_align="left",
                        border_style=border, box=box.ROUNDED))


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m casino.check",
                                     description="Check games against the Terminal Casino plugin spec.")
    parser.add_argument("targets", nargs="*", help="plugin keys or paths to game folders (default: all installed)")
    parser.add_argument("--key", help="the plugin key a single target folder will be installed as")
    args = parser.parse_args(argv)
    console = Console(highlight=False)

    targets = []
    for t in args.targets or [str(p) for p in installed()]:
        path = Path(t).expanduser()
        if not path.exists() and (PLUGINS_DIR / t).exists():
            path = PLUGINS_DIR / t
        targets.append(path)
    if not targets:
        console.print("No games found in plugins/. Pass a path to a game folder to check it.")
        return 0
    if args.key and len(targets) != 1:
        parser.error("--key only works with a single target")

    failed = 0
    for path in targets:
        key = args.key or path.resolve().name
        report = check_plugin(path, key=key, taken=modules_taken_by_others(key, path), deep=True)
        check_configured_tables(report)
        render(report, console)
        failed += not report.ok

    console.print(Text("  Also check by hand (spec §8.2):", "bold"))
    for item in MANUAL:
        console.print(f"  [grey50]☐[/] {escape(item)}")
    console.print()
    if len(targets) > 1:
        style = "bold red" if failed else "bold green"
        console.print(Text(f"  {len(targets) - failed}/{len(targets)} games compliant", style))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
