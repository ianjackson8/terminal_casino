'''
Vinnie "The Vig": the casino's loan shark. He replaces the rebuy.

When you can't afford any table he offers a loan. You get the chips; he gets the loan plus his vig,
due in a set number of rounds (a round is one visit to a table). Pay late and interest compounds
every round, Vinnie stops being friendly, and eventually his boys come and take your chips.

Debt counts against your lifetime net, so the vig is a real loss.

Author: Ian Jackson
'''

from __future__ import annotations

import random

from rich.align import Align
from rich.console import Group
from rich.table import Table
from rich.text import Text

from casino.tui import esc, money

VIG = 0.20              # added up front: borrow $500, owe $600
LATE_RATE = 0.10        # compounds every round past the due date
COLLECT_AFTER = 10      # rounds overdue before the boys start taking chips
MAX_LOANS_OWED = 4      # he won't lend once you owe this many loans' worth
STANDING_STEP = 0.05    # each point of standing moves his vig by 5%, between 10% and 30%

NAME = 'Vinnie "The Vig"'


#== Settings and standing ==#

def vig_for(profile) -> float:
    '''His fee: 20%, less for players who pay on time, more for ones his boys had to visit.'''
    return round(VIG - STANDING_STEP * max(-2, min(2, profile.standing)), 2)


def standing_name(profile) -> str:
    return {-2: "on his list", -1: "on thin ice", 0: "a stranger", 1: "good for it", 2: "family"}[
        max(-2, min(2, profile.standing))]


def loan_amount(settings: dict) -> float:
    return float(settings.get("loan_amount", 500))


def loan_rounds(settings: dict) -> int:
    return max(1, int(settings.get("loan_rounds", 10)))


#== The man himself ==#

# mood -> (eyes, mouth, colour of his look)
FACES = {
    "friendly": ("  ◕   ◕  ", "  ╰───╯  ", "grey85"),
    "business": ("  ─   ─  ", "  ─────  ", "grey85"),
    "annoyed":  ("  ▀   ▀  ", "  ╭───╮  ", "orange1"),
    "angry":    ("  ╲   ╱  ", "  ▄▄▄▄▄  ", "red1"),
}


def portrait(mood: str) -> Text:
    eyes, mouth, look = FACES[mood]
    hat, suit, tie, cigar, ember = "grey35", "grey30", "red3", "tan", "bold orange_red1"
    art = Text(no_wrap=True)

    def line(*parts):
        for chunk, style in parts:
            art.append(chunk, style)
        art.append("\n")

    line(("      ▄▄▄▄▄▄▄▄▄      ", hat))
    line(("      █████████      ", hat))
    line(("      ▀▀▀▀▀▀▀▀▀      ", "grey15"))
    line(("   ▄▄▄█████████▄▄▄   ", hat))
    line(("     ╭", "wheat1"), ("─────────", "wheat1"), ("╮     ", "wheat1"))
    line(("     │", "wheat1"), (eyes, f"bold {look}"), ("│     ", "wheat1"))
    line(("     │", "wheat1"), ("    ╹    ", "wheat1"), ("│     ", "wheat1"))
    line(("     │", "wheat1"), (mouth, f"bold {look}"), ("│", "wheat1"), ("═══", cigar), ("●", ember), ("~", "grey50"))
    line(("     ╰──╮", "wheat1"), ("   ", ""), ("╭──╯     ", "wheat1"))
    line(("   ▗▄▄▄▄", suit), ("╲", "white"), ("▼", tie), ("╱", "white"), ("▄▄▄▄▖   ", suit))
    line(("  ▐█████", suit), ("▐", "white"), ("█", tie), ("▌", "white"), ("█████▌  ", suit))
    line(("  ▐█████", suit), ("▐", "white"), ("█", tie), ("▌", "white"), ("█████▌  ", suit))
    art.rstrip()
    return art


def scene(mood: str, lines: list, ledger=None) -> Table:
    '''Vinnie on the left, what he says (and the books) on the right.'''
    words = Text()
    words.append(f"{NAME}\n\n", "bold gold1")
    for i, line in enumerate(lines):
        words.append_text(Text.from_markup(line))
        if i < len(lines) - 1:
            words.append("\n\n")
    right = Group(words, Text(""), ledger) if ledger is not None else words
    grid = Table.grid(padding=(0, 4))
    grid.add_column(no_wrap=True)
    grid.add_column(width=46)
    grid.add_row(portrait(mood), right)
    return grid


