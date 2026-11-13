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
import json
import random
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rich.console import Console, Group   # noqa: E402
from rich.text import Text                # noqa: E402

from casino import check as check_cli     # noqa: E402
from casino import pages                  # noqa: E402
from casino.carousel import Lobby         # noqa: E402
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

# the casino's real tables, so the screenshots show what a fresh clone shows
SETTINGS = {
    "init_balance": 500, "autosave": True, "allow_rebuy": True, "enabled_plugins": [],
    "tables": json.loads((ROOT / "game_settings.json").read_text()).get("tables", []),
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
    ui.lobby = Lobby(tables)
    ui.lobby.move_table(1)                 # High Roller
    for line in [f"Welcome back, [bold]Alex[/]. Your balance is [green]{money(player.starting_balance)}[/].",
                 "[bold]Blackjack[/]: won [green]$60[/]",
                 "[bold]Blackjack[/]: lost [red]$100[/]",
                 "[bold]Blackjack · High Roller[/]: won [green]$185[/]"]:
        ui.log(line)
    ui._prompt = "[bold]Lobby[/]"
    from main import lobby_options
    ui._options = lobby_options(ui.lobby, rebuy=False, autosave=True)
    snap(ui, "lobby", "Terminal Casino — Lobby", height=32)

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
        ui.lobby = Lobby(tables)
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


def _import_game(key: str, modules):
    '''Import a game's own modules from plugins/<key>, or None if it (or a dependency) is missing.'''
    plugin_dir = ROOT / "plugins" / key
    if not plugin_dir.exists():
        return None
    sys.path.insert(0, str(plugin_dir))
    try:
        with redirect_stdout(io.StringIO()):
            return [__import__(m) for m in modules]
    except Exception as err:
        print(f"  (skipped {key} screen: {err})")
        return None


def _table(game: str, name: str) -> dict:
    cfg = next((t for t in SETTINGS["tables"] if t["game"] == game and t["name"] == name), None)
    return cfg or {"name": name, "min_bet": 1, "max_bet": None, "rules": {}}


def roulette_screen(balance: float) -> None:
    mods = _import_game("roulette", ["play_roulette", "roulette_tui", "roulette_engine"])
    if mods is None:
        return
    pr, rt, eng = mods
    settings = {**pr.load_settings(), "write_log": False, "animate_spin": False}
    ui = rt.RouletteUI()
    game = pr.RouletteGame("Alex", balance, _table("roulette", "European"), settings, ui=ui, rng=random.Random(5))
    ui.game = game
    for spec, amount in (("17", 25), ("16/17/18", 10), ("black", 50), ("2nd12", 20)):
        game.place(eng.parse_spot(spec, game.wheel).key, amount)
    game.spins, game.history = 6, ["32", "5", "0", "19", "26", "8"]
    spin = game.spin(result="17")
    _, final_rot = pr.spin_frames(eng.WHEEL_ORDER[game.wheel], "17", game.wheel_rot,
                                  rt.front_slot(len(eng.WHEEL_ORDER[game.wheel])), 1)
    game.wheel_rot = final_rot % len(eng.WHEEL_ORDER[game.wheel])
    game.ball = ("pocket", "17")
    game.reveal(spin)
    ui.console = recorder(W, 38)
    ui.console.print(ui._render(), height=38)
    save(ui.console, "roulette", "Roulette — European")


def baccarat_screen(balance: float) -> None:
    mods = _import_game("baccarat", ["play_baccarat", "bac_tui"])
    if mods is None:
        return
    pb, bt = mods
    settings = {**pb.load_settings(), "deal_delay": 0, "animate_cards": False, "log_game": False}
    # find a shoe whose first coup is a Player win on a third card, which shows off the most
    for seed in range(500):
        ui = bt.RichUI()
        table = {"name": "Mini Baccarat", "min_bet": 5, "max_bet": 500, "rules": {}}
        game = pb.BaccaratGame("Alex", balance, table, settings, ui, rng=random.Random(seed), plugin_mode=True)
        game.new_shoe()
        game.bets = {pb.PLAYER: 100, pb.TIE: 10}
        game.placed = list(game.bets.items())
        game.deal()
        if game.coup.winner == pb.PLAYER and len(game.coup.order) >= 5:
            break
    game.status = "Place your bets"
    game.phase = "result"
    ui._prompt, ui._options, ui._default = "Place your bets", game.options(), None
    ui.console = recorder(W, 34)
    ui.console.print(ui._render(), height=34)
    save(ui.console, "baccarat", "Baccarat — Mini Baccarat")


def craps_screen(balance: float) -> None:
    mods = _import_game("craps", ["play_craps", "craps_tui"])
    if mods is None:
        return
    pc, ct = mods
    settings = {**pc.load_settings(), "animate_dice": False, "log_game": False}
    ui = ct.RichUI()
    game = pc.CrapsGame("Alex", balance, _table("craps", "Standard"), settings, ui, plugin_mode=True)
    # point 6 with odds, a come bet travels to the 5 and takes odds, then a hard eight pays the props
    game.add_bet("pass", 25)
    game.roll(dice=(4, 2))
    for key, amount in (("pass_odds", 100), ("place_8", 30), ("come", 25)):
        game.add_bet(key, amount)
    game.roll(dice=(2, 3))
    for key, amount in (("come_odds_5", 50), ("hard_8", 5), ("field", 10)):
        game.add_bet(key, amount)
    game.roll(dice=(4, 4))
    game.cursor = (0, 3)                      # on the Place 8, which just paid
    for line in ("[bold]Roll 1[/] · 4-2 = 6 · The point is 6, easy.",
                 "[bold]Roll 2[/] · 2-3 = 5 · Five, no field.", "  [grey62]Come moves to the 5[/]",
                 "[bold]Roll 3[/] · 4-4 = [bold]8[/] · Hard eight.", "  Place 8 $30: [bold green]+$35[/]",
                 "  Hard 8 $5: [bold green]+$45[/]", "  Field $10: [red3]-$10[/]"):
        ui.log(line)
    ui._prompt, ui._options, ui._default = game.prompt, game.options(), "bet"
    snap(ui, "craps", "Craps — Standard", W, 36)


def slots_screen(balance: float) -> None:
    mods = _import_game("slots", ["play_slots", "slots_tui"])
    if mods is None:
        return
    ps, st = mods
    settings = {**ps.load_settings(), "animate": False, "animate_reels": False, "log_game": False}
    table = _table("slots", "Main Floor")
    for seed in range(400):        # a real win of 5x or more, without free spins (those open their own screen)
        ui = st.RichUI()
        game = ps.SlotsGame("Alex", balance, table, settings, ui, rng=random.Random(seed), plugin_mode=True)
        game.animate = False
        game.line_bet = 0.25
        spin = game.play_spin()
        if spin.win >= 5 * spin.total_bet and not spin.free_spins_won:
            break
    ui._prompt, ui._options, ui._default = "Your bet", game.options(), "spin"
    ui.console = recorder(W, 34)
    ui.console.print(ui._render(), height=34)
    save(ui.console, "slots", "Slots — Main Floor")


def poker_screen(balance: float) -> None:
    mods = _import_game("poker", ["play_poker", "poker_tui"])
    if mods is None:
        return
    pp, pt = mods

    class ScriptedUI(pt.RichUI):
        '''Checks or calls every decision, and skips every pause, so a real hand plays itself.'''
        def get_action(self, prompt, options, default=None):
            values = [v for _, v, _ in options]
            self._prompt, self._options, self._default = prompt, options, default
            return ("call" if "call" in values else "deal" if "deal" in values else values[0]), None

        def pause(self, seconds):
            return True

        def flip_card(self):
            return True

    settings = {**pp.load_settings(), "animate_cards": False, "deal_delay": 0, "bot_delay": 0, "log_game": False}
    table = _table("poker", "$1/$2 No-Limit")
    for seed in range(300):        # a hand the player wins at a showdown against at least one other player
        ui = ScriptedUI()
        game = pp.PokerGame("Alex", balance, table, settings, ui, rng=random.Random(seed), plugin_mode=True)
        game.rack_up()
        before = game.human.stack
        game.play_hand()
        live = [p for p in game.hand.players if not p.folded]
        if game.human.stack > before + 10 and len(live) >= 2 and game.board_shown == 5:
            break
    opts = [(("enter", " "), "deal", "Deal"), ("?", "help", "Rules"), (("tab",), "tab", "Panel"),
            (("q", "Q", "esc"), "leave", "Leave table")]
    ui._prompt, ui._options, ui._default = "Next hand", opts, "deal"
    ui.console = recorder(W, 34)
    ui.console.print(ui._render(), height=34)
    save(ui.console, "poker", "Texas Hold'em — $1/$2 No-Limit")


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
    roulette_screen(balance)
    baccarat_screen(balance)
    slots_screen(balance)
    poker_screen(balance)
    craps_screen(balance)


if __name__ == "__main__":
    main()
