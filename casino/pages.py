'''
Full-screen overlay pages: Stats (tabbed) and Settings (editor).

Both run their own key loop on top of the UI's overlay, like AI Blackjack's settings editor.

Author: Ian Jackson
'''

from __future__ import annotations

import copy
import re
import time
from datetime import datetime
from typing import Optional, Sequence

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from casino.profiles import GameStats
from casino.tui import ago, esc, money, net_text, signed_money, sparkline


#== Formatting helpers ==#

def duration(secs: float) -> str:
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.0f}%" if whole else "—"


BLOCKS = " ▁▂▃▄▅▆▇█"


def balance_chart(values: Sequence[float], width: int, height: int) -> Text:
    '''
    Multi-row block chart of balance over time, with a y-axis. Bars are green at or above the
    first value, red below. Long series are downsampled to fit the width.
    '''
    if len(values) < 2 or width < 12 or height < 2:
        return Text("Play a few games to see your balance chart.", "grey50 italic")
    label_w = max(len(money(max(values))), len(money(min(values)))) + 1
    plot_w = width - label_w - 1
    if len(values) > plot_w:   # downsample, always keeping the latest value
        step = len(values) / plot_w
        values = [values[min(len(values) - 1, int(i * step))] for i in range(plot_w - 1)] + [values[-1]]
    elif len(values) * 2 <= plot_w:   # stretch short series so the chart fills the panel
        k = plot_w // len(values)
        values = [v for v in values for _ in range(k)]
    start, lo, hi = values[0], min(values), max(values)
    span = (hi - lo) or 1
    levels = height * 8
    heights = [max(1, round((v - lo) / span * levels)) for v in values]
    lines = []
    for row in range(height):            # top row first
        floor = (height - 1 - row) * 8
        if row == 0:
            label = money(hi)
        elif row == height - 1:
            label = money(lo)
        else:
            label = ""
        line = Text(f"{label:>{label_w}}", "grey50")
        line.append("┤" if label else "│", "grey42")
        for v, h in zip(values, heights):
            cell = min(8, max(0, h - floor))
            line.append(BLOCKS[cell], "green" if v >= start else "red")
        lines.append(line)
    axis = Text(" " * label_w + "└" + "─" * len(values), "grey42")
    lines.append(axis)
    return Text("\n").join(lines)


class _Sized:
    '''Builds its renderable at render time, once the available width and height are known.'''

    fill = True   # take the overlay's full height

    def __init__(self, build):
        self.build = build

    def __rich_console__(self, console, options):
        yield self.build(options.max_width, options.height or console.height)


def _tabs(names: Sequence[str], current: int) -> Text:
    line = Text()
    for i, name in enumerate(names):
        if i:
            line.append("  ")
        line.append(f" {name} ", "bold black on gold1" if i == current else "grey62 on grey23")
    line.append("     ←/→ or Tab to switch", "grey42")
    return line


#== Stats page ==#

STAT_TABS = ("Overview", "Games", "History")


def _kv(rows) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="grey62", no_wrap=True)
    t.add_column(justify="right", no_wrap=True)
    for k, v in rows:
        t.add_row(k, v if isinstance(v, Text) else Text(str(v), "bold"))
    return t


def _overview(player, width: int, height: int):
    p = player.profile
    lifetime = _kv([
        ("Balance", Text(money(p.balance), "bold green" if p.balance > 0 else "bold red")),
        ("Bought in", money(p.bought_in)),
        ("Rebuys", Text(str(p.rebuys), "magenta" if p.rebuys else "grey50")),
        ("Net", net_text(p.net)),
        ("Games", f"{p.games_played:,}"),
        ("Win rate", pct(sum(g.won for g in p.games.values()), p.games_played)),
        ("Time played", duration(p.seconds_played)),
        ("Visits", f"{p.sessions}"),
        ("Since", datetime.fromtimestamp(p.created).strftime("%b %d, %Y")),
    ])
    session = _kv([
        ("Started with", money(player.starting_balance)),
        ("Now", Text(money(player.balance), "bold")),
        ("Net", net_text(player.net)),
        ("Games", str(player.total_sessions)),
        ("Time here", duration(time.time() - player.started)),
    ])
    best_game = max(p.games.items(), key=lambda kv: kv[1].net, default=None)
    if best_game and best_game[1].net > 0:
        session.add_row("", "")
        session.add_row("Best table", Text(f"{best_game[0]} {signed_money(best_game[1].net)}", "bold green"))

    top = Table.grid(expand=True, padding=(0, 4))
    top.add_column(ratio=1)
    top.add_column(ratio=1)
    top.add_row(Panel(lifetime, title="[bold gold1]Lifetime[/]", border_style="grey42", box=box.ROUNDED),
                Panel(session, title="[bold gold1]This visit[/]", border_style="grey42", box=box.ROUNDED))
    chart_h = max(2, height - 11 - 4 - 3)     # tabs + kv panels + chart frame
    chart = balance_chart(p.balance_series(), width - 4, min(chart_h, 12))
    return Group(top, Panel(chart, title="[bold gold1]Balance[/]", border_style="grey42", box=box.ROUNDED))


