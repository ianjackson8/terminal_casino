'''
The lobby carousel: one big card per game in the middle of the felt, its neighbours peeking in
from the sides, sliding left and right. The selected game's tables are listed underneath.

    ←/→  slide to the previous / next game      ↑/↓  pick a table      ↵  sit down

Author: Ian Jackson
'''

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from rich.align import Align
from rich.console import Group
from rich.table import Table
from rich.text import Text

# A line of art is a list of (text, style) segments; a block is a list of lines.
Seg = Tuple[str, str]
Line = List[Seg]

FELT_BG = "#0b3d2e"
SLIDE_S = 0.22          # seconds for one slide
SLIDE_FPS = 40


#== Lobby state ==#

class Lobby:
    '''Which game is in the middle of the carousel, and which of its tables is picked.'''

    def __init__(self, tables: list):
        self.game = 0
        self.offset = 0.0               # slide animation: +1 = the centre card starts one slot to the right
        self._picked: Dict[str, int] = {}
        self.set_tables(tables)

    def set_tables(self, tables: list) -> None:
        self.tables = list(tables)
        self.games: List[Tuple[object, list]] = []
        for t in self.tables:
            if self.games and self.games[-1][0] is t.plugin:
                self.games[-1][1].append(t)
            else:
                self.games.append((t.plugin, [t]))
        self.game = min(self.game, max(0, len(self.games) - 1))

    @property
    def plugin(self):
        return self.games[self.game][0] if self.games else None

    @property
    def game_tables(self) -> list:
        return self.games[self.game][1] if self.games else []

    @property
    def table_index(self) -> int:
        if not self.games:
            return 0
        return min(self._picked.get(self.plugin.key, 0), len(self.game_tables) - 1)

    @property
    def table(self):
        tables = self.game_tables
        return tables[self.table_index] if tables else None

    def move_game(self, step: int) -> bool:
        if len(self.games) < 2:
            return False
        self.game = (self.game + step) % len(self.games)
        return True

    def move_table(self, step: int) -> None:
        if self.game_tables:
            self._picked[self.plugin.key] = (self.table_index + step) % len(self.game_tables)

    def pick_table(self, index: int) -> bool:
        if 0 <= index < len(self.game_tables):
            self._picked[self.plugin.key] = index
            return True
        return False


#== Art ==#

RED_INK, BLACK_INK, CARD_BG = "bold red3 on grey93", "bold grey11 on grey93", "on grey93"
EDGE = "grey50 on grey93"
GOLD = "bold gold1"


def _card(rank: str, suit: str) -> List[Line]:
    ink = RED_INK if suit in "♥♦" else BLACK_INK
    return [
        [("╭─────╮", EDGE)],
        [("│", EDGE), (f"{rank:<2}", ink), ("   ", CARD_BG), ("│", EDGE)],
        [("│", EDGE), ("  ", CARD_BG), (suit, ink), ("  ", CARD_BG), ("│", EDGE)],
        [("│", EDGE), ("   ", CARD_BG), (f"{rank:>2}", ink), ("│", EDGE)],
        [("╰─────╯", EDGE)],
    ]


def _side_by_side(blocks: Sequence[List[Line]], gap: int = 1) -> List[Line]:
    height = max(len(b) for b in blocks)
    widths = [max(seg_len(l) for l in b) for b in blocks]
    out = []
    for r in range(height):
        line: Line = []
        for i, (b, w) in enumerate(zip(blocks, widths)):
            if i:
                line.append((" " * gap, ""))
            cell = b[r] if r < len(b) else []
            line += cell + [(" " * (w - seg_len(cell)), "")]
        out.append(line)
    return out


def _pocket(n: str) -> Seg:
    red = {"1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23", "25", "27", "30", "32", "34", "36"}
    style = "bold white on green4" if n in ("0", "00") else ("bold white on red3" if n in red else "bold white on grey15")
    return (f"{n:>2}", style)


def _join(segs: Sequence[Seg], sep: Seg = (" ", "")) -> Line:
    out: Line = []
    for i, s in enumerate(segs):
        if i:
            out.append(sep)
        out.append(s)
    return out


def art_blackjack(compact: bool) -> List[Line]:
    if compact:
        return [[(" A♠ ", BLACK_INK), (" ", ""), (" K♥ ", RED_INK)], [], [("2 1", GOLD)]]
    cards = _side_by_side([_card("A", "♠"), _card("K", "♥")])
    return cards + [[], [("★  2 1  ★", GOLD)]]


