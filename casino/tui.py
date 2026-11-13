'''
Terminal UI for Terminal Casino, built on Rich.

Modelled on the AI Blackjack TUI. Two front-ends share one interface:
  RichUI      - full-screen lobby: header bar, green felt, side wallet/log, key-driven footer
  HeadlessUI  - plain stdin/stdout fallback (pipes, non-TTY)

The casino never calls print/input directly while the UI is running; it uses
ui.log, ui.error, ui.choose, ui.ask, ui.wait_key and ui.show_info.

Author: Ian Jackson
'''

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from typing import List, Optional, Sequence, Tuple

from rich import box

from casino import __version__
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

FELT = "on #0b3d2e"
MAX_FPS = 30
SIDE_MIN_WIDTH = 100     # below this the side column moves under the main panel

# (keys, value, label) — the first key is the one shown on screen
Option = Tuple[object, str, str]

KEY_LABELS = {"up": "↑", "down": "↓", "left": "←", "right": "→", "enter": "↵", "esc": "Esc", "tab": "Tab"}


#== Small helpers ==#

def _key_matches(key: str, keys) -> bool:
    '''Option keys are either a string of single characters or a tuple of key names like ("up", "k").'''
    if isinstance(keys, str):
        return len(key) == 1 and key in keys
    return key in keys


def key_label(keys) -> str:
    first = keys[0]
    return KEY_LABELS.get(first, first.upper())


def esc(value) -> str:
    '''Escape a value for use inside Rich markup.'''
    return escape(str(value))


def money(value) -> str:
    value = float(value)
    return f"${value:,.0f}" if value.is_integer() else f"${value:,.2f}"


def signed_money(value) -> str:
    value = float(value)
    return f"+{money(value)}" if value >= 0 else f"-{money(abs(value))}"


def net_text(value) -> Text:
    if value > 0:
        return Text(signed_money(value), "bold green")
    if value < 0:
        return Text(signed_money(value), "bold red")
    return Text("even", "grey62")


def ago(ts: float) -> str:
    secs = max(0, time.time() - ts)
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float], width: int) -> Text:
    '''Tiny balance chart: the last `width` values, green at/above the first value, red below.'''
    if not values:
        return Text("")
    start = values[0]
    pts = list(values[-width:])
    lo, hi = min(pts + [start]), max(pts + [start])
    span = (hi - lo) or 1
    line = Text()
    for v in pts:
        line.append(SPARK[min(len(SPARK) - 1, int((v - lo) / span * (len(SPARK) - 1) + 0.5))],
                    "green" if v >= start else "red")
    return line


#== Splash logo: chips, dice and a slot reel ==#

DIE_BG = "on grey93"
DIE_EDGE = f"grey50 {DIE_BG}"
PIP = f"bold grey11 {DIE_BG}"
PIPS = {   # 3x3 pip grid per face, read row by row
    1: ("   ", " ● ", "   "), 2: ("●  ", "   ", "  ●"), 3: ("●  ", " ● ", "  ●"),
    4: ("● ●", "   ", "● ●"), 5: ("● ●", " ● ", "● ●"), 6: ("● ●", "● ●", "● ●"),
}

# side-view chip stacks: (body colour, edge-spot colour, label ink)
CHIP_COLOURS = {
    "1K": ("orange1", "grey93", "black"), "500": ("purple4", "gold1", "white"),
    "100": ("grey11", "grey93", "white"), "25": ("green4", "grey93", "white"),
    "5": ("red3", "grey93", "white"),
}
CHIP_GAP = "#06261c"
LOGO_H = 5


def _die(face: int) -> List[Text]:
    rows = [Text("╭───────╮", DIE_EDGE)]
    for pips in PIPS[face]:
        rows.append(Text.assemble(("│ ", DIE_EDGE), (" ".join(pips), PIP), (" │", DIE_EDGE)))
    rows.append(Text("╰───────╯", DIE_EDGE))
    return rows


def _chip_stack(label: str, count: int) -> List[Text]:
    body, spot, ink = CHIP_COLOURS[label]
    rows = [Text(f"{label:^5}", f"bold {ink} on {body}")]
    for _ in range(count - 1):
        edge = Text()
        for j in range(5):
            edge.append("▆", f"{spot if j in (1, 3) else body} on {CHIP_GAP}")
        rows.append(edge)
    return rows