def _games(player, width: int, height: int):
    p = player.profile
    if not p.games:
        return Text("No games played yet.", "grey50 italic")
    wide = width >= 90
    t = Table(box=box.SIMPLE_HEAVY, header_style="bold gold1", expand=True, pad_edge=False)
    t.add_column("Table", style="bold", no_wrap=True, ratio=2)
    t.add_column("Played", justify="right")
    t.add_column("W", justify="right", style="green")
    t.add_column("L", justify="right", style="red")
    if wide:
        t.add_column("Even", justify="right", style="grey62")
    t.add_column("Win %", justify="right")
    t.add_column("Net", justify="right", no_wrap=True)
    if wide:
        t.add_column("Best", justify="right", style="green", no_wrap=True)
        t.add_column("Worst", justify="right", style="red", no_wrap=True)
        t.add_column("Time", justify="right", style="grey70", no_wrap=True)
    def add(label, g, style=""):
        row = [label, str(g.played), str(g.won), str(g.lost)]
        if wide:
            row.append(str(g.even))
        row += [pct(g.won, g.played), net_text(g.net)]
        if wide:
            row += [signed_money(g.best) if g.best > 0 else "—",
                    signed_money(g.worst) if g.worst < 0 else "—", duration(g.seconds)]
        t.add_row(*row, style=style)

    groups = {}
    for label, g in p.games.items():
        groups.setdefault(g.game or label, []).append((label, g))
    for game, rows in sorted(groups.items(), key=lambda kv: -sum(g.played for _, g in kv[1])):
        rows.sort(key=lambda kv: -kv[1].played)
        if len(rows) == 1:
            add(esc(rows[0][0]), rows[0][1])
            continue
        total = GameStats(game=game)
        for _, g in rows:
            total.played += g.played; total.won += g.won; total.lost += g.lost; total.even += g.even
            total.net += g.net; total.seconds += g.seconds
            total.best = max(total.best, g.best); total.worst = min(total.worst, g.worst)
        add(Text(game, "bold"), total)
        for label, g in rows:
            short = label[len(game) + 3:] if label.startswith(game + " · ") else label
            add(Text("  " + short, "grey85"), g)
    return t


def _history(player, width: int, height: int):
    p = player.profile
    if not p.history:
        return Text("Nothing here yet.", "grey50 italic")
    room = max(1, height - 4)
    t = Table(box=None, show_header=True, header_style="bold gold1", expand=True, pad_edge=False, padding=(0, 2))
    t.add_column("When", style="grey62", no_wrap=True)
    t.add_column("Table", style="bold", no_wrap=True, ratio=1)
    t.add_column("Result", justify="right", no_wrap=True)
    t.add_column("Balance", justify="right", no_wrap=True)
    t.add_column("", no_wrap=True)
    recent = p.history[-room:][::-1]
    series = [h["balance"] for h in p.history[-30:]]
    for i, h in enumerate(recent):
        is_rebuy = h["game"] == "Rebuy"
        result = Text(f"+{money(h['delta'])} chips", "magenta") if is_rebuy else net_text(h["delta"])
        when = datetime.fromtimestamp(h["t"]).strftime("%b %d %H:%M")
        t.add_row(when, esc(h["game"]), result, money(h["balance"]),
                  sparkline(series, 30) if i == 0 and width >= 90 else "")
    if len(p.history) > room:
        t.add_row("", Text(f"… {len(p.history) - room} older", "grey50"), "", "", "")
    return t


