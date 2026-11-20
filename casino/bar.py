'''
The bar. Buy a drink, loosen up, and maybe your luck turns. Overdo it and it turns the other way.

Luck lives on the casino side: games keep their own odds. After each table visit, a lucky player
may catch a small "hot streak" bonus on a win; a drunk one may fumble some chips. Drinks wear off
a step per round (a round is one table visit), and the bartender keeps it from getting silly:

- at most two drinks between rounds;
- cut off from the strong stuff once you're drunk;
- the bonuses are small and capped, so on average a drink costs more than the luck it buys.

Author: Ian Jackson
'''

from __future__ import annotations

import random

from rich.align import Align
from rich.console import Group
from rich.table import Table
from rich.text import Text

from casino.tui import money

BARTENDER = "Lou"

# key, name, price, buzz, line
DRINKS = [
    ("1", "Soda", 2, -1, "Calms you down a step"),
    ("2", "Beer", 6, 1, "Takes the edge off"),
    ("3", "Martini", 15, 2, "Shaken, with nerve"),
    ("4", "Whiskey", 30, 3, "Top shelf. Careful."),
]
MAX_BUZZ = 8
CUT_OFF = 6             # at this buzz Lou only pours soda
PER_ROUND = 2           # drinks between rounds

# buzz -> luck
LUCK = [0, 1, 2, 3, 3, 1, -1, -3, -5]
CHANCE = 0.10           # per point of luck, that it kicks in after a round
SHARE = 0.10            # of the round's win or loss
BONUS_CAP = 25.0
FUMBLE_CAP = 50.0

MOODS = ["Sober", "Relaxed", "Loose", "In the zone", "In the zone", "Tipsy", "Drunk", "Hammered", "Seeing double"]


def luck(profile) -> int:
    return LUCK[max(0, min(profile.buzz, MAX_BUZZ))]


def mood(profile) -> str:
    return MOODS[max(0, min(profile.buzz, MAX_BUZZ))]


def luck_text(profile) -> Text:
    n = luck(profile)
    style = "bold green" if n > 0 else "bold red" if n < 0 else "grey62"
    return Text.assemble((f"{n:+d}" if n else "0", style), (f"  {mood(profile)}", "grey62"))


def meter(profile) -> Text:
    t = Text()
    for i in range(1, MAX_BUZZ + 1):
        style = "green" if LUCK[i] > 0 else "red"
        t.append("▮" if i <= profile.buzz else "▯", style if i <= profile.buzz else "grey35")
    return t


#== Lou ==#

def portrait() -> Text:
    art = Text(no_wrap=True)
    rows = [
        [("      ▄▄▄▄▄▄▄▄     ", "grey50")],
        [("     ▐", "grey50"), ("╭──────╮", "wheat1"), ("▌    ", "grey50")],
        [("      ", ""), ("│ ●  ● │", "wheat1"), ("     ", "")],
        [("      ", ""), ("│  ╹   │", "wheat1"), ("     ", "")],
        [("      ", ""), ("│ ╰──╯ │", "wheat1"), ("     ", "")],
        [("      ", ""), ("╰─╮  ╭─╯", "wheat1"), ("     ", "")],
        [("   ▗▄▄▄", "grey85"), ("◆▶◀◆", "red3"), ("▄▄▄▖   ", "grey85")],
        [("  ▐▌", "grey85"), ("███▐▌███", "dark_red"), ("▐▌▐▌  ", "grey85")],
        [("▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀", "dark_orange3")],
        [("  ▕▏  ", "grey50"), ("Y", "bold cyan"), ("  ", ""), ("U", "bold gold1"), ("  ", ""),
         ("▯", "bold orange3"), ("    ▕▏  ", "grey50")],
    ]
    for row in rows:
        for chunk, style in row:
            art.append(chunk, style)
        art.append("\n")
    art.rstrip()
    return art


GREET = [
    "What'll it be?",
    "Pull up a stool. What are we drinkin'?",
    "Rough table? Good table? Either way, I pour.",
]
CUT = [
    "That's enough for you, friend. Soda's on the menu. Nothin' else.",
    "I'm cuttin' you off. Go play a few hands and come back.",
]
SLOW = [
    "Easy. Two's the limit between rounds. Go play, then come back.",
    "Pace yourself. Win a hand first.",
]


def _menu(profile, ordered: int) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(no_wrap=True)
    t.add_column(style="bold", no_wrap=True)
    t.add_column(justify="right", no_wrap=True)
    t.add_column(style="grey62", no_wrap=True)
    for key, name, price, buzz, line in DRINKS:
        open_ = buzz < 0 or (profile.buzz < CUT_OFF and ordered < PER_ROUND)
        t.add_row(Text(f" {key} ", "bold black on gold1" if open_ else "grey42 on grey23"),
                  Text(name, "bold" if open_ else "grey42"), Text(money(price), "green" if open_ else "grey42"),
                  Text(line, "grey62" if open_ else "grey42"))
    return t


