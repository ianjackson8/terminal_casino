# terminal_casino

A terminal casino lobby that plugs independent games into one shared wallet, with player profiles, stats and saves.

```bash
pip install -r requirements.txt
python3 main.py
```

## Adding a game

Games live in `plugins/<key>/` (a git submodule or a plain folder) and follow [docs/GAME_SPEC.md](docs/GAME_SPEC.md).

Check a game before adding it. Non-compliant games are blocked at startup.

```bash
python3 -m casino.check path/to/game     # or a plugin key, or no argument for all installed games
```