def ledger(profile) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="grey62", no_wrap=True)
    t.add_column(justify="right", no_wrap=True)
    t.add_row("You owe", Text(money(profile.debt), "bold red"))
    left = profile.rounds_left
    if left > 0:
        t.add_row("Due in", Text(f"{left} round{'s' if left != 1 else ''}", "bold yellow" if left <= 3 else "bold"))
    elif left == 0:
        t.add_row("Due", Text("now", "bold red"))
    else:
        t.add_row("Late", Text(f"{-left} round{'s' if left != -1 else ''}  (+{LATE_RATE:.0%} a round)", "bold red"))
    return t


def mood_for(profile) -> str:
    left = profile.rounds_left
    if left > 3:
        return "friendly"
    if left >= 0:
        return "business"
    if -left < COLLECT_AFTER // 2:
        return "annoyed"
    return "angry"


def show(ui, mood: str, lines: list, options: list, prompt: str = "", ledger_of=None, default=None) -> str:
    '''Vinnie walks up to the table. Returns the option the player picks.'''
    body = Align.center(scene(mood, lines, ledger(ledger_of) if ledger_of is not None else None), vertical="middle")
    if not ui.interactive:
        ui.show_info(NAME, body)
    ui.set_overlay(f"[bold red]  {NAME}  [/]", body)
    try:
        return ui.choose(prompt or "[bold]Well?[/]", options, default=default)
    finally:
        ui.clear_overlay()


#== What he says ==#

OFFER = [
    "Hey, hey — look at you. Pockets empty, table's waiting. That's a sad thing to see.",
    "Rough night, huh? I seen it happen to better people than you. Smarter too.",
    "Lady Luck walked out on you, pal? I got somethin' that might bring her back.",
]
REMINDER = [
    "Just checkin' in. Friendly-like. You remember our little arrangement?",
    "Enjoyin' the tables? Good. Don't enjoy 'em so much you forget about me.",
    "I'm not worried. Are you worried? You shouldn't be worried. Yet.",
]
DUE = [
    "Clock's run out, friend. Today's the day. I'd like my money.",
    "Today's the day we talked about. I'm a patient man, but my patience got a due date too.",
]
LATE = [
    "You're late. I don't like late. Every round you sit there, the number gets bigger.",
    "Funny thing about interest — it don't take nights off. Neither do I.",
    "My associates been askin' about you. I told 'em you're good for it. Don't make me a liar.",
]
THREAT = [
    "Nice hands you got. Real nice. Be a shame if you couldn't hold cards with 'em no more.",
    "You know what happens to people who stiff me? Neither do their families. Nobody does.",
    "I'm tryin' to be reasonable here. My boys? They don't do reasonable.",
    "Last guy who kept me waitin' this long — they're still lookin' for his car. And him.",
]
COLLECT = [
    "I warned you. I warned you nice, then I warned you not so nice. Boys — turn out those pockets.",
    "We're done talkin'. Tony, Sal — take everything on the table. All of it.",
]
PAID_OFF = [
    "Pleasure doin' business. See? Nobody got hurt. Come see me anytime.",
    "Paid in full. I always knew you was one of the good ones.",
]
PARTIAL = [
    "It's a start. The meter's still runnin' on the rest.",
    "I'll take it. But we ain't square. Not yet.",
]
STIFFED = [
    "Stallin'? ...Alright. Alright. I'll be around. I'm always around.",
    "Sure, sure. Take your time. I'll just be over here. Watchin'.",
    "You're makin' a mistake, pal. But it's your mistake to make.",
]


def say(lines: list) -> str:
    return random.choice(lines)


#== Scenes ==#

def can_borrow(profile, settings: dict) -> bool:
    return profile.debt < loan_amount(settings) * (1 + VIG) * MAX_LOANS_OWED


def _achieve(ui, player, **event) -> None:
    from casino import achievements
    achievements.check(ui, player, **event)


