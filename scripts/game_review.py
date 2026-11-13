#!/usr/bin/env python3
'''
Play a game the way a person would, in an emulated terminal, to review how it looks and flows.

Runs plugins/<key> (or the whole casino) in a pseudo-terminal, emulates the screen with pyte,
sends a scripted sequence of keys, and reports what was on screen after each step. Steps can be
"filmed" to time an animation (how long the screen keeps changing after a key). Frames can be
saved as PNGs (needs Google Chrome) to compare a new game side by side with the reference game.

    pip install -r requirements-dev.txt

    python scripts/game_review.py ai_blackjack --keys "enter:4:film,h:2:film,s:5,esc,y"
    python scripts/game_review.py roulette --table American --size 80x24 --keys "enter,s:6:film,q,x"
    python scripts/game_review.py casino --keys "Alex,enter:2,right:1:film,enter:4" --png out/

Key tokens are comma-separated: KEY[:WAIT_SECONDS][:film]. KEY is a name (enter, esc, tab, space,
backspace, up, down, left, right, ctrl-c) or literal text. Default wait is 0.8 s.

Author: Ian Jackson
'''

from __future__ import annotations

import argparse
import fcntl
import html
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path

try:
    import pyte
except ImportError:                                   # dev-only dependency
    sys.exit("game_review needs pyte: pip install -r requirements-dev.txt")

ROOT = Path(__file__).resolve().parent.parent
KEYS = {"enter": b"\r", "esc": b"\x1b", "tab": b"\t", "space": b" ", "backspace": b"\x7f",
        "up": b"\x1b[A", "down": b"\x1b[B", "right": b"\x1b[C", "left": b"\x1b[D", "ctrl-c": b"\x03"}
ANSI = {"black": "#1e1e1e", "red": "#cd3131", "green": "#0dbc79", "brown": "#e5e510", "yellow": "#e5e510",
        "blue": "#2472c8", "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5"}
CHROME = next((p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                           shutil.which("google-chrome") or "", shutil.which("chromium") or "") if p and Path(p).exists()), None)


def find_table(game: str, name: str | None) -> dict | None:
    '''A table from game_settings.json by name, or None for the game's default table.'''
    if not name:
        return None
    tables = json.loads((ROOT / "game_settings.json").read_text()).get("tables") or []
    for t in tables:
        if t.get("game") == game and t.get("name", "").lower() == name.lower():
            return {"id": t["id"], "name": t["name"], "min_bet": t["min_bet"], "max_bet": t.get("max_bet"),
                    "rules": t.get("rules") or {}}
    sys.exit(f"No table named {name!r} for {game} in game_settings.json")


