# Changelog

All notable changes to Terminal Casino. Versions follow [semver](https://semver.org). Each game is
versioned on its own (see the table under each release); `docs/GAME_SPEC.md` has its own version.

## [1.0.0] — 2026-11-19

The first stable release.

### Plugin spec v1.0, frozen
- **A stable contract:** a game that meets spec v1.0 keeps working in every 1.x release. Later 1.x
  specs may only add optional things; anything that would break a compliant game waits for 2.0.
- **Cleanups:** the open questions are now "Ideas for later versions" and aren't part of the
  contract. The integration notes for the first two games are gone, since both games shipped.

### Removed
- **`plugin_overrides`:** the setting from before tables, which hadn't been passed to games since
  tables replaced it. Old `game_settings.json` files still load; the key is dropped when the
  settings are next saved. `discover_plugins()` no longer takes an `overrides` argument.

### Games in this release
Unchanged from 1.0.0-beta.4: Blackjack 5.2.0, Roulette 1.2.0, Baccarat 1.1.0, Craps 1.1.0,
Slots 1.1.1 and Texas Hold'em 1.0.2.

## [1.0.0-beta.4] — 2026-11-19

### The loan shark
- **No more rebuys:** when you can't afford any table, Vinnie "The Vig" offers a $500 loan. You owe
  $600 (a 20% fee), due in 10 rounds; a round is one visit to a table.
- **He escalates:** a nod from the bar, then reminders as the due date gets close, then threats.
  Every round past the due date adds 10% compound interest. At ten rounds late his boys take your
  chips toward the debt.
- **Paying back:** `P` in the lobby pays all or part of the debt. Taking another loan while you owe
  adds to the debt and keeps the original due date. He stops lending at four loans' worth of debt.
- **Debt is a loss:** lifetime and per-visit net subtract what you owe. The wallet, Stats and the
  session summary show the debt; History lists loans, repayments and collections.
- **Settings:** "Allow rebuys" is now "Loan shark"; new `loan_amount` (500) and `loan_rounds` (10).
  Existing profiles load unchanged, and their old rebuys stay in their buy-in.

### Games in this release
Unchanged from 1.0.0-beta.3: Blackjack 5.2.0, Roulette 1.2.0, Baccarat 1.1.0, Craps 1.1.0,
Slots 1.1.1 and Texas Hold'em 1.0.2.

## [1.0.0-beta.3] — 2026-11-13

### Games ship with the casino
- **One download:** each release now has `terminal-casino-<version>.zip`, the casino with every game
  installed. Download it, unzip it and run `python3 main.py`.
- **Clones install games on first launch:** the casino downloads its release's games bundle
  (`games-<version>.tar.gz`, about 0.5 MB), checks it against the checksum in `games.lock`, and
  unpacks it into `plugins/`. Offline, it carries on with what it has and tries again next time.
- **No GitHub repo per game:** games stay in their own repos, local or remote, and the casino
  records which tagged version of each it ships in `games.lock`. The git submodules are gone, and
  game code is no longer stored in the casino's git history.
- **`scripts/games.py`:**
  - `set` locks a game at a new tag (or adds a game, with `--source`).
  - `sync` rebuilds `plugins/` from the lock.
  - `release` builds the reproducible bundle, records its checksum, then commits, tags, pushes and
    publishes both downloads.
- **Safe installs:**
  - **Checksum:** a bundle is only unpacked after its checksum matches.
  - **Contents:** absolute paths, `..` and links are refused.
  - **Your data:** upgrades keep each game's `logs/` and `saves/`.
  - **Your checkouts:** a game folder the casino didn't install is never replaced.
- **Plugin spec v0.6:** §2 and the new §2.2 describe the lock file and the bundles.

### Games in this release
Unchanged from 1.0.0-beta.2: Blackjack 5.2.0, Roulette 1.2.0, Baccarat 1.1.0, Craps 1.1.0,
Slots 1.1.1 and Texas Hold'em 1.0.2.

## [1.0.0-beta.2] — 2026-11-13

### Games
- **Slots 1.1.1: four machines instead of one.** A new `machine` table rule picks the cabinet. Each
  machine has its own art, mechanics and pay table:
  - **Diamond Sevens:** the original 5-reel, 20-line machine with free spins.
  - **Gem Mine:** 5×4 reels with 1,024 ways. Cascading wins raise the multiplier ×1 → ×5.
  - **Brass Bell:** a 3-reel mechanical with a lever and 2× wilds.
  - **Night Sky:** walking star wilds that respin and merge into multipliers.

  A cascade or respin chain is paced as one moment of about 4 s however long it is, and is judged as
  one spin. The payback is exact or measured and tested per machine.
- **Craps 1.1.0:**
  - **Layout:** laid out like a real craps table, with number boxes, the Come and Don't Come bars,
    the Field, the Pass Line and a props panel.
  - **New bet:** C & E.
  - **The throw:** the dice are flung onto the felt, hit the back wall, bounce and tumble to a stop.

### Casino
- **New tables:** Gem Mine ($1–$100), Brass Bell ($1–$50, 92%) and Night Sky ($1–$200, 97%), for 18
  tables in all.
- **Carousel art:** each game in the lobby has its own card art, including Craps, Slots and Hold'em.
- **README:** the four slot machines, with a Gem Mine cascade screenshot, and the new Craps table.

### Games in this release

| Game | Version |
|---|---|
| Blackjack (AI Blackjack) | 5.2.0 |
| Roulette | 1.2.0 |
| Baccarat | 1.1.0 |
| Craps | 1.1.0 |
| Slots | 1.1.1 |
| Texas Hold'em | 1.0.2 |

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
  submodules pointing at local folders, so a clone from GitHub only gets Blackjack. Fixed in
  1.0.0-beta.3, which ships the games with the release.
- **Plugin spec:** it's a draft (v0.5). It will be frozen at 1.0.
- **Legacy setting:** `plugin_overrides` is still read but not passed to games. Table rules replace
  it.

[1.0.0]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0
[1.0.0-beta.4]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0-beta.4
[1.0.0-beta.3]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0-beta.3
[1.0.0-beta.2]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0-beta.2
[1.0.0-beta.1]: https://github.com/ianjackson8/terminal_casino/releases/tag/v1.0.0-beta.1
