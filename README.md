<p align="center">
  <img alt="Terminal Casino: one wallet, every table, right in your terminal" src="docs/assets/brand/banner.svg" width="100%">
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-0B3D2E?style=flat-square&logo=python&logoColor=FFD700">
  <img alt="Built with Rich" src="https://img.shields.io/badge/built%20with-rich-0B3D2E?style=flat-square">
  <img alt="Games: 3" src="https://img.shields.io/badge/games-3%20%C2%B7%20blackjack%20%C2%B7%20roulette%20%C2%B7%20baccarat-FFD700?style=flat-square&labelColor=0B3D2E">
  <img alt="Tables: 7" src="https://img.shields.io/badge/tables-7-FFD700?style=flat-square&labelColor=0B3D2E">
  <img alt="Plugin spec v0.4" src="https://img.shields.io/badge/plugin%20spec-v0.4-D72027?style=flat-square">
</p>

<p align="center">
  <a href="#a-tour">Tour</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#games">Games</a> ·
  <a href="#adding-a-game">Add a game</a> ·
  <a href="docs/GAME_SPEC.md">Plugin spec</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

**Terminal Casino** is a casino floor that runs in your terminal. Pick a table in the lobby, play, and walk back out with your winnings. One wallet follows you to every game, and your profile remembers your bankroll, your stats and every hand you've played.

The games aren't built into the casino. Each one is its own project, added as a plugin. The casino owns the lobby, the wallet and the bookkeeping. A game only has to take a balance, play, and hand a balance back. A compliance checker makes sure it plays by the rules before the casino lets it in.

<picture>
  <img alt="The lobby: three blackjack tables (Standard, High Roller, Single Deck) with their stakes and rules, a wallet panel and the Casino Floor log" src="docs/readme/lobby.svg" width="100%">
</picture>

## What it does

- **Runs a casino floor, not a menu.** A game can be offered at several tables, like a $5 table, a high-roller room and a single-deck variant. Each table has its own stakes and rules.
- **Keeps one wallet across every game.** Your balance moves from table to table, and the casino records every result.
- **Remembers you.** Type your name and you're back where you left off: balance, lifetime stats, history. It autosaves, or you can save by hand.
- **Lets anyone add a game.** Drop a folder into `plugins/`, run the checker, and it's on the floor. Games stay runnable on their own.
- **Lives entirely in the terminal.** It's full-screen and driven by single keys, with card art, chip stacks and a balance chart.

## A tour

### Pull up a chair

<picture>
  <img alt="The welcome screen: chip stacks, dice and a 777 slot reel on green felt, a list of regulars with their balances, and a name prompt" src="docs/readme/welcome.svg" width="100%">
</picture>

Type a name to sit down. Regulars are listed with their balance and when they last played. A returning name, in any capitalisation, picks up their profile. A new name buys in fresh.

### At the table

<picture>
  <img alt="AI Blackjack at the High Roller table: the dealer shows a 9, the player holds A♠ 7♦ for soft 18 with a $200 bet, and the footer offers Hit, Stand, Double, Rules and Leave table" src="docs/readme/blackjack.svg" width="100%">
</picture>

