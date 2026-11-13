#!/usr/bin/env python3
"""
Terminal Casino
Author: Ian Jackson
"""

import json
import sys
import time
from pathlib import Path

from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from casino.carousel import Lobby
from casino.loader import discover_plugins
from casino.pages import settings_page, stats_page
from casino.profiles import Profile, ProfileStore
from casino.session import Player
from casino.tables import build_tables, open_tables
from casino.tui import esc, make_ui, money, net_text

ROOT = Path(__file__).parent
SETTINGS_FILE = ROOT / "game_settings.json"
PLUGINS_DIR = ROOT / "plugins"
PROFILES_DIR = ROOT / "profiles"
DEFAULTS = {
    "init_balance": 100.0,
    "autosave": True,
    "allow_rebuy": True,
    "enabled_plugins": [],      # optional game order in the lobby; empty = discovery order
    "tables": [],               # extra tables per game (stakes + rules); see docs/GAME_SPEC.md §6
    "disabled_tables": [],      # table ids hidden from the lobby (toggled in Settings)
    "plugin_overrides": {},
}


#== Settings ==#

def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            settings = {**DEFAULTS, **json.load(f)}
        # pre-tables configs hid whole games; a game's default table id is its plugin key
        legacy = settings.pop("disabled_plugins", None) or []
        settings["disabled_tables"] = sorted(set(settings.get("disabled_tables") or []) | set(legacy))
        return settings
    except FileNotFoundError:
        return dict(DEFAULTS)
    except json.JSONDecodeError as e:
        print(f"Invalid game_settings.json: {e}")
        sys.exit(1)


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
        f.write("\n")


def ordered_plugins(all_plugins: list, settings: dict) -> list:
    '''Installed games, with enabled_plugins (if set) first in that order; new games follow.'''
    order = settings.get("enabled_plugins") or []
    return sorted(all_plugins, key=lambda p: order.index(p.key) if p.key in order else len(order))


def load_tables(all_plugins: list, settings: dict, log=None) -> list:
    '''Every valid table (open or not), grouped by game.'''
    return build_tables(ordered_plugins(all_plugins, settings), settings, log)


#== Profiles ==#

def sign_in(ui, store: ProfileStore, settings: dict) -> Player:
    while True:
        name = ui.ask("[bold]Your name[/] ([grey62]Enter to take a seat[/])").strip()
        if not name:
            ui.error("Name cannot be empty.")
            continue
        if len(name) > 24:
            ui.error("Keep it to 24 characters or fewer.")
            continue
        try:
            profile = store.load(name)
        except ValueError as err:
            moved = store.quarantine(name)
            ui.log(f"[yellow]Couldn't read the saved profile for {esc(name)} — moved it to {esc(moved.name)}.[/]")
            ui.error(str(err))
            profile = None
        if profile is not None:
            ui.log(f"Welcome back, [bold]{esc(profile.name)}[/]. Your balance is [green]{money(profile.balance)}[/].")
            return Player(profile, returning=True)
        buy_in = float(settings["init_balance"])
        profile = Profile(name=name, balance=buy_in, bought_in=buy_in)
        ui.log(f"Welcome, [bold]{esc(name)}[/]. New profile — you buy in for [green]{money(buy_in)}[/].")
        return Player(profile)


def save_player(ui, store: ProfileStore, player: Player, quiet: bool = False) -> bool:
    try:
        store.save(player.profile)
    except OSError as err:
        ui.error(f"Couldn't save your profile: {err}")
        return False
    player.mark_saved()
    if not quiet:
        ui.log(f"[green]Saved[/] {esc(player.name)}'s profile.")
    ui.refresh()
    return True


#== Lobby ==#

def summary_table(player: Player) -> Table:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    table.add_row("Player", Text(player.name, "bold"))
    table.add_row("Sat down with", money(player.starting_balance))
    table.add_row("Leaving with", Text(money(player.balance), "bold green"))
    table.add_row("This visit", net_text(player.net))
    table.add_row("Lifetime", net_text(player.profile.net))
    for game, count in player.games_played.items():
        table.add_row("", Text.assemble((game, "bold"), (f"  ×{count}", "grey62")))
    return table


def run_table(ui, table, player: Player) -> None:
    '''Hand the terminal to a game at one of its tables, then take it back with the new balance.'''
    plugin = table.plugin
    balance_before = player.balance
    started = time.monotonic()
    ui.stop()
    error = None
    try:
        if plugin.accepts_table:
            result = plugin.run(player.name, player.balance, table=table.to_run_arg())
        else:
            result = plugin.run(player.name, player.balance)
        player.balance = max(0.0, float(result))
    except (KeyboardInterrupt, EOFError):
        player.balance = balance_before
        error = "interrupted"
    except Exception as err:
        player.balance = balance_before
        error = err
    finally:
        ui.start()

    label = table.label
    if error == "interrupted":
        ui.log(f"[grey62]Left {esc(label)} with Ctrl-C — balance rolled back.[/]")
        return
    if error is not None:
        ui.log(f"[red]{esc(label)} crashed: {esc(error)}[/]")
        ui.error(f"Error in {label} — balance restored to {money(balance_before)}.")
        return

    player.record_game(label, balance_before, time.monotonic() - started, game=plugin.name)
    delta = player.balance - balance_before
    if delta > 0:
        ui.log(f"[bold]{esc(label)}[/]: won [green]{money(delta)}[/]")
    elif delta < 0:
        ui.log(f"[bold]{esc(label)}[/]: lost [red]{money(-delta)}[/]")
    else:
        ui.log(f"[bold]{esc(label)}[/]: broke even")


