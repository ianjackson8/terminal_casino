#!/usr/bin/env python3
'''
Regenerate the README screenshots in docs/readme/ from the real UI code, using demo data.

    python scripts/readme_screens.py

Each screen is rendered with Rich's SVG export, so the images are genuine renders of the
current UI (no mock-ups). Nothing is written outside docs/readme/: the demo profiles live in a
temporary folder. The blackjack screen needs plugins/ai_blackjack and its dependencies (torch).

Author: Ian Jackson
'''

from __future__ import annotations

import io
import random
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console, Group   # noqa: E402
from rich.text import Text                # noqa: E402

from casino import check as check_cli     # noqa: E402
from casino import pages                  # noqa: E402
from casino.compliance import check_plugin  # noqa: E402
from casino.loader import discover_plugins  # noqa: E402
from casino.profiles import Profile, ProfileStore  # noqa: E402
from casino.session import Player         # noqa: E402
from casino.tables import build_tables, open_tables  # noqa: E402
from casino.tui import RichUI, money      # noqa: E402

OUT = ROOT / "docs" / "readme"
W, H = 128, 36
NOW = time.time()
DAY = 86400

SETTINGS = {
    "init_balance": 500, "autosave": True, "allow_rebuy": True, "enabled_plugins": [],
    "tables": [
        {"id": "ai_blackjack", "game": "ai_blackjack", "name": "Standard", "min_bet": 5, "max_bet": 500, "rules": {}},
        {"id": "bj_high_roller", "game": "ai_blackjack", "name": "High Roller", "min_bet": 100, "max_bet": 5000,
         "rules": {"num_decks": 2, "allow_insurance": False}},
        {"id": "bj_single_deck", "game": "ai_blackjack", "name": "Single Deck", "min_bet": 10, "max_bet": 250,
         "rules": {"num_decks": 1, "split_limit": "1", "allow_double_after_split": False}},
    ],
    "disabled_tables": [],
}


def recorder(width: int = W, height: int = H) -> Console:
    return Console(record=True, width=width, height=height, force_terminal=True, color_system="truecolor",
                   file=io.StringIO(), legacy_windows=False)


def save(console: Console, name: str, title: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(OUT / f"{name}.svg"), title=title)
    print(f"  docs/readme/{name}.svg")


def snap(ui, name: str, title: str, width: int = W, height: int = H) -> None:
    ui.console = recorder(width, height)
    ui.console.print(ui._render(), height=height)
    save(ui.console, name, title)


#== Demo data ==#

def demo_profile() -> Profile:
    rng = random.Random(18)   # chosen for a dip-then-climb balance arc
    prof = Profile("Alex", 500, 500, created=NOW - 24 * DAY, last_played=NOW - 300)
    tables = [("Blackjack", 0.5, (5, 60)), ("Blackjack · High Roller", 0.25, (100, 600)),
              ("Blackjack · Single Deck", 0.25, (10, 120))]
    t = NOW - 23 * DAY
    for i in range(70):
        label, _, (lo, hi) = rng.choices(tables, weights=[w for _, w, _ in tables])[0]
        if label.endswith("High Roller") and prof.balance < 700:
            label, (lo, hi) = "Blackjack", (5, 60)
        before = prof.balance
        swing = rng.uniform(lo, hi) * rng.choice([1, 1, 1, -1, -1, 0.5]) * 0.6
        swing += 4 if i > 30 else 0            # a slow upward drift, so the chart tells a story
        prof.balance = round(max(5.0, before + swing), 2)
        prof.record(label, before, prof.balance, rng.uniform(60, 900), game="Blackjack")
        prof.history[-1]["t"] = t
        t += rng.uniform(0.15, 0.5) * DAY
    prof.sessions = 11
    prof.last_played = NOW - 300
    return prof


def regulars(store: ProfileStore) -> None:
    store.save(demo_profile())
    for name, bal, ago_s in (("Sam", 312.5, 2 * 3600), ("Jordan", 1840, 3 * DAY), ("Priya", 95, 6 * DAY)):
        store.save(Profile(name, bal, 500, last_played=NOW - ago_s))


#== Screens ==#

