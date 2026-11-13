# Terminal Casino — Game Plugin Spec

**Status:** Draft v0.1 · 2026-11-12
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

Each game lives in its own repo, added as a git submodule:

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
git submodule add <repo-url> plugins/<key>
```

Then list `<key>` in `enabled_plugins` in `game_settings.json`. If that list is empty, every discovered plugin is shown.

---

## 3. The plugin contract

### 3.1 `PLUGIN_META`

A module-level dict:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | `str` | yes | Display name in the lobby, logs, and stats. Short, e.g. "Blackjack". |
| `description` | `str` | yes | One line, about 60 characters or fewer, shown under the name. |
| `min_bet` | `float` | yes | Smallest bet the game accepts. The lobby blocks entry if the balance is below this. |
| `version` | `str` | *(proposed)* | Semver of the game, shown in the stats screen. |
| `author` | `str` | *(proposed)* | Credit line. |

The loader falls back to the directory name for `name`, `""` for `description`, and `0.0` for `min_bet`. Don't rely on those fallbacks.

### 3.2 `run()`

```python
def run(player_name: str, balance: float) -> float: ...
```

- **Input:** the player's name and their whole current casino balance.
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

Each game keeps its own `game_settings.json` in its directory for rules (decks, payouts, animation…).

The casino's `game_settings.json` has a `plugin_overrides` block keyed by plugin key:

```json
{
  "init_balance": 100.0,
  "enabled_plugins": ["slot_machine", "ai_blackjack"],
  "plugin_overrides": {
    "ai_blackjack": { "num_decks": 6, "deal_delay": 0.4 }
  }
}
```

*(proposed)* The loader already stores these as `Plugin.overrides` but doesn't pass them on yet. The plan is to call `run(player_name, balance, settings=overrides)` **only if** the plugin's `run` accepts a `settings` keyword, so existing two-argument plugins keep working. Games would shallow-merge overrides on top of their own file and never write them back.

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
}


def run(player_name: str, balance: float) -> float:
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from coinflip_game import CoinFlipGame        # lazy import: keeps lobby startup fast

    game = CoinFlipGame(player=player_name, balance=balance, root=HERE)
    try:
        return game.play()                          # returns when the player picks "Leave table"
    except KeyboardInterrupt:
        return game.balance                         # treat Ctrl-C as leaving, keep the winnings
    finally:
        game.ui.stop()                              # always give the terminal back clean
```

---

## 8. Acceptance checklist

Before enabling a game in `game_settings.json`:

- [ ] `plugin.py` defines `PLUGIN_META` (name, description, min_bet) and `run(player_name, balance) -> float`.
- [ ] The casino starts quickly with the plugin enabled (no heavy imports at module level).
- [ ] The game opens from the lobby, plays a round, and **Leave table** returns to the lobby with the right balance.
- [ ] Opening the game twice in one session works (no leftover state).
- [ ] Ctrl-C in the middle of a round returns to the lobby with a clean terminal and an intact lobby display.
- [ ] A forced exception inside the game shows the error in the lobby and rolls the balance back.
- [ ] It never calls `sys.exit` / `quit` anywhere reachable from `run()`.
- [ ] All file reads and writes are relative to the plugin dir; nothing new appears in the casino root.
- [ ] No module-name collisions with other enabled plugins.
- [ ] The balance can never go negative, and no money is created for the human player.
- [ ] Usable at 80×24 and at ≥100 columns with the side panel.
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

---

## 10. Open questions / proposed changes

1. **Ctrl-C semantics.** Should the casino keep the game's last known balance instead of rolling back? That would need games to report their balance as it changes (e.g. a callback), so rollback is the simpler default for now.
2. **Settings passthrough.** Add the `settings=` keyword described in §6.
3. **Explicit exit exception.** Provide `casino.GameExit(balance)` so deeply nested game code can leave without threading a return value up? It would conflict with "games don't import `casino.*`", so the alternative is for games to define their own internal exception and catch it in `plugin.py`.
4. **Richer return value.** Return `{"balance": ..., "rounds": ..., "biggest_win": ...}` so the casino's stats screen can show per-game detail? Stay backwards compatible by still accepting a bare float.
5. **Shared UI kit.** Move the house style (`money`, key-caps footer, header, palette, key reader) into a small standalone package both the casino and the games depend on, instead of copy-paste.
6. **Module isolation.** The loader could run each plugin with a scoped `sys.path` and clear its modules from `sys.modules` afterwards, which would remove the collision rule in §4.3.
7. **Plugin API version.** Add `PLUGIN_META["api"] = 1` so the loader can reject or adapt to older plugins once the contract changes.