GREET_OWED = [
    "Look who's back. I was startin' to think you forgot about me.",
    "Welcome back, friend. Your tab missed you.",
]
GREET_LATE = [
    "There you are. My boys been drivin' past your place. Nice curtains.",
    "You got some nerve walkin' in here. You got my money too?",
]
BIG_WIN = [
    "Whoa, whoa — look at that pile. Funny, I was just thinkin' about our arrangement.",
    "Nice score, pal. Real nice. Now's a beautiful time to settle up, don't you think?",
]


def offer_loan(ui, player, settings: dict) -> bool:
    '''The player is broke: Vinnie offers a loan. Returns True if they took it.'''
    p = player.profile
    amount, rounds = loan_amount(settings), loan_rounds(settings)
    vig = vig_for(p)
    owed = round(amount * (1 + vig), 2)
    if not can_borrow(p, settings):
        show(ui, "angry", [
            f"Another loan? You already owe me [bold red]{money(p.debt)}[/]. You got a problem, kid, "
            "and it ain't a money problem.",
            "Come back when you can pay me. Or don't come back at all.",
        ], [(("enter", "esc", "n", "y"), "ok", "Back away slowly")], ledger_of=p)
        return False
    if p.loan:
        lines = [
            "Back already? You still owe me. ...But I like you, so here's the deal.",
            f"I put another [bold green]{money(amount)}[/] on the table. Your tab goes up "
            f"[bold red]{money(owed)}[/]. Same due date — the clock don't reset for nobody.",
        ]
        mood = "annoyed" if p.rounds_left < 0 else "business"
    else:
        lines = [
            say(OFFER),
            f"I can put [bold green]{money(amount)}[/] in your hand right now. You pay me back "
            f"[bold]{money(owed)}[/] inside [bold]{rounds} rounds[/]. That's {vig:.0%} — a bargain, "
            "between friends.",
            f"Late? Then it's {LATE_RATE:.0%} more every round, and we stop bein' friends.",
        ]
        mood = "friendly"
        if p.standing > 0:
            lines.insert(1, "You paid me on time before. I remember that. You get the friends-and-family rate.")
        elif p.standing < 0:
            lines.insert(1, "Last time my boys had to come see you. So this time it costs more.")
            mood = "business"
    choice = show(ui, mood, lines, [("y", "y", f"Take the {money(amount)}"), (("n", "esc"), "n", "No thanks")],
                  prompt=f"[bold]Take a {money(amount)} loan?[/]", ledger_of=p if p.loan else None)
    if choice != "y":
        ui.log(f"[grey62]{NAME} shrugs and lights another cigar.[/]")
        return False
    p.borrow(amount, vig, rounds)
    player.money_moved()
    ui.log(f"[magenta]{NAME}:[/] +{money(amount)} in chips. You owe [red]{money(p.debt)}[/], "
           f"due in {max(p.rounds_left, 0)} rounds.")
    _achieve(ui, player, kind="loan")
    return True


def pay(ui, player, mood: str = None) -> None:
    '''Pay Vinnie: all of it if you can, or a part.'''
    p = player.profile
    if not p.loan:
        return
    if player.balance <= 0:
        ui.error("You've got nothing to pay him with.")
        return
    full = min(p.debt, player.balance)
    options = [("a", "all", f"Pay {money(full)}" + ("" if full >= p.debt else " (everything)"))]
    if player.balance > 1:
        options.append(("p", "part", "Pay part"))
    options.append((("esc", "n"), "n", "Not now"))
    choice = ui.choose(f"You owe {NAME} [bold red]{money(p.debt)}[/]. Pay how much?", options, default="all")
    if choice == "n":
        return
    amount = full
    if choice == "part":
        while True:
            raw = ui.ask(f"Pay how much? (up to {money(full)})").replace("$", "").replace(",", "").strip()
            if not raw:
                return
            try:
                amount = float(raw)
            except ValueError:
                ui.error("Enter an amount, e.g. 100.")
                continue
            if amount <= 0:
                ui.error("Vinnie doesn't find that funny.")
                continue
            amount = min(amount, full)
            break
    on_time = p.rounds_left >= 0
    paid = p.repay(amount)
    player.money_moved()
    if p.loan is None:
        ui.log(f"[green]Paid {NAME} {money(paid)} — you're square.[/]")
        lines = [say(PAID_OFF)]
        if on_time:
            p.standing = min(2, p.standing + 1)
            lines.append(f"[green]On time, too. Next loan's {vig_for(p):.0%}. You're {standing_name(p)} now.[/]")
        show(ui, "friendly", lines, [(("enter", "esc", " "), "ok", "Nod")])
        _achieve(ui, player, kind="paid_off", on_time=on_time)
    else:
        ui.log(f"[yellow]Paid {NAME} {money(paid)}. Still owe {money(p.debt)}.[/]")
        show(ui, mood or mood_for(p), [say(PARTIAL)], [(("enter", "esc", " "), "ok", "Nod")], ledger_of=p)


