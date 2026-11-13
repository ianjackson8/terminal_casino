#!/usr/bin/env python3
"""
Terminal Casino
Author: Ian Jackson
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from casino.loader import discover_plugins
from casino.session import Player
from casino.tui import esc, make_ui, money, net_text

ROOT = Path(__file__).parent
SETTINGS_FILE = ROOT / "game_settings.json"
PLUGINS_DIR = ROOT / "plugins"
DEFAULTS = {"init_balance": 100.0, "enabled_plugins": [], "plugin_overrides": {}}


def load_settings() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return {**DEFAULTS, **json.load(f)}
    except FileNotFoundError:
        print(f"Missing {SETTINGS_FILE}. Using defaults.")
        return dict(DEFAULTS)
    except json.JSONDecodeError as e:
        print(f"Invalid game_settings.json: {e}")
        sys.exit(1)


def ask_name(ui) -> str:
    while True:
        name = ui.ask("[bold]Your name[/] ([grey62]Enter to take a seat[/])").strip()
        if name:
            return name
        ui.error("Name cannot be empty.")


def summary_table(player: Player) -> Table:
    table = Table.grid(padding=(0, 3))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    table.add_row("Player", Text(player.name, "bold"))
    table.add_row("Bought in", money(player.starting_balance))
    table.add_row("Cashed out", Text(money(player.balance), "bold green"))
    table.add_row("Net", net_text(player.net))
    for game, count in player.games_played.items():
        table.add_row("", Text.assemble((game, "bold"), (f"  ×{count}", "grey62")))
    return table


def run_plugin(ui, plugin, player: Player) -> None:
    '''Hand the terminal to a game, then take it back with the new balance.'''
    balance_before = player.balance
    ui.stop()
    error = None
    try:
        player.balance = float(plugin.run(player.name, player.balance))
    except (KeyboardInterrupt, EOFError):
        player.balance = balance_before
    except Exception as err:
        player.balance = balance_before
        error = err
    finally:
        ui.start()

    if error is not None:
        ui.log(f"[red]{esc(plugin.name)} crashed: {esc(error)}[/]")
        ui.error(f"Error in {plugin.name} — balance restored to {money(balance_before)}.")
        return

    player.record_game(plugin.name)
    delta = player.balance - balance_before
    if delta > 0:
        ui.log(f"[bold]{esc(plugin.name)}[/]: won [green]{money(delta)}[/]")
    elif delta < 0:
        ui.log(f"[bold]{esc(plugin.name)}[/]: lost [red]{money(-delta)}[/]")
    else:
        ui.log(f"[bold]{esc(plugin.name)}[/]: broke even")


def lobby_loop(ui, plugins: list, player: Player) -> None:
    lobby = ui.lobby = SimpleNamespace(plugins=plugins, cursor=0)
    options = []
    if plugins:
        options += [(("up", "k"), "up", ""), (("down", "j"), "down", "Move"), (("enter", " "), "play", "Play")]
        last = min(len(plugins), 9)
        options += [(str(i), str(i), None) for i in range(1, last + 1)]       # hidden: one per digit
        if last > 1:
            options.append(((f"1-{last}",), "", "Quick pick"))                 # shown only, never matches
    options += [("s", "stats", "Stats"), (("q", "esc"), "quit", "Cash out")]

    while True:
        action = ui.choose("[bold]Lobby[/]", options)
        if action == "up":
            lobby.cursor = (lobby.cursor - 1) % len(plugins)
        elif action == "down":
            lobby.cursor = (lobby.cursor + 1) % len(plugins)
        elif action == "stats":
            ui.show_info("Session", summary_table(player))
        elif action == "quit":
            confirm = ui.choose("Cash out and leave the casino?", [("y", "y", "Cash out"), ("n", "n", "Stay")])
            if confirm == "y":
                return
        elif action == "play" or action.isdigit():
            idx = lobby.cursor if action == "play" else int(action) - 1
            if not 0 <= idx < len(plugins):
                continue
            lobby.cursor = idx
            plugin = plugins[idx]
            if player.balance < plugin.min_bet:
                ui.error(f"{plugin.name} needs at least {money(plugin.min_bet)} — you have {money(player.balance)}.")
                continue
            run_plugin(ui, plugin, player)


def main() -> None:
    settings = load_settings()
    ui = make_ui()
    player = None
    try:
        ui.start()
        plugins = discover_plugins(PLUGINS_DIR, enabled=settings["enabled_plugins"],
                                   overrides=settings["plugin_overrides"],
                                   warn=lambda msg: ui.log(f"[yellow]{esc(msg)}[/]"))
        ui.splash_info = (f"Buy-in [bold]{money(settings['init_balance'])}[/]  ·  "
                          f"{len(plugins)} table{'s' if len(plugins) != 1 else ''} open")
        player = Player(name=ask_name(ui), balance=float(settings["init_balance"]))
        ui.player = player
        ui.log(f"Welcome, [bold]{esc(player.name)}[/]. You buy in for [green]{money(player.balance)}[/].")
        lobby_loop(ui, plugins, player)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        ui.stop()

    if player is not None:
        ui.print_after(Text("\n  Session Summary", "bold gold1"))
        ui.print_after(Padding(summary_table(player), (1, 2)))
        ui.print_after(Text(f"\n  Thanks for playing, {player.name}! Come back soon.\n"))


if __name__ == "__main__":
    main()