def art_baccarat(compact: bool) -> List[Line]:
    labels = [("PLAYER", "bold dodger_blue2"), ("      ", ""), ("BANKER", "bold red1")]
    if compact:
        return [labels, [(" 9♦ ", RED_INK), ("        ", ""), (" 8♣ ", BLACK_INK)], [("NATURAL", GOLD)]]
    cards = _side_by_side([_card("9", "♦"), _card("8", "♣")], gap=5)
    return [labels] + cards + [[("N A T U R A L", GOLD)]]


def art_roulette(compact: bool) -> List[Line]:
    top = ["32", "15", "19", "4", "21"]
    bottom = ["34", "6", "27", "13", "36"]
    ball = ("●", "bold bright_white")
    if compact:
        return [_join([_pocket(n) for n in top]), [("    ", ""), ball], _join([_pocket(n) for n in bottom])]
    gap = " " * 15
    return [
        [("  ", "")] + _join([_pocket(n) for n in top]),
        [_pocket("0"), (gap + "   ", ""), _pocket("2")],
        [_pocket("26"), ("        ", ""), ball, ("         ", ""), _pocket("25")],
        [_pocket("3"), (gap + "   ", ""), _pocket("17")],
        [("  ", "")] + _join([_pocket(n) for n in reversed(bottom)]),
        [],
        [("◀  0 – 36  ▶", GOLD)],
    ]


def art_generic(compact: bool) -> List[Line]:
    die = [[("╭─────╮", EDGE)], [("│", EDGE), ("●   ●", BLACK_INK), ("│", EDGE)],
           [("│", EDGE), ("  ●  ", "bold red3 on grey93"), ("│", EDGE)],
           [("│", EDGE), ("●   ●", BLACK_INK), ("│", EDGE)], [("╰─────╯", EDGE)]]
    chips = [[(" 25 ", "bold white on green4")], [("▆▆▆▆", "green4")], [(" 5  ", "bold white on red3")],
             [("▆▆▆▆", "red3")], [("▆▆▆▆", "red3")]]
    if compact:
        return [[(" ⚄ ", BLACK_INK), ("  ", ""), (" 25 ", "bold white on green4"), (" ", ""), (" 5 ", "bold white on red3")]]
    return _side_by_side([chips, die], gap=3) + [[], [("♠ ♥ ♦ ♣", GOLD)]]


ART = [("blackjack", art_blackjack), ("baccarat", art_baccarat), ("roulette", art_roulette)]


def game_art(plugin, compact: bool) -> List[Line]:
    name = f"{getattr(plugin, 'key', '')} {getattr(plugin, 'name', '')}".lower()
    for word, fn in ART:
        if word in name:
            return fn(compact)
    return art_generic(compact)


#== Canvas: blocks pasted side by side, cropped at the edges ==#

def seg_len(line: Line) -> int:
    return sum(len(t) for t, _ in line)


class Canvas:
    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.cells = [[(" ", "")] * width for _ in range(height)]

    def put(self, x: int, y: int, line: Line, extra: str = "") -> None:
        if not 0 <= y < self.h:
            return
        for text, style in line:
            for ch in text:
                if 0 <= x < self.w:
                    self.cells[y][x] = (ch, f"{style} {extra}".strip())
                x += 1

    def to_text(self) -> Text:
        rows = []
        for row in self.cells:
            t = Text(no_wrap=True, overflow="crop")
            run, run_style = "", None
            for ch, style in row:
                if style != run_style and run:
                    t.append(run, run_style or None)
                    run = ""
                run_style = style
                run += ch
            if run:
                t.append(run, run_style or None)
            rows.append(t)
        return Text("\n").join(rows)


def _card_block(plugin, width: int, compact: bool, centre: bool, tight: bool = False) -> List[Line]:
    '''A game card: frame, art centred inside, the game's name along the bottom.'''
    inner = width - 2
    art = game_art(plugin, compact)
    art_h = 3 if compact else 7
    art = (art + [[]] * art_h)[:art_h]
    name = plugin.name.upper()
    spaced = " ".join(name)
    title = spaced if len(spaced) <= inner - 2 else name[: inner - 2]
    if centre:
        frame, tl, tr, bl, br, hz, vt = "bold gold1", "╔", "╗", "╚", "╝", "═", "║"
        title_style = "bold gold1"
    else:
        frame, tl, tr, bl, br, hz, vt = "grey50", "╭", "╮", "╰", "╯", "─", "│"
        title_style = "bold grey70"

    def framed(content: Line) -> Line:
        pad = inner - seg_len(content)
        left = pad // 2
        return [(vt, frame), (" " * left, "")] + content + [(" " * (pad - left), ""), (vt, frame)]

    pad = [] if tight else [framed([])]
    rows: List[Line] = [[(tl + hz * inner + tr, frame)]] + pad
    rows += [framed(line) for line in art]
    rows += pad + [framed([(title, title_style)]), [(bl + hz * inner + br, frame)]]
    return rows


