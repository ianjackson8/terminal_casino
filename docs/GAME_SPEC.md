# Terminal Casino — Game Plugin Spec

**Status:** Draft v0.4 · 2026-11-12
**Applies to:** any game added under `plugins/` (Slot Machine, AI Blackjack, and future tables)

This document defines what a game must do to plug into Terminal Casino, and how it should look and feel once it's in. Sections marked **MUST** are enforced by the casino or will break things if ignored. **SHOULD** items are house style. Items marked *(proposed)* aren't implemented in the casino yet. See [Open questions](#10-open-questions--proposed-changes).

---

## 1. Responsibilities

| The casino owns | The game owns |
|---|---|
| Lobby, game selection, welcome/cash-out screens | All gameplay, rules, and table UI |
| The player's wallet (one balance across all games) | Taking bets out of, and paying them into, the balance it was handed |
| Session stats (games played, net, balance history) | Its own logs, saves, models, and in-game stats |
| Loading plugins and recovering from crashes | Restoring the terminal before handing control back |

A game never reads or writes the casino's wallet directly. The game gets a balance, plays, and returns a balance.

---

## 2. Packaging

A game is a folder under `plugins/`. It can be either of these:

- **Git-tracked:** its own repo, added as a git submodule (preferred for anything you'll keep developing).
- **Plain folder:** copied straight in, with no git history of its own (fine for small or one-off games).

```
terminal_casino/
└── plugins/
    └── <key>/              # directory name = plugin key (used in game_settings.json)
        ├── plugin.py       # REQUIRED: the adapter the casino loads
        ├── requirements.txt
        └── ...             # the game's own code, unchanged layout
```

- **MUST:** `plugin.py` sits at the root of the plugin directory.
- **MUST:** the key (directory name) is lowercase `snake_case`, e.g. `ai_blackjack`, `slot_machine`.
- **SHOULD:** the game stays runnable on its own (`python play_blackjack.py`). `plugin.py` is a thin adapter, not a fork of the game.

Add a game:

```bash
git submodule add <repo-url> plugins/<key>      # git-tracked game
cp -R ~/path/to/game plugins/<key>              # plain folder
```

New games appear in the lobby automatically, at their default table. Tables are added, edited and switched off on the **Settings** page (§3.5, §6). `enabled_plugins` optionally sets the game order.

### 2.1 Versioning

Every game has a version. `PLUGIN_META["version"]` is the **single source of truth**, whether or not the game is in git.

**All games:**

- **MUST:** declare the version in `PLUGIN_META["version"]` as a full [semver](https://semver.org) string, `"MAJOR.MINOR.PATCH"` (e.g. `"5.0.0"`, not `"v5.0"` or `"5.0"`).
- **MUST:** bump it whenever the game's behaviour changes (see the table below). Two different builds of a game must never share a version.
- **SHOULD:** keep a `CHANGELOG.md` in the game folder with one entry per version.

When to bump:

| Bump | When | Examples |
|---|---|---|
| **MAJOR** | The game's integration with the casino breaks, or the house edge / payouts change | `run()` signature changes; 3:2 blackjack becomes 6:5; save format changes incompatibly |
| **MINOR** | New features that don't change the odds or the contract | New bot strategy, new animation, new settings |
| **PATCH** | Bug fixes and polish only | Fix a split edge case, fix a layout glitch at 80×24 |

**Git-tracked games** also tag each release:

- **SHOULD:** tag the commit that sets the version with an annotated tag named `v` + the version:

  ```bash
  git tag -a v5.0.0 -m "AI Blackjack 5.0.0"
  git push origin v5.0.0
  ```

- **SHOULD:** pin the casino's submodule to a tagged commit rather than an untagged work-in-progress commit. From the casino root, this prints the matching tag:

  ```bash
  git -C plugins/<key> describe --tags --exact-match    # → v5.0.0
  ```

- **MUST:** if a tag exists, it matches `PLUGIN_META["version"]`. A `v5.1.0` tag on a commit whose `plugin.py` says `5.0.0` is a bug.
- **MUST NOT:** move or reuse a tag once it's pushed. A fix is a new PATCH release.

Updating a git-tracked game in the casino:

```bash
cd plugins/<key>
git fetch --tags
git checkout v5.1.0
cd ../..
git add plugins/<key>
git commit -m "Bump <key> to v5.1.0"
```

Updating a plain-folder game: replace the folder's contents and check that `PLUGIN_META["version"]` went up.

The compliance check (§8.1) enforces this. A missing or invalid `version`, or a git tag that contradicts it, stops the game from loading. The lobby and Settings page show each game's version.

---

## 3. The plugin contract

### 3.1 `PLUGIN_META`

A module-level dict:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | `str` | yes | Display name in the lobby, logs, and stats. Short, e.g. "Blackjack". |
| `description` | `str` | yes | One line, about 60 characters or fewer, shown under the name. |
| `min_bet` | `float` | yes | Minimum bet at the game's default table. The lobby blocks entry if the balance is below the table's minimum. |
| `version` | `str` | yes | Semver release, `"MAJOR.MINOR.PATCH"`. The source of truth for the game's version; must match its git tag, if it has one (see §2.1). |
| `author` | `str` | no | Credit line. |
| `rules` | `dict` | no | The table rules the game accepts, so the casino can run it at several tables (see §3.5). Requires `run()` to take `table`. |

The loader falls back to the directory name for `name`, `""` for `description`, and `0.0` for `min_bet`. Don't rely on those fallbacks.

### 3.2 `run()`

```python
def run(player_name: str, balance: float, table: dict | None = None) -> float: ...
```

- **Input:** the player's name and their whole current casino balance. Games that support tables also get `table` (see §3.5). The casino only passes `table` to a `run()` that has a `table` parameter, so two-argument games keep working.
- **Return:** the player's balance when they leave the table, as a `float`.
- **MUST:** return a value `>= 0`. The game must never let the player bet more than they have.
- **MUST:** return only through `return`. Never call `sys.exit()`, `exit()` or `quit()`, or raise `SystemExit`. The casino doesn't catch `SystemExit`, so it would close the whole casino.
- **MUST:** give the player an explicit **leave table** action that ends `run()` and returns the balance.
- **MUST:** be re-entrant. The player can open the same game many times in one session, so don't depend on module-level state left over from a previous call. Reset or rebuild it inside `run()`.

### 3.3 Exits and errors

What the casino does when `run()` ends:

| How `run()` ends | Casino behaviour |
|---|---|
| Returns a number | Wallet set to the returned value; logged as won, lost, or broke even. |
| Raises `KeyboardInterrupt` / `EOFError` | **Balance rolled back** to what it was before the game; nothing recorded. |
| Raises any other `Exception` | Balance rolled back, error shown in the footer and the Casino Floor log. |
| Raises `SystemExit` | Casino exits. **Not allowed** (see 3.2). |

Because Ctrl-C rolls the balance back, any winnings since the game started are lost too. If the game wants Ctrl-C to mean "leave the table", it should catch `KeyboardInterrupt` itself and `return` the current balance.

### 3.4 Money rules

- Balances are dollars as `float`. Bets and payouts may have cents (for example 3:2 blackjack pays $7.50 on a $5 bet).
- **MUST NOT** create money: no rebuys, credit, or free-chip bonuses for the human player inside a game. Topping up the wallet is the casino's job.
- **MUST NOT** load a saved balance for the human player when running as a plugin. If the game has its own save/load, turn it off, or only use it for non-money state, in plugin mode.
- Bots and AI opponents may have their own bankrolls. Only the human player's balance crosses the plugin boundary.
- Single human seat: the casino has one player. Multi-seat games seat `player_name` and may fill other seats with bots.

### 3.5 Tables

Like a real casino floor, one game can be offered at several **tables**, e.g. a $5 table, a high-roller table, or a single-deck table with different rules. Tables are **configured by the casino** (§6): the operator creates, duplicates and edits them on the Settings page. A game never defines tables itself. Its job is to **declare which rules it accepts**, then **play by the table it's handed**.

Every game gets one table automatically, its *default table*: the `PLUGIN_META` minimum bet, no maximum, and default rules. A game whose `run()` has no `table` parameter only ever has that one table.

**Declaring rules:** `PLUGIN_META["rules"]` maps each rule name (`snake_case`) to a spec:

| Key | Required | Meaning |
|---|---|---|
| `type` | yes | `"int"`, `"float"`, `"bool"` or `"choice"` |
| `label` | yes | Short name shown in the lobby and Settings, e.g. `"Decks"` |
| `default` | yes | Value used when a table doesn't set this rule. Must itself be valid. |
| `choices` | for `choice` | List of allowed values, e.g. `["3:2", "6:5"]` |
| `min`, `max` | no | Bounds for `int` / `float` |
| `description` | no | One-line hint shown in the table editor |

```python
PLUGIN_META = {
    ...,
    "rules": {
        "num_decks": {"type": "int", "label": "Decks", "default": 6, "min": 1, "max": 8},
        "blackjack_payout": {"type": "choice", "label": "Blackjack pays", "choices": ["3:2", "6:5"], "default": "3:2"},
        "dealer_hits_soft_17": {"type": "bool", "label": "Dealer hits soft 17", "default": False},
    },
}
```

**The `table` argument** the casino passes to `run()`:

```python
{
    "id": "bj_high_roller",       # stable id; don't rely on its format
    "name": "High Roller",        # show it in the game's header
    "min_bet": 100.0,
    "max_bet": 5000.0,            # or None for no maximum
    "rules": {"num_decks": 2, "blackjack_payout": "3:2", "dealer_hits_soft_17": False},
}
```

`rules` always contains **every** declared rule, with defaults filled in, and the values are already validated against the spec.

- **MUST:** enforce `min_bet <= bet <= max_bet` (and, as always, `bet <= balance`). If the player can't cover `min_bet`, end the visit and return the balance.
- **MUST:** apply every value in `rules`. Table rules take precedence over the game's own settings file for the length of the visit.
- **MUST:** honour every rule it declares. Don't declare a rule the game ignores.
- **MUST NOT:** write table settings back to the game's own files.
- **SHOULD:** show the table name and limits on screen, e.g. "High Roller · $100–$5,000" in the header.
- Adding a rule is a MINOR version bump. Removing or renaming one is MAJOR, because tables configured with it will stop opening.

---

## 4. Runtime environment

### 4.1 Terminal handover

Before `run()`, the casino stops its full-screen display, leaves the alternate screen, and puts the terminal back into normal (line-buffered, echoing) mode. The game gets a clean terminal.

- **MUST:** put the terminal back the same way before returning, **including on exceptions**: leave the alternate screen, restore `termios` settings, show the cursor, and stop any `rich.live.Live`. Use `try/finally`.
- **MUST:** stop or join any background threads (draw loops, timers) before returning.
- **SHOULD NOT:** print to the terminal after tearing down the game's own UI. Anything printed then is hidden behind the lobby straight away. Put end-of-game summaries inside the game's UI, for example on a "Results" screen before leaving.

### 4.2 Paths

The casino runs from its own root, so the working directory is **not** the game's directory.

- **MUST:** resolve every file path from the plugin's own location:

  ```python
  HERE = Path(__file__).resolve().parent
  settings = json.loads((HERE / "game_settings.json").read_text())
  ```

- **MUST:** write logs, saves, and models inside the plugin directory, never the casino root.

### 4.3 Imports

The casino loads `plugin.py` as the module `plugins.<key>.plugin`. The plugin's own directory is **not** on `sys.path`.

- `from . import mygame` works in `plugin.py`, because `plugins/<key>` resolves as a namespace package.
- A plain `import mygame` fails, and so do absolute imports *between* the game's own modules, e.g. `play_blackjack.py` doing `from tui import ...`.

Recommended approach: put the plugin directory on `sys.path` inside `run()`, then import lazily:

```python
def run(player_name, balance):
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from play_blackjack import ...
```

- **SHOULD:** avoid generic top-level module names (`tui`, `utils`, `strategy`, `config`). `sys.modules` is shared by all games, so two games each with a `tui.py` will collide, and the second one gets the first one's module. Prefix them (`bj_tui.py`) or keep the game inside a package (`blackjack/tui.py`).
- **SHOULD:** never import `casino.*` from a game. Games must stay usable on their own. *(See open question on a shared UI kit.)*

### 4.4 Startup cost

The casino runs every `plugin.py` at launch, before the lobby appears.

- **MUST:** keep `plugin.py`'s top level cheap. It should only define `PLUGIN_META` and `run`. Import heavy dependencies (PyTorch, NumPy, Matplotlib) **inside** `run()`.
- **MUST NOT:** do any I/O, prompts, or printing at import time.

### 4.5 Dependencies

- List them in the game's own `requirements.txt`. For now, install each enabled plugin's requirements by hand. *(proposed)* A casino setup script that installs them all.
- `rich` is guaranteed to be available because the casino depends on it.
- Pin nothing tighter than needed. All games share one environment.

---

## 5. Design guidelines

Games should feel like rooms in the same building. The reference implementation is `casino/tui.py`, which itself follows AI Blackjack's `tui.py`.

### 5.1 Layout

Full-screen Rich `Live` (`screen=True`), split into:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ♠ ♥ G A M E   T I T L E ♦ ♣                      Ian   $125   Round 4      ┃  header, size 3
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
╭─ Table ──────────────────────────────────────────╮╭─ Side panel ────────────╮
│                                                  ││ scores / log            │  body
│               green felt play area               ││ (42 wide; 46 at ≥150)   │
│                                                  ││                         │
╰──────────────────────────────────────────────────╯╰─────────────────────────╯
╭───────────────────────────────────────────────────────────────────────────────╮
│ Your move    H  Hit   S  Stand   D  Double   L  Leave table                   │  footer, size 4
╰─────────────────────────────────────────────────────────── Ctrl-C quits ──────╯
```

- **Header:** `box.HEAVY`, border `gold1`. Spaced-out title in `bold gold1` between suit symbols on the left. Player name, balance, and game state (round, shoe, spins…) on the right.
- **Body:** play area on felt. The side column appears only at width ≥ 100. Below that, a log strip about 7 rows tall sits under the play area.
- **Footer:** the current prompt plus key-caps. A one-line error flash goes above the prompt.
- **Overlays** (help, stats, settings) replace the play area in a `box.DOUBLE` panel with a `gold1` border, and close on any key.
- **Minimum size:** must stay usable at **80×24**. Switch to compact rendering (smaller art, fewer panels) instead of overflowing.

### 5.2 Palette

| Use | Style |
|---|---|
| Felt background / border | `on #0b3d2e` / `green4` |
| Titles, active seat, cursor `▶`, key-caps | `gold1` (key-caps: `bold black on gold1`) |
| Neutral panel borders | `grey42` (inactive `grey35`–`grey50`) |
| Secondary / hint text | `grey62` (dimmer: `grey50`) |
| Money, wins | `bold green` |
| Losses, errors | `bold red` / `red3` |
| Bots / AI elements | `cyan` |
| Selected row background | `on grey23` |
| Result badges | `bold black on gold1` (jackpot/blackjack), `on green3` (win), `on grey70` (push), `bold white on red3` (lose/bust) |

Chip colours follow casino convention: $1 white/grey, $5 red, $25 green, $100 black, $500 purple, $1K orange.

### 5.3 Text and numbers

- Money: `$1,250` for whole dollars, `$7.50` otherwise. Signed: `+$25` / `-$10`. Copy `money()` / `signed_money()` from `casino/tui.py`.
- Escape player-supplied text with `rich.markup.escape` before putting it in markup.
- Keep the voice short and table-side: "Place your bet", "Dealer stands on 17", "Leave table".

### 5.4 Controls

Single keypress input (cbreak mode); no "type a command and press Enter" except for amounts and names.

| Key | Meaning everywhere |
|---|---|
| `↑` `↓` / `k` `j` | Move cursor |
| `↵` / `Space` | Confirm / default action (show `(↵)` next to the default) |
| `Esc` / `Q` | Back out of a menu; at the table, **leave table** (confirm if a bet is live) |
| `Tab` | Cycle the side panel (scores ↔ log) |
| `?` | Help / rules overlay |
| `1`–`9` | Quick-pick from a numbered list |
| `Ctrl-C` | Hard exit (see §3.3; the casino rolls back) |

Game-specific actions use one memorable letter (`H` hit, `S` stand, `D` double, `P` split…). Always list every live key in the footer.

### 5.5 Feel

- Redraw only when something changes (draw thread plus a dirty flag, capped at about 30 fps). Don't auto-refresh the whole screen at a fixed rate.
- Short animations are welcome (card flip, reel spin) but must stay under about 1 s, and should be skippable or turn-offable in the game's settings.
- Hide information that hasn't been revealed yet: don't show totals or outcomes before the animation that reveals them finishes.
- Fall back to plain `input()` / `print` when stdin or stdout isn't a TTY (tests, pipes).

---

## 6. Game settings

Each game keeps its own `game_settings.json` in its directory for its defaults (decks, payouts, animation…).

The casino's `game_settings.json` holds the casino's settings and its **tables**. It's edited from the Settings page (G in the lobby), or by hand:

```json
{
  "init_balance": 500,
  "autosave": true,
  "allow_rebuy": true,
  "enabled_plugins": ["ai_blackjack", "slot_machine"],
  "tables": [
    {"id": "ai_blackjack", "game": "ai_blackjack", "name": "Standard", "min_bet": 5, "max_bet": 500, "rules": {}},
    {"id": "bj_high_roller", "game": "ai_blackjack", "name": "High Roller", "min_bet": 100, "max_bet": 5000,
     "rules": {"num_decks": 2}},
    {"id": "bj_single_deck", "game": "ai_blackjack", "name": "Single Deck", "min_bet": 10, "max_bet": 500,
     "rules": {"num_decks": 1, "blackjack_payout": "6:5"}}
  ],
  "disabled_tables": ["bj_single_deck"],
  "plugin_overrides": {}
}
```

| Key | Meaning |
|---|---|
| `enabled_plugins` | Optional game order in the lobby. Games not listed follow in folder order. |
| `tables` | Tables per game. `id` is lowercase `snake_case` and unique; `game` is the plugin key; `max_bet` may be `null`; `rules` only lists rules that differ from the game's defaults. A game with no entries here gets its default table. |
| `disabled_tables` | Table ids hidden from the lobby. A game's default table has the plugin key as its id. |

- A table whose `id` is the plugin key is that game's original table. Its stats stay under the plain game name, so adding more tables doesn't split the history.
- A table that fails validation isn't opened, and the reason is logged in the Casino Floor. Causes include an unknown rule, a bad value, `max_bet < min_bet`, a duplicate id, or a game that can't take tables. The game's other tables still open.
- Stats are kept per table ("Blackjack · High Roller") and totalled per game on the Stats page.

*(legacy)* `plugin_overrides` is still read by the loader but not passed to games. Use table `rules` instead.

---

## 7. Reference `plugin.py`

```python
"""Terminal Casino adapter for Coin Flip."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

PLUGIN_META = {
    "name": "Coin Flip",
    "description": "Call it in the air. Pays even money.",
    "min_bet": 1.0,
    "version": "1.2.0",           # semver; if git-tracked, tag the release v1.2.0 (§2.1)


    "rules": {                    # optional: lets the casino run several tables (§3.5)
        "payout": {"type": "choice", "label": "Pays", "choices": ["1:1", "9:10"], "default": "1:1"},
    },
}


def run(player_name: str, balance: float, table: dict | None = None) -> float:
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from coinflip_game import CoinFlipGame        # lazy import: keeps lobby startup fast

    table = table or {"name": PLUGIN_META["name"], "min_bet": PLUGIN_META["min_bet"], "max_bet": None,
                      "rules": {"payout": "1:1"}}
    game = CoinFlipGame(player=player_name, balance=balance, root=HERE, table=table)
    try:
        return game.play()                          # returns when the player picks "Leave table"
    except KeyboardInterrupt:
        return game.balance                         # treat Ctrl-C as leaving, keep the winnings
    finally:
        game.ui.stop()                              # always give the terminal back clean
```

---

## 8. Compliance

### 8.1 Automated check

Run the compliance check before adding a game, and again before each release:

```bash
python -m casino.check ~/code/my_game                 # a game folder anywhere, before adding it
python -m casino.check ~/code/MyGame --key my_game    # if the folder name isn't the key it'll be installed as
python -m casino.check ai_blackjack                   # an installed game, by key
python -m casino.check                                # every installed game
```

Run it from the casino root. It prints a report for each game and a verdict: **Ready to add**, **Can be added with warnings**, or **Not compliant**. The exit code is `1` if any game has errors, so it can run in CI.

**The casino runs the same checks at startup.** A game with **any error is not loaded**. The reason, and the command to run, appear in the Casino Floor log. Warnings don't block a game, but the log line still points you at the check.

| Check | Level | Spec |
|---|---|---|
| `plugin.py` at the folder root; key is lowercase `snake_case` | error | §2 |
| `plugin.py` parses; never calls `sys.exit` / `exit` / `quit` / `os._exit` / `raise SystemExit` | error | §3.2 |
| `PLUGIN_META` is a dict with `name`, `description`, `min_bet` (number ≥ 0) and semver `version` | error | §3.1, §2.1 |
| `name` > 24 chars, `description` > 60 chars, unknown `PLUGIN_META` fields (typos) | warning | §3.1 |
| `run` exists and accepts `(player_name, balance)` | error | §3.2 |
| `rules` (if declared) is well-formed: types, labels, choices, bounds, valid defaults | error | §3.5 |
| `rules` declared but `run()` has no `table` parameter | error | §3.5 |
| Each configured table: valid id (unique), name, `min_bet`, `max_bet >= min_bet`, only declared rules with valid values, game accepts tables *(checked at startup, on save, and by the dev check; a bad table is skipped, not the whole game)* | error | §6 |
| `plugin.py` imports without raising, exiting, printing or calling `input()` | error | §4.4 |
| No heavy modules (PyTorch, NumPy, Matplotlib, pandas…) imported at module level | error | §4.4 |
| Import takes longer than 0.3 s | warning | §4.4 |
| Top-level module names don't shadow the standard library, use `casino`/`plugins`, or clash with another installed game | error | §4.3 |
| Generic top-level module names (`tui`, `utils`, `strategy`…) | warning | §4.3 |
| Git-tracked: a version tag at HEAD matches `version`; `v<version>` isn't on a different commit | error | §2.1 |
| Git-tracked: release isn't tagged; uncommitted changes | warning | §2.1 |
| `requirements.txt` and `CHANGELOG.md` present *(dev check only)* | warning | §4.5, §2.1 |
| Exit calls elsewhere in the game's code, outside `if __name__ == "__main__":` *(dev check only)* | warning | §3.2 |

When two installed games clash on a module name, the game whose folder sorts **later** is the one blocked.

### 8.2 Manual checklist

The automated check can't play the game. Before enabling a game, also confirm:

- [ ] `python -m casino.check <game>` passes with no errors, and any warnings are understood.
- [ ] `version` was bumped from the last version the casino had.
- [ ] If git-tracked: the release tag is pushed to the game's remote.
- [ ] The game opens from the lobby, plays a round, and **Leave table** returns to the lobby with the right balance (check the Stats page records it).
- [ ] Opening the game twice in one session works (no leftover state).
- [ ] Ctrl-C in the middle of a round returns to the lobby with a clean terminal and an intact lobby display.
- [ ] A forced exception inside the game shows the error in the lobby and rolls the balance back.
- [ ] `sys.exit` / `quit` can't be reached from `run()` (follow up any "Exits in game code" warnings).
- [ ] All file reads and writes are relative to the plugin dir; nothing new appears in the casino root.
- [ ] The balance can never go negative, and no money is created for the human player.
- [ ] Usable at 80×24 and at ≥100 columns with the side panel.
- [ ] If it supports tables: a bet below `min_bet` or above `max_bet` is refused, and every declared rule visibly changes play.
- [ ] Footer lists every live key; `Esc`/`Q` leaves; `?` shows the rules.
- [ ] The game still runs on its own outside the casino.

---

## 9. Integration notes for current games

- **Slot Machine:** low effort. Needs `plugin.py` and path fixes; its UI will need restyling to §5.
- **AI Blackjack:** already matches §5 visually. Needs:
  - `quit()` / `sys.exit` replaced with a return path
  - paths resolved from `HERE` (`game_settings.json`, `models/`, `logs/`, `saves/`)
  - generic module names (`tui`, `strategy`, `counter`) prefixed or packaged
  - PyTorch imported lazily
  - the end-of-game `print_after` stats moved inside the UI (§4.1)
  - save/load turned off for the human balance in plugin mode
  - single human seat
  - version string switched from `v5.0` to semver (`5.0.0`) in `PLUGIN_META`, plus an annotated `v5.0.0` tag on the release commit (it's a git repo)

---

## 10. Open questions / proposed changes

1. **Ctrl-C semantics.** Should the casino keep the game's last known balance instead of rolling back? That would need games to report their balance as it changes (e.g. a callback), so rollback is the simpler default for now.
2. **Settings passthrough.** ~~Add a `settings=` keyword~~. Replaced by tables (§3.5); remove `plugin_overrides`.
3. **Explicit exit exception.** Provide `casino.GameExit(balance)` so deeply nested game code can leave without threading a return value up? It would conflict with "games don't import `casino.*`", so the alternative is for games to define their own internal exception and catch it in `plugin.py`.
4. **Richer return value.** Return `{"balance": ..., "rounds": ..., "biggest_win": ...}` so the casino's stats screen can show per-game detail? Stay backwards compatible by still accepting a bare float.
5. **Shared UI kit.** Move the house style (`money`, key-caps footer, header, palette, key reader) into a small standalone package both the casino and the games depend on, instead of copy-paste.
6. **Module isolation.** The loader could run each plugin with a scoped `sys.path` and clear its modules from `sys.modules` afterwards, which would remove the collision rule in §4.3.
7. **Plugin API version.** Add `PLUGIN_META["api"] = 1` so the loader can reject or adapt to older plugins once the contract changes.