def _slot_reel() -> List[Text]:
    frame, dim, hot = "bold gold1", "grey50 on grey93", "bold red3 on grey93"
    def row(symbols, style, left=" ", right=" "):
        line = Text.assemble((left, "bold red"), ("║", frame))
        for i, sym in enumerate(symbols):
            if i:
                line.append("║", frame)
            line.append(f" {sym} ", style)
        return line.append("║", frame).append(right, "bold red")
    return [
        Text.assemble((" ", ""), ("╔═══╦═══╦═══╗", frame), (" ", "")),
        row("♣♥♦", dim),
        row("777", hot, "▶", "◀"),
        row("♦♠♣", dim),
        Text.assemble((" ", ""), ("╚═══╩═══╩═══╝", frame), (" ", "")),
    ]


def _hjoin(blocks: Sequence[List[Text]], gap: int = 2) -> Text:
    '''Place blocks of lines side by side, bottom-aligned.'''
    widths = [max(t.cell_len for t in b) for b in blocks]
    lines = []
    for r in range(LOGO_H):
        line = Text()
        for k, (block, w) in enumerate(zip(blocks, widths)):
            if k:
                line.append(" " * gap)
            idx = r - (LOGO_H - len(block))
            cell = block[idx] if idx >= 0 else Text("")
            line.append_text(cell).append(" " * (w - cell.cell_len))
        lines.append(line)
    return Text("\n").join(lines)


def casino_logo() -> Text:
    stacks_l = _hjoin([_chip_stack("5", 3), _chip_stack("25", 5)], gap=1).split()
    stacks_r = _hjoin([_chip_stack("100", 4), _chip_stack("1K", 2)], gap=1).split()
    return _hjoin([list(stacks_l), _die(5), _slot_reel(), _die(3), list(stacks_r)])


def title_text() -> Text:
    return Text.assemble(("♠ ", "bold white"), ("♥ ", "bold red"),
                         ("T E R M I N A L   C A S I N O", "bold gold1"),
                         (" ♦", "bold red"), (" ♣", "bold white"))


#== Base / headless UI ==#

class BaseUI:
    interactive = False

    def __init__(self):
        self.lobby = None        # casino.carousel.Lobby while the lobby is showing
        self.player = None       # casino.session.Player once seated
        self.splash_info = ""
        self.regulars = []       # recent profiles, shown on the welcome screen
        self.autosave = True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def slide_lobby(self, direction: int) -> None:
        pass

    def set_overlay(self, title: str, renderable) -> None:
        pass

    def clear_overlay(self) -> None:
        pass

    def print_after(self, renderable) -> None:
        Console(highlight=False).print(renderable)


class HeadlessUI(BaseUI):
    '''Plain-text fallback for pipes / non-TTY.'''

    def __init__(self):
        super().__init__()
        self.console = Console(highlight=False)

    def log(self, message: str) -> None:
        self.console.print("  " + message)

    def error(self, message: str) -> None:
        self.console.print(f"  [red]{message}[/]")

    def choose(self, prompt: str, options: Sequence[Option], default: Optional[str] = None) -> str:
        hints = "  ".join(f"[{key_label(keys)}] {label}" for keys, _, label in options if label is not None)
        raw = input(f"  {Text.from_markup(prompt).plain}  {hints}\n  > ").strip().lower()
        if not raw and default is not None:
            return default
        for keys, value, label in options:
            if _key_matches(raw, keys) or raw == value or (label and raw == label.lower()):
                return value
        return raw

    def ask(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        raw = input(f"  {Text.from_markup(prompt).plain}{suffix}: ").strip()
        return raw or default

    def wait_key(self, prompt: str = "Press Enter to continue") -> None:
        input(f"  {Text.from_markup(prompt).plain}")

    def show_info(self, title: str, renderable) -> None:
        self.console.print(Panel(renderable, title=title, expand=False))


#== Rich full-screen UI ==#

class _KeyReader:
    '''Reads single keypresses from the terminal without echo.'''

    def __init__(self):
        self._fd = None
        self._old = None

    def __enter__(self):
        if os.name != "nt":
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            # TCSADRAIN keeps keys typed while the casino was starting; keeps ISIG so Ctrl-C works
            tty.setcbreak(self._fd, termios.TCSADRAIN)
        return self

    def __exit__(self, *exc):
        if self._old is not None:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._old = None

    def read(self) -> str:
        if os.name == "nt":
            import msvcrt
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(msvcrt.getwch(), "")
            if ch == "\x03":
                raise KeyboardInterrupt
            return {"\r": "enter", "\n": "enter", "\x08": "backspace", "\x1b": "esc", "\t": "tab"}.get(ch, ch)

        import select
        first = os.read(self._fd, 1)
        if first == b"\x1b":
            # swallow the rest of an escape sequence (arrow keys etc.)
            seq = b""
            while select.select([self._fd], [], [], 0.02)[0]:
                seq += os.read(self._fd, 1)
            if not seq:
                return "esc"
            return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left",
                    b"OA": "up", b"OB": "down", b"OC": "right", b"OD": "left"}.get(seq, "")
        if first == b"\t":
            return "tab"
        if first in (b"\r", b"\n"):
            return "enter"
        if first in (b"\x7f", b"\x08"):
            return "backspace"
        if first == b"\x04":
            raise EOFError
        lead = first[0]
        extra = 1 if lead >> 5 == 0b110 else 2 if lead >> 4 == 0b1110 else 3 if lead >> 3 == 0b11110 else 0
        data = first + (os.read(self._fd, extra) if extra else b"")
        return data.decode("utf-8", errors="ignore")