#== The lobby view ==#

def render_lobby(lobby: Lobby, balance: float, money, bet_range, rules_summary, width: int, height: int):
    if not lobby.games:
        return Group(Text("The tables are empty.", "bold", justify="center"),
                     Text("Add a game to plugins/, or open a table in Settings.", "grey62", justify="center"))

    n = len(lobby.games)
    tables = lobby.game_tables
    info_h = 2 + (1 if n > 1 else 0) + len(tables)           # name, description, dots, tables
    roomy = height >= 13 + info_h + 2                       # room for the big centre card
    # the centre card is bigger than its neighbours; on short screens everything is compact
    centre_w = max(22, min(36, width // 3 + 4))
    side_w = max(18, centre_w - 8)
    centre_h = 12 if roomy else 6
    gap = 3
    near = (centre_w + side_w) // 2 + gap               # centre-to-neighbour distance
    far = side_w + gap                                  # neighbour-to-neighbour distance

    def centreline(p: float) -> float:
        '''Horizontal position of a card at carousel slot p (0 = middle), piecewise linear.'''
        if abs(p) <= 1:
            return p * near
        return (1 if p > 0 else -1) * (near + (abs(p) - 1) * far)

    canvas = Canvas(width, centre_h)
    # Which slots to draw: with 3+ games the carousel wraps around, but each game appears only once
    # (3 games: one neighbour each side; 4: two on the right). With 2 games there's no wrap.
    if n >= 3:
        slots = [k for k in range(-2, 3) if abs(k) <= (n - 1) // 2 or (n % 2 == 0 and k == n // 2)]
    else:
        slots = [k for k in range(-1, 2) if 0 <= lobby.game + k < n]
    # draw the neighbours first so the centre card sits on top while sliding
    for k in sorted(slots, key=lambda k: -abs(k + lobby.offset)):
        idx = (lobby.game + k) % n
        p = k + lobby.offset
        centre = abs(p) < 0.5
        w = centre_w if centre else side_w
        block = _card_block(lobby.games[idx][0], w, compact=not (roomy and centre), centre=centre, tight=not roomy)
        x = round(width / 2 + centreline(p) - w / 2)
        y0 = (centre_h - len(block)) // 2
        for y, line in enumerate(block):
            canvas.put(x, y0 + y, line, "" if centre else "dim")

    # centre the whole lobby vertically in the felt
    used = centre_h + info_h + (1 if roomy else 0)
    top = max(0, (height - used) // 2 - 1)
    compact = not roomy

    plugin = lobby.plugin
    parts = ([Text("\n" * (top - 1))] if top else []) + [canvas.to_text()]   # Text("\n" * k) is k+1 lines

    # arrows, name line, description, position dots
    head = Text(justify="center")
    if n > 1:
        head.append("◀  ", "bold gold1")
    head.append(plugin.name, "bold white")
    if plugin.version:
        head.append(f"  v{plugin.version}", "grey50")
    if n > 1:
        head.append("  ▶", "bold gold1")
    parts.append(head)
    if plugin.description:
        parts.append(Text(plugin.description, "grey70", justify="center", no_wrap=True, overflow="ellipsis"))
    if n > 1:
        dots = Text(justify="center")
        for i in range(n):
            dots.append("● " if i == lobby.game else "○ ", "gold1" if i == lobby.game else "grey42")
        parts.append(dots)
    if not compact:
        parts.append(Text(""))

    # this game's tables
    grid = Table(box=None, show_header=False, pad_edge=False, padding=(0, 1))
    grid.add_column(width=1, no_wrap=True)
    grid.add_column(width=3, no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True, max_width=max(10, width - 60), overflow="ellipsis")
    for i, t in enumerate(tables):
        selected = i == lobby.table_index
        can_play = balance >= t.min_bet
        style = "on grey23" if selected else ""
        pointer = Text("▶", "bold gold1") if selected else Text("")
        num = Text(f" {i + 1} ", "bold black on gold1" if can_play else "grey50 on grey23") if i < 9 else Text("")
        name = Text(t.name if not t.is_default else "Main table", "bold" if can_play else "grey50")
        stakes = Text(bet_range(t, money), "cyan" if can_play else "grey42")
        if not can_play:
            stakes.append("  not enough chips", "red")
        grid.add_row(pointer, num, name, stakes, Text(rules_summary(t), "grey62"), style=style)
    parts.append(Align.center(grid))
    return Group(*parts)
