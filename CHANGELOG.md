# Changelog

All notable changes to Terminal Casino. Versions follow [semver](https://semver.org). Each game is
versioned on its own (see the table under each release); `docs/GAME_SPEC.md` has its own draft number.

## [1.0.0-beta.1] — 2026-11-13

The first versioned release: a beta of what 1.0 will be. Everything below works and is tested. The
plugin spec is still a draft, so the contract between the casino and its games may still change
before 1.0.

### The casino
- **Lobby:** a carousel of games, with the current game in a big gold-framed card with its own art
  and its neighbours dimmed either side. `←` `→` slides, `↑` `↓` picks one of the game's tables,
  `↵` sits down.
- **One wallet:** one balance across every game. Each visit is logged on the Casino Floor and
  recorded in your stats.
- **Profiles:**
  - Each player has a profile, matched by name in any capitalisation.
  - Saves automatically, or by hand with autosave off.
  - Rebuys when you can't afford any table.
  - Regulars are listed on the welcome screen.
- **Tables:**
  - Any game can run at several tables, each with its own stakes and rules.
  - The house adds, duplicates, edits and closes tables on the Settings page.
  - Games declare the rules they accept, and the casino validates every table against them.
- **Stats:**
  - **Overview:** lifetime and this visit, with a balance chart.
  - **Games:** results per table, with totals per game.
  - **History:** every result, newest first.
- **Compliance check:**
  - Developers run `python -m casino.check`, and the casino runs the same checks at startup.
  - A game that breaks the spec isn't loaded.
  - A bad table is skipped without taking its game down.
- **House style:** every game follows the same look and controls (plugin spec §5):
  - gold header with the table and its limits
  - cards that slide in and flip
  - chip stacks
  - WIN / LOSE / PUSH badges by net result
  - `?` rules, `Q` to leave, and a session summary
  - skippable animations
  - every game usable at 80×24

### Games in this release

| Game | Version | Tables |
|---|---|---|
| Blackjack (AI Blackjack) | 5.2.0 | Standard · High Roller · Single Deck |
| Roulette | 1.2.0 | European · American · High Roller · La Partage |
| Baccarat | 1.1.0 | Main table (Punto Banco) |
| Craps | 1.1.0 | Standard · High Roller · 10x Odds |
| Slots | 1.0.1 | Main Floor · High Limit · Single Line |
| Texas Hold'em | 1.0.2 | $1/$2 No-Limit · $5/$10 Pot-Limit · Heads-Up High Roller |

### Developer tools
- `scripts/readme_screens.py` regenerates every README screenshot from the real UI.
- `scripts/game_review.py` plays a game in an emulated terminal to review its look, animations and
  returned balance (`pip install -r requirements-dev.txt`).

### Known limitations
- **Five games can't be downloaded yet:** Roulette, Baccarat, Craps, Slots and Texas Hold'em are
  submodules pointing at local folders, so a clone from GitHub only gets Blackjack. Publishing them
  is the main item left for 1.0.
- **Plugin spec:** it's a draft (v0.5). It will be frozen at 1.0.
- **Legacy setting:** `plugin_overrides` is still read but not passed to games. Table rules replace
  it.

[1.0.0-beta.1]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0-beta.1