class _LogView:
    '''Shows the newest log lines that fit in the region it is given.'''

    def __init__(self, lines: List[str], title: str):
        self.lines = lines
        self.title = title

    def __rich_console__(self, console, options):
        height = options.height or console.height
        inner_w = max(10, options.max_width - 4)
        budget = max(1, height - 2)
        picked: List[Text] = []
        for markup in reversed(self.lines):
            text = Text.from_markup(markup)
            used = len(text.wrap(console, inner_w))
            if used > budget:
                break
            picked.append(text)
            budget -= used
        picked.reverse()
        yield Panel(Group(*picked) if picked else Text("…", "dim"), title=self.title,
                    title_align="left", border_style="grey42", height=height, box=box.ROUNDED)


class RichUI(BaseUI):
    interactive = True

    def __init__(self):
        super().__init__()
        self.console = Console(highlight=False)
        self._live: Optional[Live] = None
        self._keys = _KeyReader()
        self._log: deque = deque(maxlen=300)
        self._prompt: Optional[str] = None
        self._options: Sequence[Option] = ()
        self._default: Optional[str] = None
        self._buffer: Optional[str] = None
        self._placeholder = ""
        self._flash: Optional[str] = None
        self._overlay = None
        self._overlay_title = ""
        self._dirty = threading.Event()
        self._drawer: Optional[threading.Thread] = None
        self._running = False

    # lifecycle
    def start(self) -> None:
        if self._live:
            return
        self._keys.__enter__()
        # No auto-refresh: a draw thread repaints only when refresh() marks the screen dirty
        # (or the terminal is resized), at most MAX_FPS times a second.
        self._live = Live(get_renderable=self._render, console=self.console, screen=True,
                          auto_refresh=False, redirect_stdout=False, redirect_stderr=False)
        self._live.start()
        self._running = True
        self._drawer = threading.Thread(target=self._draw_loop, name="tui-draw", daemon=True)
        self._drawer.start()
        self.refresh()

    def stop(self) -> None:
        if self._live:
            self._running = False
            self._dirty.set()
            if self._drawer:
                self._drawer.join(timeout=1)
            self._live.stop()
            self._live = None
        self._keys.__exit__()

    def _draw_loop(self) -> None:
        size = self.console.size
        while self._running:
            self._dirty.wait(timeout=0.25)
            if not self._running:
                break
            new_size = self.console.size
            if not self._dirty.is_set() and new_size == size:
                continue
            size = new_size
            self._dirty.clear()
            try:
                self._live.refresh()
            except Exception:
                self._dirty.set()
            time.sleep(1 / MAX_FPS)

    # output
    def log(self, message: str) -> None:
        self._log.append(message)
        self.refresh()

    def error(self, message: str) -> None:
        self._flash = message
        self.refresh()

    def refresh(self) -> None:
        if self._live:
            self._dirty.set()

    def set_overlay(self, title: str, renderable) -> None:
        self._overlay_title = title
        self._overlay = renderable
        self.refresh()

    def clear_overlay(self) -> None:
        self._overlay = None
        self.refresh()

    def show_info(self, title: str, renderable) -> None:
        self.set_overlay(title, renderable)
        self.wait_key("Press any key to return to the lobby")
        self.clear_overlay()

    # input
    def _read(self) -> str:
        key = self._keys.read()
        self._flash = None
        return key

    def choose(self, prompt: str, options: Sequence[Option], default: Optional[str] = None) -> str:
        self._prompt, self._options, self._default, self._buffer = prompt, options, default, None
        self.refresh()
        try:
            while True:
                key = self._read()
                if key == "enter" and default is not None:
                    return default
                if len(key) == 1:
                    key = key.lower()
                for keys, value, _ in options:
                    if _key_matches(key, keys):
                        return value
                self.refresh()
        finally:
            self._prompt, self._options, self._default = None, (), None
            self.refresh()

    def ask(self, prompt: str, default: str = "") -> str:
        self._prompt, self._options, self._buffer, self._placeholder = prompt, (), "", default
        self.refresh()
        try:
            while True:
                key = self._read()
                if key == "enter":
                    return self._buffer.strip() or default
                if key == "backspace":
                    self._buffer = self._buffer[:-1]
                elif key == "esc":
                    self._buffer = ""
                elif len(key) == 1 and key.isprintable():
                    self._buffer += key
                self.refresh()
        finally:
            self._prompt, self._buffer, self._placeholder = None, None, ""
            self.refresh()

    def wait_key(self, prompt: str = "Press any key to continue") -> None:
        self._prompt, self._options = prompt, ()
        self.refresh()
        try:
            self._read()
        finally:
            self._prompt = None
            self.refresh()

    # rendering
    def _render(self):
        width, height = self.console.size
        side = width >= SIDE_MIN_WIDTH
        side_w = 46 if width >= 150 else 42
        # short, narrow screen: the body gets the full height and the newest log line goes in the footer
        self._inline_log = not side and height < 32

        layout = Layout()
        layout.split_column(
            Layout(self._header(), name="header", size=3),
            Layout(name="body"),
            Layout(self._footer(), name="footer", size=4),
        )
        body = layout["body"]

        if self._overlay is not None:
            view = self._overlay if getattr(self._overlay, "fill", False) else Align.center(self._overlay, vertical="middle")
            main = Panel(view, title=self._overlay_title, border_style="gold1", box=box.DOUBLE)
        elif self.lobby is None:
            main = self._splash()
        else:
            main = self._lobby()

        log_view = _LogView(list(self._log), "Casino Floor")
        if self._overlay is not None or self._inline_log:   # full-screen pages get the whole body
            body.update(main)
        elif side:
            side_view = self._side(height - 7) if self.player is not None else log_view
            body.split_row(Layout(main, name="main"), Layout(side_view, name="side", size=side_w))
        else:
            body.split_column(Layout(main, name="main"), Layout(log_view, name="log", size=7))
        return layout

    def _header(self):
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        info = Text(style="grey70")
        p = self.player
        if p is not None:
            info.append(p.name, "bold")
            info.append("   ")
            info.append(money(p.balance), "bold green" if p.balance > 0 else "bold red")
            info.append(f"   {p.total_sessions} game{'s' if p.total_sessions != 1 else ''} this visit")
        grid.add_row(title_text(), info)
        return Panel(grid, box=box.HEAVY, border_style="gold1")

    def _footer(self):
        lines = []
        if self._flash:
            lines.append(Text.from_markup(f"[bold red]✖ {self._flash}[/]"))
        elif getattr(self, "_inline_log", False) and self._log and self._overlay is None:
            latest = Text.from_markup(self._log[-1], style="grey70")
            latest.no_wrap, latest.overflow = True, "ellipsis"
            lines.append(latest)
        if self._prompt is not None:
            line = Text.from_markup(self._prompt)
            if self._buffer is not None:
                line.append("  ")
                if self._buffer:
                    line.append(self._buffer, "bold white")
                elif self._placeholder:
                    line.append(self._placeholder, "grey50")
                line.append("▌", "blink bold gold1")
            if self._options:
                line.append("   ")
                for keys, value, label in self._options:
                    if label is None:          # hidden shortcut
                        continue
                    line.append(f" {key_label(keys)} ", "bold black on gold1")
                    if not label:
                        line.append(" ")
                        continue
                    line.append(f" {label}", "bold")
                    line.append(" (↵)  " if value == self._default else "  ", "grey62")
            lines.append(line)
        if not lines:
            lines.append(Text(""))
        return Panel(Group(*lines[-2:]), box=box.ROUNDED, border_style="grey42",
                     subtitle="[grey50]Ctrl-C cashes out[/]", subtitle_align="right")

    def _splash(self):
        logo = casino_logo()
        parts = [Align.center(logo), Text(""), Align.center(title_text()),
                 Align.center(Text("pull up a chair · one wallet, every table", "grey62")),
                 Align.center(Text(f"v{__version__}", "grey42")), Text("")]
        if self.splash_info:
            parts.append(Align.center(Text.from_markup(self.splash_info, style="grey62", justify="center")))
        if self.regulars:
            regs = Table(box=box.SIMPLE, header_style="bold gold1", pad_edge=False, padding=(0, 2))
            regs.add_column("Regulars", style="bold", no_wrap=True)
            regs.add_column("Balance", justify="right", no_wrap=True)
            regs.add_column("Last seen", style="grey62", no_wrap=True)
            for prof in self.regulars[:5]:
                regs.add_row(esc(prof.name), Text(money(prof.balance), "green" if prof.balance > 0 else "red"),
                             ago(prof.last_played))
            parts += [Text(""), Align.center(regs),
                      Align.center(Text("type a regular's name to pick up where they left off", "grey50"))]
        return Panel(Align.center(Group(*parts), vertical="middle"), box=box.ROUNDED,
                     border_style="green4", style=FELT)

    def _lobby(self):
        from casino.carousel import render_lobby
        from casino.tables import bet_range, rules_summary
        lobby = self.lobby
        balance = self.player.balance if self.player else 0

        class _Carousel:
            def __rich_console__(self, console, options):
                yield render_lobby(lobby, balance, money, bet_range, rules_summary,
                                   options.max_width, options.height or console.height)

        n = len(lobby.tables)
        return Panel(_Carousel(), title="[bold]Lobby[/]", title_align="left",
                     subtitle=f"[grey62]{len(lobby.games)} game{'s' if len(lobby.games) != 1 else ''} · "
                              f"{n} table{'s' if n != 1 else ''} open[/]",
                     subtitle_align="right", box=box.ROUNDED, border_style="green4", style=FELT,
                     padding=(0, 1))

    def slide_lobby(self, direction: int) -> None:
        '''Animate the carousel after the centre game changed: cards glide in from `direction`.'''
        from casino.carousel import SLIDE_FPS, SLIDE_S
        lobby = self.lobby
        frames = max(1, int(SLIDE_S * SLIDE_FPS))
        try:
            for i in range(frames + 1):
                lobby.offset = direction * (1 - i / frames) ** 3      # ease out
                self.refresh()
                time.sleep(SLIDE_S / frames)
        finally:
            lobby.offset = 0.0
            self.refresh()

    def _side(self, height: int):
        p = self.player
        wallet = Table.grid(padding=(0, 2))
        wallet.add_column(style="grey62", no_wrap=True)
        wallet.add_column(justify="right", no_wrap=True)
        prof = p.profile
        wallet.add_row("Balance", Text(money(p.balance), "bold green" if p.balance > 0 else "bold red"))
        wallet.add_row("This visit", net_text(p.net))
        wallet.add_row("Lifetime", net_text(prof.net))
        extra = 0
        if prof.rebuys:
            wallet.add_row("Rebuys", Text(str(prof.rebuys), "magenta"))
            extra += 1
        if p.dirty:
            save = Text("● unsaved", "yellow")
        elif p.saved_at:
            save = Text(f"✓ saved {time.strftime('%H:%M', time.localtime(p.saved_at))}", "green")
        else:
            save = Text("✓ saved", "green")
        if self.autosave:
            save.append(" · auto", "grey50")
        wallet.add_row("Profile", save)
        parts = [wallet]
        if len(p.history) > 1:
            parts += [Text(""), Text("  ") + sparkline(p.history, 30)]
        if p.games_played:
            parts.append(Text(""))
            for game, count in p.games_played.items():
                parts.append(Text.assemble(("· ", "grey50"), (game, "bold"), (f"  ×{count}", "grey62")))
        n_lines = 4 + extra + (2 if len(p.history) > 1 else 0) + (1 + len(p.games_played) if p.games_played else 0)

        layout = Layout()
        layout.split_column(
            Layout(Panel(Group(*parts), title="[bold gold1]Wallet[/]", border_style="grey42", box=box.ROUNDED),
                   size=min(n_lines + 2, max(6, height // 2))),
            Layout(_LogView(list(self._log), "Casino Floor")),
        )
        return layout


def make_ui():
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return HeadlessUI()
    return RichUI()