class Session:
    '''One game (or the whole casino) running in an emulated terminal.'''

    def __init__(self, target: str, table: dict | None = None, cols: int = 140, rows: int = 40,
                 balance: float = 500.0, player: str = "Alex", python: str = sys.executable):
        if target == "casino":
            argv = [python, "main.py"]
        else:
            code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import plugin; "
                    "t = json.loads(sys.argv[2]); "
                    "r = plugin.run(sys.argv[3], float(sys.argv[4]), **({'table': t} if t else {})); "
                    "print('RETURNED', r)")
            argv = [python, "-c", code, str(ROOT / "plugins" / target), json.dumps(table), player, str(balance)]
        self.cols, self.rows = cols, rows
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(ROOT)
            os.environ.update(TERM="xterm-256color", COLORTERM="truecolor")
            os.execv(python, argv)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.raw = b""
        self.frames: list[tuple[float, str, str]] = []      # (seconds since start, name, html)
        self.exited = False
        self.t0 = time.time()

    def pump(self, seconds: float, film: str | None = None, every: float = 0.05) -> None:
        '''Read output for `seconds`; when filming, snapshot the screen every `every` seconds.'''
        end, nxt = time.time() + seconds, time.time()
        while time.time() < end and not self.exited:
            if select.select([self.fd], [], [], 0.01)[0]:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    self.exited = True
                    break
                self.raw += data
                self.stream.feed(data)
            if film and time.time() >= nxt:
                self.snap(f"{film}-{len(self.frames):03d}")
                nxt = time.time() + every

    def send(self, key: str, wait: float = 0.8, film: str | None = None) -> bool:
        if self.exited:
            return False
        try:
            os.write(self.fd, KEYS.get(key, key.encode()))
        except OSError:
            self.exited = True
            return False
        self.pump(wait, film)
        return True

    def text(self) -> str:
        return "\n".join(line.rstrip() for line in self.screen.display)

    def snap(self, name: str) -> None:
        def colour(c, fallback):
            if c in (None, "default"):
                return fallback
            return ANSI.get(c) or (f"#{c}" if len(c) == 6 else fallback)
        rows = []
        for y in range(self.rows):
            line = self.screen.buffer[y]
            cells = []
            for x in range(self.cols):
                ch = line[x]
                fg, bg = colour(ch.fg, "#d4d4d4"), colour(ch.bg, "#1e1e1e")
                if ch.reverse:
                    fg, bg = bg, fg
                weight = ";font-weight:bold" if ch.bold else ""
                cells.append(f'<span style="color:{fg};background:{bg}{weight}">{html.escape(ch.data or " ")}</span>')
            rows.append("".join(cells))
        self.frames.append((round(time.time() - self.t0, 2), name, "<br>".join(rows)))

    def returned(self) -> str | None:
        found = re.findall(rb"RETURNED ([\d.]+)", self.raw)
        return found[-1].decode() if found else None

    def close(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def animation_timing(frames, prefix: str) -> tuple[int, float]:
    '''(number of distinct screens, seconds until the screen stopped changing) for a filmed step.'''
    strip = lambda h: re.sub(r"<[^>]+>", "", h)                    # noqa: E731
    shots = [(t, strip(body)) for t, name, body in frames if name.startswith(prefix)]
    if not shots:
        return 0, 0.0
    changes, prev = [], None
    for t, body in shots:
        if body != prev:
            changes.append(t)
        prev = body
    return len(changes), round(changes[-1] - shots[0][0], 2)


def save_png(frames, out: Path, cols: int, rows: int) -> list[Path]:
    if CHROME is None:
        print("  (no Chrome found: PNGs skipped)")
        return []
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for _, name, body in frames:
        page = out / f"{name}.html"
        page.write_text(f'<html><body style="margin:0;background:#1e1e1e"><div style="font:14px/17px Menlo,monospace;'
                        f'white-space:pre;padding:8px">{body}</div></body></html>')
        png = out / f"{name}.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={int(cols * 8.43) + 16},{rows * 17 + 16}", f"--screenshot={png}",
                        page.resolve().as_uri()], capture_output=True)
        page.unlink()
        saved.append(png)
    return saved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="a plugin key, or 'casino' for the whole app")
    ap.add_argument("--keys", default="", help="comma-separated KEY[:WAIT][:film] steps")
    ap.add_argument("--table", help="table name from game_settings.json (default: the game's default table)")
    ap.add_argument("--size", default="140x40", help="terminal COLSxROWS (default 140x40)")
    ap.add_argument("--balance", type=float, default=500.0)
    ap.add_argument("--start-wait", type=float, default=3.0, help="seconds to let the game start")
    ap.add_argument("--png", type=Path, help="save a PNG of each step (and filmed frames) into this folder")
    ap.add_argument("--quiet", action="store_true", help="don't print the screen after each step")
    ap.add_argument("--python", default=sys.executable, help="interpreter to run the game with")
    args = ap.parse_args()

    cols, rows = (int(n) for n in args.size.lower().split("x"))
    table = None if args.target == "casino" else find_table(args.target, args.table)
    s = Session(args.target, table, cols, rows, args.balance, python=args.python)
    try:
        s.pump(args.start_wait)
        s.snap("00-start")
        if not args.quiet:
            print(f"===== start\n{s.text()}")
        films = []
        for i, token in enumerate(t for t in args.keys.split(",") if t):
            parts = token.split(":")
            key = parts[0]
            wait = float(parts[1]) if len(parts) > 1 and parts[1] else 0.8
            film = f"film{i + 1:02d}" if "film" in parts[2:] else None
            if not s.send(key, wait, film):
                print(f"===== the game exited before step {i + 1} ({key!r})")
                break
            s.snap(f"{i + 1:02d}-{re.sub(r'[^a-z0-9]+', '_', key.lower())}")
            if film:
                films.append((key, film))
            if not args.quiet:
                print(f"===== after {key!r}\n{s.text()}")
        s.pump(1.0)
        for key, film in films:
            n, secs = animation_timing(s.frames, film)
            print(f"animation after {key!r}: {n} distinct frames over {secs} s")
        print(f"returned balance: {s.returned() or '(still running)'}")
        if args.png:
            saved = save_png(s.frames, args.png, cols, rows)
            print(f"saved {len(saved)} PNGs to {args.png}")
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
