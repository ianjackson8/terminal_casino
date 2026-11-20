'''
Achievements: trophies a profile earns once, checked after anything that moves money.

Each one is a test on the profile plus what just happened (an "event" dict). Unlocking logs a line
on the Casino Floor and shows on the Stats page's Trophies tab and on the leaderboard.

Author: Ian Jackson
'''

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class Achievement:
    id: str
    name: str
    desc: str
    test: Callable      # (profile, player, event) -> bool
    secret: bool = False


def _games_seen(profile) -> set:
    return {g.game for g in profile.games.values() if g.played}


def _event(kind: str):
    return lambda p, pl, e: e.get("kind") == kind


ALL: List[Achievement] = [
    # the tables
    Achievement("first_round", "Pull Up a Chair", "Play your first table",
                lambda p, pl, e: p.games_played >= 1),
    Achievement("regular", "Regular", "Play 50 tables",
                lambda p, pl, e: p.games_played >= 50),
    Achievement("night_owl", "Night Owl", "Play 25 tables in one visit",
                lambda p, pl, e: pl.total_sessions >= 25),
    Achievement("tourist", "Tourist", "Play 3 different games",
                lambda p, pl, e: len(_games_seen(p)) >= 3),
    Achievement("whole_floor", "Seen It All", "Play every game on the floor",
                lambda p, pl, e: e.get("all_games") and _games_seen(p) >= set(e["all_games"])),
    Achievement("high_roller", "High Roller", "Sit at a table with a $100+ minimum",
                lambda p, pl, e: e.get("kind") == "round" and e.get("min_bet", 0) >= 100),
    # money
    Achievement("big_score", "Big Score", "Win $1,000 at one table",
                lambda p, pl, e: e.get("kind") == "round" and e.get("delta", 0) >= 1000),
    Achievement("double_up", "Double Up", "Leave a table with twice what you sat down with ($50+)",
                lambda p, pl, e: e.get("kind") == "round" and e.get("before", 0) >= 50
                and p.balance >= 2 * e["before"]),
    Achievement("in_the_black", "In the Black", "Reach a lifetime net of +$1,000",
                lambda p, pl, e: p.net >= 1000),
    Achievement("rock_bottom", "Rock Bottom", "Lose every last chip",
                lambda p, pl, e: e.get("kind") == "round" and p.balance <= 0),
    Achievement("comeback", "Comeback Kid", "Hit $2,000 after borrowing from Vinnie",
                lambda p, pl, e: p.loans > 0 and p.balance >= 2000),
    # Vinnie
    Achievement("made_man", "Friend of the Family", "Take a loan from Vinnie", _event("loan")),
    Achievement("good_for_it", "Good for It", "Pay Vinnie back on time",
                lambda p, pl, e: e.get("kind") == "paid_off" and e.get("on_time")),
    Achievement("shaken_down", "Shaken Down", "Get a visit from Vinnie's boys", _event("collected"), secret=True),
    Achievement("in_deep", "In Deep", "Owe Vinnie $2,000",
                lambda p, pl, e: p.debt >= 2000, secret=True),
    # the bar
    Achievement("first_round_bar", "First Round's on Me", "Order a drink at the bar",
                lambda p, pl, e: p.drinks >= 1),
    Achievement("in_the_zone", "In the Zone", "Reach the luckiest buzz",
                lambda p, pl, e: e.get("kind") == "drink" and e.get("luck", 0) >= 3),
    Achievement("cut_off", "Cut Off", "Get cut off by the bartender",
                lambda p, pl, e: e.get("kind") == "drink" and e.get("cut_off"), secret=True),
]
BY_ID = {a.id: a for a in ALL}


def check(ui, player, **event) -> List[Achievement]:
    '''Test every locked achievement against the profile and this event; unlock and announce new ones.'''
    p = player.profile
    new = []
    for a in ALL:
        if a.id in p.achievements:
            continue
        try:
            hit = a.test(p, player, event)
        except (KeyError, TypeError, ValueError):
            hit = False
        if hit:
            p.achievements[a.id] = time.time()
            new.append(a)
    for a in new:
        ui.log(f"[bold gold1]★ Achievement:[/] [bold]{a.name}[/] [grey62]— {a.desc}[/]")
    if new:
        player.dirty = True
    return new


def progress(profile) -> str:
    return f"{len(profile.achievements)}/{len(ALL)}"