def after_round(ui, player, settings: dict, delta: float = 0.0) -> None:
    '''Back from a table: interest, reminders, threats, and — eventually — a visit from the boys.'''
    p = player.profile
    if not p.loan:
        return
    interest = p.accrue(LATE_RATE)
    if interest:
        player.dirty = True
        ui.log(f"[red]Late fee:[/] +{money(interest)} on what you owe {NAME}. You owe [red]{money(p.debt)}[/].")
    left = p.rounds_left
    late = -left

    if late >= COLLECT_AFTER and player.balance > 0:
        show(ui, "angry", [say(COLLECT),
                           "Two very large men lean over the table and help themselves to your chips."],
             [(("enter", "esc", " "), "ok", "Don't resist")], prompt="[bold red]Collection[/]", ledger_of=p)
        taken = p.repay(player.balance, label="Collected")
        p.standing = max(-2, p.standing - 1)
        player.money_moved()
        _achieve(ui, player, kind="collected")
        ui.log(f"[bold red]Vinnie's boys took {money(taken)}.[/] "
               + (f"You still owe {money(p.debt)}." if p.loan else "You're square — the hard way."))
        return

    if delta > 0 and player.balance >= p.debt and delta >= p.debt / 2:
        choice = show(ui, mood_for(p), [say(BIG_WIN)],
                      [("p", "pay", "Pay him"), (("n", "esc"), "n", "Not yet")], ledger_of=p, default="pay")
        if choice == "pay":
            pay(ui, player)
        else:
            ui.log(f"[red]{NAME}:[/] Your call. I'll remember it.")
        return

    if left > 3:
        ui.log(f"[grey62]{NAME} tips his hat from the bar. {money(p.debt)} due in {left} rounds.[/]")
        return
    if left > 0 and left not in (3, 1):
        ui.log(f"[yellow]{NAME} is watching you. {money(p.debt)} due in {left} rounds.[/]")
        return

    mood = mood_for(p)
    if left > 0:
        lines = [say(REMINDER)]
    elif left == 0:
        lines = [say(DUE)]
    elif late < COLLECT_AFTER // 2:
        lines = [say(LATE)]
    else:
        lines = [say(THREAT)]
        if late == COLLECT_AFTER - 1:
            lines.append("[bold red]Next round, my boys come collect. Whatever you got, they take.[/]")
    options = []
    if player.balance > 0:
        options.append(("p", "pay", "Pay him"))
    options.append((("n", "esc"), "n", "Not yet" if left > 0 else "Stall"))
    choice = show(ui, mood, lines, options, ledger_of=p, default="pay" if player.balance >= p.debt else None)
    if choice == "pay":
        pay(ui, player, mood)
    elif left <= 0:
        ui.log(f"[red]{NAME}:[/] {esc(say(STIFFED))}")


def greet(ui, player) -> None:
    '''Signing in while in debt: Vinnie's waiting at the door.'''
    p = player.profile
    if not p.loan:
        return
    late = p.rounds_left < 0
    options = [(("enter", "esc", " "), "ok", "Nod nervously")]
    if p.balance > 0:
        options.insert(0, ("p", "pay", "Pay him"))
    choice = show(ui, mood_for(p), [say(GREET_LATE if late else GREET_OWED)], options, ledger_of=p,
                  prompt="[bold]Vinnie's waiting by the door[/]")
    if choice == "pay":
        pay(ui, player)


def farewell(ui, player) -> None:
    '''Cashing out while in debt.'''
    p = player.profile
    if not p.loan:
        return
    late = p.rounds_left < 0
    line = ("Leavin' town? Funny. We know where you live." if late
            else "Headin' out? Sure. The clock stops while you're gone. The debt don't.")
    ui.log(f"[red]{NAME}:[/] {line}  (You owe {money(p.debt)}.)")
