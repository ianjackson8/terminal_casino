'''
The leaderboard: every saved player ranked by lifetime net, shown on the welcome screen and in Stats.

Author: Ian Jackson
'''

from __future__ import annotations

from typing import List, Optional

from rich import box
from rich.table import Table
from rich.text import Text

from casino.tui import ago, esc, money, net_text

MEDALS = {1: ("1st", "bold gold1"), 2: ("2nd", "bold grey85"), 3: ("3rd", "bold dark_orange3")}


def ranked(profiles: List, current=None) -> List:
    '''Profiles best lifetime net first. `current` (the live profile) replaces its saved copy.'''
    if current is not None:
        profiles = [current] + [p for p in profiles if p.name.lower() != current.name.lower()]
    return sorted(profiles, key=lambda p: (-p.net, -p.games_played, p.name.lower()))


def table(profiles: List, current=None, limit: Optional[int] = None, wide: bool = True) -> Table:
    rows = ranked(profiles, current)
    t = Table(box=box.SIMPLE, header_style="bold gold1", pad_edge=False, padding=(0, 2))
    t.add_column("#", justify="right", no_wrap=True)
    t.add_column("Player", style="bold", no_wrap=True)
    t.add_column("Lifetime", justify="right", no_wrap=True)
    t.add_column("Balance", justify="right", no_wrap=True)
    if wide:
        t.add_column("Games", justify="right", style="grey62", no_wrap=True)
    t.add_column("Trophies", justify="right", no_wrap=True)
    if wide:
        t.add_column("Last seen", style="grey62", no_wrap=True)
    shown = rows[:limit] if limit else rows
    for i, p in enumerate(shown, 1):
        rank, style = MEDALS.get(i, (str(i), "grey62"))
        name = Text(esc(p.name), "bold")
        if current is not None and p is current:
            name.append("  ◀ you", "cyan")
        if p.loan:
            name.append("  owes Vinnie", "red")
        trophies = Text(f"★ {len(p.achievements)}", "gold1" if p.achievements else "grey42")
        cells = [Text(rank, style), name, net_text(p.net),
                 Text(money(p.balance), "green" if p.balance > 0 else "red")]
        if wide:
            cells.append(f"{p.games_played:,}")
        cells.append(trophies)
        if wide:
            cells.append(ago(p.last_played))
        t.add_row(*cells)
    if limit and len(rows) > limit:
        t.caption = f"{len(rows) - limit} more in Stats · Leaders"
        t.caption_style = "grey50"
    return t