def stats_page(ui, player) -> None:
    if not ui.interactive:
        ui.show_info(f"Stats — {player.name}", _overview(player, 80, 30))
        return
    tab = 0
    views = (_overview, _games, _history)

    def build(width, height):
        body = views[tab](player, width, height - 2)
        return Group(_tabs(STAT_TABS, tab), Text(""), body)

    options = ([(("left", "h"), "prev", ""), (("right", "l", "tab"), "next", "Switch tab")]
               + [(str(i + 1), f"t{i}", None) for i in range(len(STAT_TABS))]      # hidden: jump to tab
               + [(("esc", "q", "s", "enter"), "back", "Back to lobby")])
    try:
        while True:
            ui.set_overlay(f"Stats  ·  {esc(player.name)}", _Sized(build))
            action = ui.choose("[bold]Stats[/]", options)
            if action == "back":
                return
            if action == "prev":
                tab = (tab - 1) % len(STAT_TABS)
            elif action == "next":
                tab = (tab + 1) % len(STAT_TABS)
            elif action.startswith("t"):
                tab = int(action[1:])
    finally:
        ui.clear_overlay()


#== Settings page ==#

FIELDS = [
    {"key": "init_balance", "label": "Starting balance", "kind": "money", "min": 1,
     "desc": "Buy-in for new profiles, and the amount of each rebuy"},
    {"key": "autosave", "label": "Autosave", "kind": "bool",
     "desc": "Save your profile after every game"},
    {"key": "allow_rebuy", "label": "Allow rebuys", "kind": "bool",
     "desc": "Offer a rebuy when you can't afford any table"},
]


def _fmt(kind: str, value) -> Text:
    if kind == "bool":
        return Text("● on", "bold green3") if value else Text("○ off", "grey50")
    if kind == "money":
        return Text(money(value), "bold")
    return Text(str(value), "bold")


def _parse_money(raw: str, minimum) -> float:
    try:
        value = float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        raise ValueError("Enter an amount, e.g. 250.")
    if minimum is not None and value < minimum:
        raise ValueError(f"Must be at least {money(minimum)}.")
    return int(value) if value.is_integer() else round(value, 2)


def _unique_id(base: str, taken: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "table"
    if not base[0].isalpha():
        base = "t_" + base
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}_{n}", n + 1
    return tid


def _ask_number(ui, prompt: str, current, minimum=None, allow_blank=False, kind="money"):
    '''Ask for a number until it's valid. Returns None for blank when allow_blank.'''
    default = "" if current is None else f"{current:g}"
    while True:
        raw = ui.ask(prompt + (" ([grey62]blank = no limit[/])" if allow_blank else ""), default=default).strip()
        if allow_blank and raw in ("", "-", "none"):
            return None
        try:
            if kind == "int":
                value = int(raw)
                if minimum is not None and value < minimum:
                    raise ValueError(f"Must be at least {minimum}.")
                return value
            return _parse_money(raw, minimum) if kind == "money" else float(raw)
        except ValueError as e:
            ui.error(str(e) if str(e).startswith("Must") or str(e).startswith("Enter") else "Enter a number.")


