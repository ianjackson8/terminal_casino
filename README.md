# terminal_casino

A terminal casino lobby that plugs independent games into one shared wallet, with player profiles, stats and saves.

```bash
git clone --recurse-submodules https://github.com/ianjackson8/terminal_casino.git   # or: git submodule update --init
pip install -r requirements.txt
python3 main.py
```

## Games

| Key | Game | Version | Source | Extra requirements |
|---|---|---|---|---|
| `ai_blackjack` | Blackjack | 5.1.0 | [ai_blackjack](https://github.com/ianjackson8/ai_blackjack) (submodule) | `pip install torch numpy` |

## Adding a game

Games live in `plugins/<key>/` (a git submodule or a plain folder) and follow [docs/GAME_SPEC.md](docs/GAME_SPEC.md).

Check a game before adding it. Non-compliant games are blocked at startup.

```bash
python3 -m casino.check path/to/game     # or a plugin key, or no argument for all installed games
```
