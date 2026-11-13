'''
Full-screen overlay pages: Stats (tabbed) and Settings (editor).

Both run their own key loop on top of the UI's overlay, like AI Blackjack's settings editor.

Author: Ian Jackson
'''

from __future__ import annotations

import copy
import time
from datetime import datetime
from typing import Optional, Sequence

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
    for name, g in sorted(p.games.items(), key=lambda kv: -kv[1].played):
        row = [esc(name), str(g.played), str(g.won), str(g.lost)]
        if wide:
            row.append(str(g.even))
        row += [pct(g.won, g.played), net_text(g.net)]
        if wide:
            row += [signed_money(g.best) if g.best > 0 else "—",
                    signed_money(g.worst) if g.worst < 0 else "—", duration(g.seconds)]
        t.add_row(*row)
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


def settings_page(ui, settings: dict, all_plugins: list, store, current: Optional[str]) -> bool:
    '''
    Edit a copy of the settings. Returns True (and updates `settings` in place) when saved.
    Profile deletions happen immediately (after a confirm), since they aren't settings.
    '''
    if not ui.interactive:
        ui.error("The settings page needs an interactive terminal — edit game_settings.json instead.")
        return False

    work = copy.deepcopy(settings)
    keys = [p.key for p in all_plugins]
    pref = work.get("enabled_plugins") or []
    order = sorted(keys, key=lambda k: pref.index(k) if k in pref else len(pref))
    disabled = set(work.get("disabled_plugins") or []) & set(keys)
    by_key = {p.key: p for p in all_plugins}
    cursor = 0
    profiles = store.all()

    def rows():
        items = [("field", f) for f in FIELDS]
        items += [("plugin", k) for k in order]
        items += [("profile", p) for p in profiles]
        return items

    def build(width, height):
        items = rows()
        lines = []      # (item index or None, section header)
        section = None
        for idx, (kind, _) in enumerate(items):
            new = {"field": "GENERAL", "plugin": "TABLES", "profile": "PROFILES"}[kind]
            if new != section:
                if section is not None:
                    lines.append((None, ""))
                lines.append((None, new))
                section = new
            lines.append((idx, None))
        for empty, title in (("plugin", "TABLES"), ("profile", "PROFILES")):
            if not any(k == empty for k, _ in items):
                lines += [(None, ""), (None, title), (None, "  none yet" if empty == "profile" else "  no games installed in plugins/")]
        room = max(3, height - 2)
        cur_line = next((i for i, (idx, _) in enumerate(lines) if idx == cursor), 0)
        start = max(0, min(cur_line - room // 2, len(lines) - room))
        window = lines[start:start + room]

        t = Table(box=None, show_header=False, expand=True, pad_edge=False, padding=(0, 1))
        t.add_column(width=2, no_wrap=True)
        t.add_column(style="bold", no_wrap=True, min_width=20)
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
            elif kind == "plugin":
                p = by_key[item]
                desc = f"v{p.version} · min bet {money(p.min_bet)} · {p.description}"
                t.add_row(pointer, esc(p.name), _fmt("bool", item not in disabled), desc, style=style)
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
        ("x", "delete", "Delete profile"),
        ("s", "save", "Save"),
        (("esc", "q"), "cancel", "Cancel"),
    ]

    def apply():
        # keep disabled entries for plugins that aren't installed right now
        others = [k for k in settings.get("disabled_plugins") or [] if k not in keys]
        work["disabled_plugins"] = others + [k for k in order if k in disabled]

    def changed():
        apply()
        return work != settings

    try:
        while True:
            items = rows()
            cursor = max(0, min(cursor, len(items) - 1))
            ui.set_overlay("Settings  ·  game_settings.json", _Sized(build))
            action = ui.choose("[bold]Settings[/]", options)
            kind, item = items[cursor]

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
            elif action == "edit" and kind == "plugin":
                if item not in disabled and len(disabled) == len(keys) - 1:
                    ui.error("At least one table has to stay open.")
                else:
                    disabled.symmetric_difference_update({item})
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
                ui.error("Select a profile first.")
            elif action == "edit" and kind == "profile":
                ui.error("Press X to delete a profile.")
    finally:
        ui.clear_overlay()