def edit_table(ui, cfg: dict, plugin) -> None:
    '''Edit one table config in place: name, stakes, and every rule the game declares.'''
    from casino.tables import check_rule_value
    schema = plugin.rules or {}
    cursor = 0
    rows = ["name", "min_bet", "max_bet"] + [("rule", k) for k in schema]

    def value_text(row) -> Text:
        if row == "name":
            return Text(cfg["name"], "bold")
        if row == "min_bet":
            return Text(money(cfg["min_bet"]), "bold")
        if row == "max_bet":
            return Text("no limit", "grey62") if cfg.get("max_bet") is None else Text(money(cfg["max_bet"]), "bold")
        spec = schema[row[1]]
        overridden = row[1] in cfg.get("rules", {})
        value = cfg.get("rules", {}).get(row[1], spec["default"])
        if spec["type"] == "bool":
            text = _fmt("bool", value)
        else:
            text = Text(str(value), "bold")
        if not overridden:
            text.append("  default", "grey50")
        return text

    def build(width, height):
        t = Table(box=None, show_header=False, expand=True, pad_edge=False, padding=(0, 1))
        t.add_column(width=2, no_wrap=True)
        t.add_column(style="bold", no_wrap=True, min_width=22)
        t.add_column(no_wrap=True, min_width=16)
        t.add_column(style="grey58", ratio=1, no_wrap=True, overflow="ellipsis")
        t.add_row("", Text("TABLE", "bold gold1"), "", "")
        labels = {"name": ("Name", "Shown in the lobby"), "min_bet": ("Minimum bet", "Players need at least this to sit down"),
                  "max_bet": ("Maximum bet", "The game won't take bets above this")}
        for i, row in enumerate(rows):
            if i == 3:
                t.add_row("", "", "", "")
                t.add_row("", Text(f"RULES  ·  {plugin.name}", "bold gold1"), "", "")
            selected = i == cursor
            if isinstance(row, tuple):
                spec = schema[row[1]]
                label, desc = spec["label"], spec.get("description", "")
                if spec["type"] == "choice":
                    desc = desc or " / ".join(map(str, spec["choices"]))
                elif "min" in spec or "max" in spec:
                    desc = desc or f"{spec.get('min', '…')} to {spec.get('max', '…')}"
            else:
                label, desc = labels[row]
            t.add_row(Text("▶", "bold gold1") if selected else "", label, value_text(row), desc,
                      style="on grey23" if selected else "")
        if not schema:
            t.add_row("", "", "", "")
            t.add_row("", Text(f"{plugin.name} v{plugin.version} doesn't declare any table rules", "grey50 italic"), "", "")
        return t

    options = [(("up", "k"), "up", ""), (("down", "j"), "down", "Move"), (("enter", " "), "edit", "Change"),
               ("r", "reset", "Reset to default"), (("esc", "q", "d"), "done", "Done")]
    while True:
        ui.set_overlay(f"Settings  ·  {esc(plugin.name)} table", _Sized(build))
        action = ui.choose(f"[bold]{esc(cfg['name'])}[/]", options)
        row = rows[cursor]
        if action == "done":
            return
        if action == "up":
            cursor = (cursor - 1) % len(rows)
        elif action == "down":
            cursor = (cursor + 1) % len(rows)
        elif action == "reset":
            if isinstance(row, tuple):
                cfg.setdefault("rules", {}).pop(row[1], None)
            elif row == "max_bet":
                cfg["max_bet"] = None
            else:
                ui.error("Only rules and the maximum bet have a default.")
        elif row == "name":
            name = ui.ask("[bold]Table name[/]", default=cfg["name"]).strip()
            if not name or len(name) > 24:
                ui.error("Use 1–24 characters.")
            else:
                cfg["name"] = name
        elif row == "min_bet":
            value = _ask_number(ui, "[bold]Minimum bet[/]", cfg["min_bet"], minimum=0)
            if cfg.get("max_bet") is not None and value > cfg["max_bet"]:
                ui.error(f"Must be at most the maximum bet ({money(cfg['max_bet'])}).")
            else:
                cfg["min_bet"] = value
        elif row == "max_bet":
            cfg["max_bet"] = _ask_number(ui, "[bold]Maximum bet[/]", cfg.get("max_bet"),
                                         minimum=cfg["min_bet"], allow_blank=True)
        else:
            name = row[1]
            spec = schema[name]
            rules = cfg.setdefault("rules", {})
            current = rules.get(name, spec["default"])
            if spec["type"] == "bool":
                value = not current
            elif spec["type"] == "choice":
                choices = spec["choices"]
                value = choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]
            else:
                while True:
                    value = _ask_number(ui, f"[bold]{esc(spec['label'])}[/]", current, kind=spec["type"])
                    why = check_rule_value(spec, value)
                    if not why:
                        break
                    ui.error(f"{spec['label']} {why}.")
            if value == spec["default"]:
                rules.pop(name, None)
            else:
                rules[name] = value