def casino_screens(plugins, store) -> None:
    tables = open_tables(build_tables(plugins, SETTINGS), SETTINGS)

    # Welcome
    ui = RichUI()
    ui.splash_info = f"New players buy in for [bold]$500[/]  ·  {len(tables)} tables open"
    ui.regulars = store.all()
    ui._prompt, ui._buffer = "[bold]Your name[/] ([grey62]Enter to take a seat[/])", "Ale"
    snap(ui, "welcome", "Terminal Casino")

    # Lobby
    prof = store.load("Alex")
    player = Player(prof, returning=True)
    player.starting_balance = prof.balance - 145
    player.history = [player.starting_balance, player.starting_balance + 60, player.starting_balance - 40, prof.balance]
    player.games_played = {"Blackjack": 2, "Blackjack · High Roller": 1}
    player.dirty, player.saved_at = False, NOW - 60
    player.started = NOW - 47 * 60
    ui = RichUI()
    ui.player = player
    ui.lobby = SimpleNamespace(tables=tables, cursor=1)
    for line in [f"Welcome back, [bold]Alex[/]. Your balance is [green]{money(player.starting_balance)}[/].",
                 "[bold]Blackjack[/]: won [green]$60[/]",
                 "[bold]Blackjack[/]: lost [red]$100[/]",
                 "[bold]Blackjack · High Roller[/]: won [green]$185[/]"]:
        ui.log(line)
    ui._prompt = "[bold]Lobby[/]"
    from main import lobby_options
    ui._options = lobby_options(tables, rebuy=False, autosave=True)
    snap(ui, "lobby", "Terminal Casino — Lobby", height=24)

    # Stats: overview and games tabs
    for tab, name in ((0, "stats"), (1, "stats-games")):
        def build(width, height, tab=tab):
            views = (pages._overview, pages._games, pages._history)
            return Group(pages._tabs(pages.STAT_TABS, tab), Text(""), views[tab](player, width, height - 2))
        ui.set_overlay("Stats  ·  Alex", pages._Sized(build))
        ui._prompt = "[bold]Stats[/]"
        ui._options = [(("left", "h"), "prev", ""), (("right", "l", "tab"), "next", "Switch tab"),
                       (("esc", "q"), "back", "Back to lobby")]
        snap(ui, name, "Terminal Casino — Stats", height=31 if tab == 0 else 22)
    ui.clear_overlay()

    # Settings, then the table editor for the High Roller table. Each runs the real settings page
    # with scripted keys and is captured just before it would wait for the next key.
    for name, keys in (("settings", ["down"] * 6), ("table-editor", ["down"] * 6 + ["edit_table"] + ["down"] * 4)):
        ui = RichUI()
        ui.player = player
        ui.lobby = SimpleNamespace(tables=tables, cursor=0)
        seq = iter(keys)

        def choose(prompt, opts, default=None, seq=seq, ui=ui, name=name):
            ui._prompt, ui._options = prompt, opts
            try:
                return next(seq)
            except StopIteration:
                snap(ui, name, "Terminal Casino — Settings", height=26 if name == "settings" else 22)
                raise KeyboardInterrupt
        ui.choose = choose
        try:
            pages.settings_page(ui, {k: v for k, v in SETTINGS.items()}, plugins, store, "Alex")
        except KeyboardInterrupt:
            pass


def check_screen(plugins) -> None:
    plugin = next((p for p in plugins if p.key == "ai_blackjack"), None)
    if plugin is None:
        return
    console = recorder(100, 40)
    report = check_plugin(plugin.path, key="ai_blackjack", deep=True)
    check_cli.render(report, console)
    save(console, "check", "python -m casino.check ai_blackjack")


def blackjack_screen(balance: float) -> None:
    plugin_dir = ROOT / "plugins" / "ai_blackjack"
    if not plugin_dir.exists():
        return
    sys.path.insert(0, str(plugin_dir))
    try:
        with redirect_stdout(io.StringIO()):
            import play_blackjack as bj
            from bj_tui import RichUI as TableUI
    except Exception as err:            # torch not installed, etc.
        print(f"  (skipped blackjack screen: {err})")
        return

    ui = TableUI()
    ui.animate = False
    ui.side_view = "log"
    with tempfile.TemporaryDirectory() as tmp:
        game = bj.BlackjackGame(num_decks=2, player_names=["Alex"], bot_info=[], starting_balance=balance,
                                log_file=str(Path(tmp) / "log.json"), deal_delay=0, ui=ui)
    game.plugin_mode = True
    game.table_name, game.min_bet, game.max_bet = "High Roller", 100.0, 5000.0
    game.game_num = 7
    ui.attach(game)
    player, dealer = game.players[0], game.dealer
    player.place_bet(200)
    C = bj.Card
    for card in (C("Ace", "Spades"), C("7", "Diamonds")):
        player.hands[0].add_card(card)
    for card in (C("Queen", "Clubs"), C("9", "Hearts")):
        dealer.hands[0].add_card(card)
    game.phase = "playing"
    ui.active_player, ui.active_hand = player, 0
    for line in ["── Round 7 ──", "[bold]Alex[/] bets [bold]$200[/]",
                 "Dealer shows [red]9♥[/]", "[bold]Alex[/] has [bold]soft 18[/]"]:
        ui._log.append(line)
    ui._prompt = "[bold]Alex[/], your move ([bold]soft 18[/] vs [red]9♥[/])"
    ui._options = [("h", "hit", "Hit"), ("s", "stand", "Stand"), ("d", "double", "Double"),
                   ("?", "help", "Rules"), (("esc", "l"), "leave", "Leave table")]
    ui.console = recorder(W, 31)
    ui.console.print(ui._render(), height=31)
    save(ui.console, "blackjack", "AI Blackjack — High Roller")


def main() -> None:
    print("Rendering README screens:")
    with tempfile.TemporaryDirectory() as tmp:
        store = ProfileStore(Path(tmp))
        regulars(store)
        plugins = discover_plugins(ROOT / "plugins", {}, log=lambda level, msg: print(f"  [{level}] {msg}"))
        casino_screens(plugins, store)
        check_screen(plugins)
        balance = store.load("Alex").balance
    blackjack_screen(balance)


if __name__ == "__main__":
    main()