def _status(profile) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="grey62", no_wrap=True)
    t.add_column(no_wrap=True)
    t.add_row("Buzz", meter(profile))
    t.add_row("Luck", luck_text(profile))
    return t


def scene(profile, line: str, ordered: int, aside: str = "") -> Align:
    words = Text()
    words.append(f"{BARTENDER}, behind the bar\n\n", "bold gold1")
    words.append_text(Text.from_markup(line))
    right = [words, Text(""), _menu(profile, ordered), Text(""), _status(profile)]
    if aside:
        right += [Text(""), Text.from_markup(aside)]
    right.append(Text("\nDrinks wear off a step every round you play.", "grey50 italic"))
    grid = Table.grid(padding=(0, 4))
    grid.add_column(no_wrap=True)
    grid.add_column(width=50)
    grid.add_row(portrait(), Group(*right))
    return Align.center(grid, vertical="middle")


#== Visiting the bar ==#

def visit(ui, player, on_drink=None) -> None:
    '''The bar overlay. `on_drink(cut_off)` is called after each order (for achievements).'''
    from casino import loanshark
    p = player.profile
    line = random.choice(GREET)
    aside = ""
    if p.loan and p.rounds_left < 0:
        aside = (f"[red]{loanshark.NAME}, from the end of the bar:[/] \"Drinkin' on my dime? "
                 f"You owe me {money(p.debt)}.\"")
    elif p.standing > 0 and not p.loan and not player.vinnie_drink and random.random() < 0.35:
        player.vinnie_drink = True
        aside = f"[magenta]{loanshark.NAME} raises a glass at you from a booth and sends over a beer.[/]"
        _pour(player, 1, "Beer from Vinnie", 0)
    options = ([(k, k, None) for k, *_ in DRINKS]
               + [(("esc", "q", "b", "enter"), "leave", "Back to the floor")])
    try:
        while True:
            ui.set_overlay("[bold gold1]  The Bar  [/]", scene(p, line, player.drinks_this_round, aside))
            choice = ui.choose("[bold]Order a drink[/] [grey50](1–4)[/]", options)
            if choice == "leave":
                return
            key, name, price, buzz, _ = next(d for d in DRINKS if d[0] == choice)
            cut_off = False
            if buzz > 0 and p.buzz >= CUT_OFF:
                line, cut_off = random.choice(CUT), True
            elif buzz > 0 and player.drinks_this_round >= PER_ROUND:
                line = random.choice(SLOW)
            elif player.balance < price:
                line = "Cash only, friend, and you ain't got enough of it."
            else:
                before = luck(p)
                _pour(player, buzz, name, price)
                after = luck(p)
                if after > before:
                    line = f"One {name.lower()}. You feel a little luckier."
                elif after < before:
                    line = f"One {name.lower()}. The room tilts a little. [red]Your luck slips.[/]"
                else:
                    line = f"One {name.lower()}, comin' up."
                ui.log(f"[cyan]Bar:[/] {name} {'−' if price else ''}{money(price) if price else 'on the house'}"
                       f" · luck {luck(p):+d} ({mood(p)})")
            if on_drink:
                on_drink(cut_off)
    finally:
        ui.clear_overlay()


def _pour(player, buzz: int, name: str, price: float) -> None:
    p = player.profile
    p.buzz = max(0, min(MAX_BUZZ, p.buzz + buzz))
    if buzz > 0:
        p.drinks += 1
        if price:
            player.drinks_this_round += 1
    if price:
        p.balance = round(p.balance - price, 2)
        p._log_money(f"Bar · {name}", -price)
    player.money_moved()


#== After a round ==#

def after_round(ui, player, delta: float) -> None:
    '''Luck kicks in (or doesn't) on the round just played, then the drinks wear off a step.'''
    p = player.profile
    n = luck(p)
    if delta and n and random.random() < CHANCE * abs(n):
        if n > 0 and delta > 0:
            bonus = round(min(max(1.0, delta * SHARE), BONUS_CAP), 2)
            p.balance = round(p.balance + bonus, 2)
            p._log_money("Hot streak", bonus)
            player.money_moved()
            ui.log(f"[bold green]Hot streak![/] Luck's with you: +{money(bonus)}.")
        elif n < 0:
            lost = round(min(max(1.0, abs(delta) * SHARE), FUMBLE_CAP, p.balance), 2)
            if lost > 0:
                p.balance = round(p.balance - lost, 2)
                p._log_money("Fumble", -lost)
                player.money_moved()
                what = "tip the dealer way too much" if delta > 0 else "knock over a stack of chips"
                ui.log(f"[bold red]Fumble![/] You {what}: −{money(lost)}.")
    player.drinks_this_round = 0
    if p.buzz:
        p.buzz -= 1
        player.dirty = True
        if p.buzz == 0:
            ui.log("[grey62]You've sobered up.[/]")