def settings_page(ui, settings: dict, all_plugins: list, store, current: Optional[str]) -> bool:
    '''
    Edit a copy of the settings. Returns True (and updates `settings` in place) when saved.
    Profile deletions happen immediately (after a confirm), since they aren't settings.
    '''
    from casino.tables import bet_range, build_tables, rules_summary
    if not ui.interactive:
        ui.error("The settings page needs an interactive terminal — edit game_settings.json instead.")
        return False

    work = copy.deepcopy(settings)
    work.pop("disabled_plugins", None)          # replaced by disabled_tables
    work.setdefault("tables", [])
    disabled = set(work.get("disabled_tables") or [])
    cursor = 0
    profiles = store.all()

    def tables():
        return build_tables(all_plugins, work)

    def rows():
        items = [("field", f) for f in FIELDS]
        by_game = {}
        for t in tables():
            by_game.setdefault(t.plugin.key, []).append(t)
        for plugin in all_plugins:
            items.append(("game", plugin))
            items += [("table", t) for t in by_game.get(plugin.key, [])]
        items += [("profile", p) for p in profiles]
        return items

    def build(width, height):
        items = rows()
        lines = []      # (item index or None, section header)
        section = None
        for idx, (kind, _) in enumerate(items):
            new = {"field": "GENERAL", "game": "TABLES", "table": "TABLES", "profile": "PROFILES"}[kind]
            if new != section:
                if section is not None:
                    lines.append((None, ""))
                lines.append((None, new))
                section = new
            lines.append((idx, None))
        for empty, title, msg in (("game", "TABLES", "  no games installed in plugins/"), ("profile", "PROFILES", "  none yet")):
            if not any(k == empty for k, _ in items):
                lines += [(None, ""), (None, title), (None, msg)]
        room = max(3, height - 2)
        cur_line = next((i for i, (idx, _) in enumerate(lines) if idx == cursor), 0)
        start = max(0, min(cur_line - room // 2, len(lines) - room))
        window = lines[start:start + room]

        t = Table(box=None, show_header=False, expand=True, pad_edge=False, padding=(0, 1))
        t.add_column(width=2, no_wrap=True)
        t.add_column(style="bold", no_wrap=True, min_width=22)
        t.add_column(no_wrap=True, min_width=12)
        t.add_column(style="grey58", ratio=1, no_wrap=True, overflow="ellipsis")
        if start > 0:
            t.add_row("", Text("▲ more", "grey50"), "", "")
        for idx, header in window:
            if idx is None:
                style = "grey50 italic" if header.startswith("  ") else "bold gold1"
                t.add_row("", Text(header, style), "", "")
                continue
            kind, item = items[idx]
            selected = idx == cursor
            pointer = Text("▶", "bold gold1") if selected else Text("")
            style = "on grey23" if selected else ""
            if kind == "field":
                t.add_row(pointer, item["label"], _fmt(item["kind"], work.get(item["key"])), item["desc"], style=style)
            elif kind == "game":
                name = Text(item.name, "bold white")
                name.append(f" v{item.version}", "grey50")
                if item.accepts_table:
                    hint = "A to add a table" if selected else f"{len(item.rules)} table rule(s)"
                else:
                    hint = "single table: this version can't take table settings"
                t.add_row(pointer, name, "", hint, style=style)
            elif kind == "table":
                desc = bet_range(item, money)
                summary = rules_summary(item)
                if summary:
                    desc += " · " + summary
                if selected and item.plugin.accepts_table:
                    desc = "E edit · D duplicate · X delete · " + desc
                t.add_row(pointer, Text("  " + item.name), _fmt("bool", item.id not in disabled), desc, style=style)
            else:
                you = item.name.lower() == (current or "").lower()
                hint = "playing now" if you else ("X to delete" if selected else f"last seen {ago(item.last_played)}")
                t.add_row(pointer, esc(item.name), Text(money(item.balance), "bold green"),
                          f"{item.games_played} games · net {signed_money(item.net)} · {hint}", style=style)
        if start + room < len(lines):
            t.add_row("", Text("▼ more", "grey50"), "", "")
        return t

    options = [
        (("up", "k"), "up", ""),
        (("down", "j"), "down", "Move"),
        (("enter", " "), "edit", "Change"),
        ("a", "add", None), ("e", "edit_table", None), ("d", "duplicate", None),   # shown in the row hints
        ("x", "delete", "Delete"),
        ("s", "save", "Save"),
        (("esc", "q"), "cancel", "Cancel"),
    ]

    def all_ids() -> set:
        return {c.get("id") for c in work["tables"]} | {p.key for p in all_plugins}

    def materialize(table) -> dict:
        '''A game's default table becomes a real config entry once it gets siblings.'''
        if not table.is_default:
            return next(c for c in work["tables"] if c.get("id") == table.id)
        cfg = {"id": table.plugin.key, "game": table.plugin.key, "name": "Standard",
               "min_bet": table.min_bet, "max_bet": None, "rules": {}}
        work["tables"].append(cfg)
        return cfg

    def add_table(plugin, source=None):
        if not plugin.accepts_table:
            ui.error(f"{plugin.name} v{plugin.version} can't take table settings, so it only has one table.")
            return None
        siblings = [t for t in tables() if t.plugin is plugin]
        if len(siblings) == 1 and siblings[0].is_default:
            materialize(siblings[0])       # keep the game's original table alongside the new one
        if source is None:
            source = {"name": "New table", "min_bet": plugin.min_bet, "max_bet": None, "rules": {}}
        name = (source["name"] + " copy")[:24] if source.get("id") else source["name"]
        cfg = {"id": _unique_id(f"{plugin.key}_{name}", all_ids()), "game": plugin.key, "name": name,
               "min_bet": source["min_bet"], "max_bet": source.get("max_bet"), "rules": dict(source.get("rules") or {})}
        work["tables"].append(cfg)
        edit_table(ui, cfg, plugin)
        return cfg

    def apply():
        valid = {t.id for t in tables()}
        # keep entries for tables whose game isn't installed right now
        others = [i for i in settings.get("disabled_tables") or [] if i not in valid and i not in disabled]
        work["disabled_tables"] = others + sorted(i for i in disabled if i in valid)

    def changed():
        apply()
        return work != settings

    def select(table_id):
        nonlocal cursor
        cursor = next((i for i, (k, it) in enumerate(rows()) if k == "table" and it.id == table_id), cursor)

    try:
        while True:
            items = rows()
            cursor = max(0, min(cursor, len(items) - 1))
            ui.set_overlay("Settings  ·  game_settings.json", _Sized(build))
            action = ui.choose("[bold]Settings[/]", options)
            kind, item = items[cursor]
            plugin = item if kind == "game" else (item.plugin if kind == "table" else None)

            if action == "up":
                cursor = (cursor - 1) % len(items)
            elif action == "down":
                cursor = (cursor + 1) % len(items)
            elif action == "save":
                apply()
                settings.clear()
                settings.update(work)
                return True
            elif action == "cancel":
                if changed():
                    if ui.choose("Discard your changes?", [("y", "y", "Discard"), ("n", "n", "Keep editing")]) != "y":
                        continue
                return False
            elif action == "edit" and kind == "field":
                if item["kind"] == "bool":
                    work[item["key"]] = not work.get(item["key"])
                    continue
                while True:
                    raw = ui.ask(f"[bold]{item['label']}[/]", default=f"{work.get(item['key'], 0):g}")
                    try:
                        work[item["key"]] = _parse_money(raw, item.get("min"))
                        break
                    except ValueError as e:
                        ui.error(str(e))
            elif action == "edit" and kind == "table":
                open_count = sum(1 for t in tables() if t.id not in disabled)
                if item.id not in disabled and open_count == 1:
                    ui.error("At least one table has to stay open.")
                else:
                    disabled.symmetric_difference_update({item.id})
            elif action in ("add", "edit") and kind == "game":
                cfg = add_table(item)
                if cfg:
                    select(cfg["id"])
            elif action == "add" and plugin is not None:
                cfg = add_table(plugin)
                if cfg:
                    select(cfg["id"])
            elif action == "duplicate" and kind == "table":
                if not plugin.accepts_table:
                    ui.error(f"{plugin.name} v{plugin.version} can't take table settings, so it only has one table.")
                    continue
                cfg = add_table(plugin, source=materialize(item))
                if cfg:
                    select(cfg["id"])
            elif action == "edit_table" and kind == "table":
                if not plugin.accepts_table:
                    ui.error(f"{plugin.name} v{plugin.version} can't take table settings.")
                    continue
                edit_table(ui, materialize(item), plugin)
            elif action == "delete" and kind == "table":
                if item.is_default:
                    ui.error("A game's only table can't be deleted. Switch it off with ↵ instead.")
                    continue
                if ui.choose(f"Delete the {esc(item.label)} table?", [("y", "y", "Delete"), ("n", "n", "Keep")]) == "y":
                    work["tables"] = [c for c in work["tables"] if c.get("id") != item.id]
                    disabled.discard(item.id)
                    remaining = [c for c in work["tables"] if c.get("game") == plugin.key]
                    # a lone leftover "Standard" table goes back to being the game's default
                    if len(remaining) == 1 and remaining[0].get("id") == plugin.key and not remaining[0].get("rules") \
                            and remaining[0].get("max_bet") is None and remaining[0]["min_bet"] == plugin.min_bet:
                        work["tables"].remove(remaining[0])
            elif action == "delete" and kind == "profile":
                if item.name.lower() == (current or "").lower():
                    ui.error("You can't delete the profile you're playing on.")
                    continue
                if ui.choose(f"Delete {esc(item.name)}'s profile ({money(item.balance)}, {item.games_played} games)? This can't be undone.",
                             [("y", "y", "Delete"), ("n", "n", "Keep")]) == "y":
                    store.delete(item.name)
                    ui.log(f"Deleted profile [bold]{esc(item.name)}[/]")
                    profiles = store.all()
            elif action == "delete":
                ui.error("Select a table or a profile to delete.")
            elif action in ("duplicate", "edit_table"):
                ui.error("Select a table first.")
            elif action == "edit" and kind == "profile":
                ui.error("Press X to delete a profile.")
    finally:
        ui.clear_overlay()