def can_rebuy(player: Player, tables: list, settings: dict) -> bool:
    '''Rebuys are offered only when the player can't afford any open table.'''
    if not settings.get("allow_rebuy", True):
        return False
    cheapest = min((t.min_bet for t in tables), default=1.0)
    return player.balance < max(cheapest, 0.01)


def lobby_options(lobby, rebuy: bool, autosave: bool) -> list:
    options = []
    if len(lobby.games) > 1:
        options += [(("left", "h"), "left", ""), (("right", "l"), "right", "Game")]
    if len(lobby.game_tables) > 1:
        options += [(("up", "k"), "up", ""), (("down", "j"), "down", "Table")]
    if lobby.games:
        options.append((("enter", " "), "play", "Play"))
        last = min(len(lobby.game_tables), 9)
        options += [(str(i), str(i), None) for i in range(1, last + 1)]       # hidden: table by number
    if rebuy:
        options.append(("r", "rebuy", "Rebuy"))
    options += [("s", "stats", "Stats"), ("g", "settings", "Settings")]
    if not autosave:
        options.append(("w", "save", "Save"))
    options.append((("q", "esc"), "quit", "Cash out"))
    return options


def lobby_loop(ui, all_plugins: list, settings: dict, store: ProfileStore, player: Player) -> None:
    lobby = ui.lobby = Lobby(open_tables(load_tables(all_plugins, settings), settings))

    while True:
        tables = lobby.tables
        autosave = bool(settings.get("autosave", True))
        ui.autosave = autosave
        if autosave and player.dirty:
            save_player(ui, store, player, quiet=True)
        rebuy = can_rebuy(player, tables, settings)
        action = ui.choose("[bold red]Out of chips[/]" if rebuy else "[bold]Lobby[/]",
                           lobby_options(lobby, rebuy, autosave))

        if action in ("left", "right"):
            step = -1 if action == "left" else 1
            if lobby.move_game(step):
                ui.slide_lobby(step)
        elif action in ("up", "down"):
            lobby.move_table(-1 if action == "up" else 1)
        elif action == "stats":
            stats_page(ui, player)
        elif action == "settings":
            if settings_page(ui, settings, ordered_plugins(all_plugins, settings), store, current=player.name):
                save_settings(settings)
                lobby.set_tables(open_tables(load_tables(all_plugins, settings, log=log_to(ui)), settings))
                ui.log("[green]Settings saved.[/]")
        elif action == "save":
            save_player(ui, store, player)
        elif action == "rebuy":
            amount = float(settings["init_balance"])
            if ui.choose(f"Rebuy for {money(amount)}? It counts against your lifetime net.",
                         [("y", "y", "Rebuy"), ("n", "n", "Not now")]) == "y":
                player.rebuy(amount)
                ui.log(f"[magenta]Rebuy:[/] +{money(amount)} in chips.")
        elif action == "quit":
            if ui.choose("Cash out and leave the casino?", [("y", "y", "Cash out"), ("n", "n", "Stay")]) != "y":
                continue
            if player.dirty and not autosave:
                answer = ui.choose("Save your profile before leaving?",
                                   [("y", "y", "Save"), ("n", "n", "Don't save"), ("esc", "c", "Cancel")], default="y")
                if answer == "c":
                    continue
                if answer == "y" and not save_player(ui, store, player):
                    continue
            return
        elif action == "play" or action.isdigit():
            if action != "play" and not lobby.pick_table(int(action) - 1):
                continue
            table = lobby.table
            if table is None:
                continue
            if player.balance < table.min_bet:
                ui.error(f"{table.label} needs at least {money(table.min_bet)} — you have {money(player.balance)}.")
                continue
            run_table(ui, table, player)


#== Main ==#

def log_to(ui):
    return lambda level, msg: ui.log(f"[{'red' if level == 'error' else 'yellow'}]{esc(msg)}[/]")


def main() -> None:
    settings = load_settings()
    store = ProfileStore(PROFILES_DIR)
    ui = make_ui()
    player = None
    try:
        ui.start()
        all_plugins = discover_plugins(PLUGINS_DIR, overrides=settings["plugin_overrides"], log=log_to(ui))
        n = len(open_tables(load_tables(all_plugins, settings, log=log_to(ui)), settings))
        ui.splash_info = (f"New players buy in for [bold]{money(settings['init_balance'])}[/]  ·  "
                          f"{n} table{'s' if n != 1 else ''} open")
        ui.regulars = store.all()
        player = sign_in(ui, store, settings)
        ui.player = player
        lobby_loop(ui, all_plugins, settings, store, player)
    except (KeyboardInterrupt, EOFError):
        if player is not None and settings.get("autosave", True) and player.dirty:
            save_player(ui, store, player, quiet=True)
    finally:
        ui.stop()

    if player is not None:
        ui.print_after(Text("\n  Session Summary", "bold gold1"))
        ui.print_after(Padding(summary_table(player), (1, 2)))
        if player.dirty:
            ui.print_after(Text("  Profile not saved — this visit wasn't kept.", "yellow"))
        else:
            ui.print_after(Text("  Profile saved.", "green"))
        ui.print_after(Text(f"\n  Thanks for playing, {player.name}! Come back soon.\n"))


if __name__ == "__main__":
    main()