Choosing a table hands the terminal to the game. Here, [AI Blackjack](https://github.com/ianjackson8/ai_blackjack) is playing the High Roller table: 2 decks, no insurance, and bets from $100 to $5,000. The casino passed it those settings. Leave the table and you're back in the lobby with your new balance, logged and saved.

### Tables, configured by the house

<picture>
  <img alt="The table editor for the Single Deck table: name, minimum and maximum bet, and the four blackjack rules (decks, double after split, splits per hand, insurance)" src="docs/readme/table-editor.svg" width="100%">
</picture>

Open **Settings** (`G`) to add, duplicate, edit or close tables. Each game declares the rules it accepts, and the editor offers exactly those: on/off switches, lists to pick from, and numbers with limits. Anything you don't change stays at the game's default. The game then enforces the table's limits and rules.

### Stats

<picture>
  <img alt="The Stats overview: lifetime numbers, this visit's numbers, and a balance chart that dips and then climbs" src="docs/readme/stats.svg" width="100%">
</picture>

<picture>
  <img alt="The Stats Games tab: Blackjack totals with a row for each table, showing played, wins, losses, win rate, net, best, worst and time" src="docs/readme/stats-games.svg" width="100%">
</picture>

Three tabs: **Overview** (lifetime and this visit, plus a balance chart), **Games** (per table, totalled per game), and **History** (every result, newest first).

### A bouncer for plugins

<picture>
  <img alt="python -m casino.check ai_blackjack: thirteen passing checks and a 'Ready to add' verdict" src="docs/readme/check.svg" width="100%">
</picture>

`python -m casino.check` tests a game against the [plugin spec](docs/GAME_SPEC.md) before it goes in. The casino runs the same checks at startup and won't open a game that fails. It checks:

- the game's metadata and its `run()` signature
- that `plugin.py` imports without printing, prompting or loading heavy libraries
- that it never calls `sys.exit`
- module names that would clash with another game or the standard library
- that its version matches its git tag
- every table configured for it

## How it works

```mermaid
flowchart LR
  you(["🧑 Player"]) --> lobby

  subgraph casino ["Terminal Casino"]
    lobby["Lobby<br/>tables by game"]
    wallet[("Profile<br/>balance · stats · history")]
    settings["Settings<br/>tables · rules · limits"]
    check{{"Compliance<br/>check"}}
    lobby <--> wallet
    settings --> lobby
  end

  subgraph plugins ["plugins/"]
    bj["ai_blackjack<br/>v5.2.0"]
    next["your game"]
  end

  check -. "at startup" .-> bj
  check -. "at startup" .-> next
  lobby == "run(name, balance, table)" ==> bj
  bj == "balance" ==> lobby
```

| Piece | What it does |
|---|---|
| [`main.py`](main.py) | Sign-in, lobby loop, hands the terminal to a game and takes it back |
| [`casino/tui.py`](casino/tui.py) | Full-screen Rich UI: header, felt, wallet, Casino Floor log, key-cap footer |
| [`casino/tables.py`](casino/tables.py) | Tables: build them from config, validate rules and stakes |
| [`casino/profiles.py`](casino/profiles.py) | One JSON profile per player in `profiles/`; per-table stats and history |
| [`casino/pages.py`](casino/pages.py) | The Stats and Settings pages, and the table editor |
| [`casino/compliance.py`](casino/compliance.py) | Checks a game against the spec; used at startup and by `casino.check` |
| [`casino/loader.py`](casino/loader.py) | Finds games in `plugins/` and loads the ones that pass |

**The contract** is two things in a game's `plugin.py`:

```python
PLUGIN_META = {"name": "Blackjack", "description": "Beat the dealer to 21.", "min_bet": 1.0, "version": "5.2.0",
               "rules": {"num_decks": {"type": "int", "label": "Decks", "default": 6, "min": 1, "max": 8}}}

def run(player_name: str, balance: float, table: dict | None = None) -> float:
    ...   # play until the player leaves, then return their balance
```

## Quickstart

```bash
git clone --recurse-submodules https://github.com/ianjackson8/terminal_casino.git
cd terminal_casino
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # the casino itself only needs rich
pip install torch numpy             # for AI Blackjack
python3 main.py
```

> [!TIP]
> Already cloned without submodules? Run `git submodule update --init` to fetch the games.

### Controls

| Key | Lobby | Everywhere |
|---|---|---|
| `↑` `↓` / `k` `j` | Move between tables | Move |
| `↵` or `1`–`9` | Sit down at a table | Confirm |
| `S` | Stats | |
| `G` | Settings (tables, rules, profiles) | |
| `R` | Rebuy, when you can't afford any table | |
| `Q` / `Esc` | Cash out | Back |
| `Ctrl-C` | Cash out (and autosave) | |

## Games

| Key | Game | Version | Tables | Source | Extra requirements |
|---|---|---|---|---|---|
| `ai_blackjack` | Blackjack | 5.2.0 | Standard · High Roller · Single Deck | [ai_blackjack](https://github.com/ianjackson8/ai_blackjack) (submodule) | `pip install torch numpy` |
| `roulette` | Roulette | 1.0.0 | European · American · High Roller · La Partage | local repo (submodule, no remote) | — |
| `baccarat` | Baccarat | 1.0.0 | Punto Banco (default table) | local repo (submodule, no remote) | — |

## Adding a game

1. **Build it to the [plugin spec](docs/GAME_SPEC.md).** Add a `plugin.py` with `PLUGIN_META` and `run()`. Optionally declare rules so the casino can run it at several tables.
2. **Check it** from anywhere, before it's in the casino:
   ```bash
   python3 -m casino.check ~/code/my_game
   ```
3. **Add it** as a submodule (`git submodule add <url> plugins/my_game`) or as a plain folder.
4. **Open tables** for it in Settings (`G`), or in `game_settings.json`:
   ```json
   {"id": "bj_high_roller", "game": "ai_blackjack", "name": "High Roller",
    "min_bet": 100, "max_bet": 5000, "rules": {"num_decks": 2, "allow_insurance": false}}
   ```

## Project layout

```
main.py                 entry point: sign-in, lobby, running tables
game_settings.json      casino settings and tables
casino/                 the casino: UI, tables, profiles, pages, loader, compliance check
plugins/<key>/          one folder per game (git submodule or plain folder)
profiles/               saved players (gitignored)
docs/GAME_SPEC.md       the plugin spec
docs/readme/            README screenshots, generated by scripts/readme_screens.py
scripts/                readme_screens.py: re-renders those screenshots from the real UI
```

The screenshots above are real renders of the UI, not mock-ups. Regenerate them after a UI change with `python3 scripts/readme_screens.py`.

## Roadmap

| | Milestone |
|---|---|
| ✅ | Plugin loader and full-screen lobby |
| ✅ | Profiles, saving, rebuys, stats and settings |
| ✅ | Plugin spec and compliance check, enforced at startup |
| ✅ | AI Blackjack, the first game |
| ✅ | Several tables per game, with stakes and rules set by the house |
| ⏭️ | Next: slot machine as the second game |
| ✅ | Roulette: European and American wheels, la partage |
| ✅ | Baccarat: Punto Banco with Big Road and Bead Plate scoreboards |
| ⬜ | More games: poker, craps… |
| ⬜ | Remove the legacy `plugin_overrides` setting; richer per-game results in Stats |

<p align="center">
  <sub>♠ ♥ ♦ ♣ &nbsp; Play money only. No real money is wagered, won or lost. &nbsp; ♣ ♦ ♥ ♠</sub>
</p>
