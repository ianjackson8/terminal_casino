'''
Player profiles: one JSON file per player in profiles/, keyed by a slug of their name
(so "Ian" and "ian" are the same profile).

Author: Ian Jackson
'''

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

PROFILE_VERSION = 1
HISTORY_CAP = 1000      # results kept per profile (oldest dropped first)


@dataclass
class GameStats:
    played: int = 0
    won: int = 0
    lost: int = 0
    even: int = 0
    net: float = 0.0
    best: float = 0.0       # biggest single-visit win
    worst: float = 0.0      # biggest single-visit loss (negative)
    seconds: float = 0.0    # time spent at the table
    game: str = ""          # the game this table belongs to (stats are keyed by table label)

    def record(self, delta: float, seconds: float) -> None:
        self.played += 1
        if delta > 0:
            self.won += 1
        elif delta < 0:
            self.lost += 1
        else:
            self.even += 1
        self.net += delta
        self.best = max(self.best, delta)
        self.worst = min(self.worst, delta)
        self.seconds += seconds


@dataclass
class Profile:
    name: str
    balance: float
    bought_in: float                    # initial buy-in plus every rebuy (rebuys predate the loan shark)
    created: float = field(default_factory=time.time)
    last_played: float = field(default_factory=time.time)
    sessions: int = 0
    rebuys: int = 0
    loans: int = 0                      # loans ever taken from the loan shark
    loan: Optional[dict] = None         # outstanding debt: {"owed", "borrowed", "due", "taken"}
    games: Dict[str, GameStats] = field(default_factory=dict)
    history: List[dict] = field(default_factory=list)   # {"t", "game", "delta", "balance"}

    @property
    def net(self) -> float:
        return self.balance - self.bought_in - self.debt

    #-- the loan shark: rounds are table visits (games_played) --#

    @property
    def debt(self) -> float:
        return self.loan["owed"] if self.loan else 0.0

    @property
    def rounds_left(self) -> int:
        '''Rounds until the loan is due; negative when it's overdue.'''
        return self.loan["due"] - self.games_played if self.loan else 0

    def borrow(self, amount: float, vig: float, rounds: int) -> None:
        '''Take a loan: `amount` in chips, `amount * (1 + vig)` owed. Rolling over keeps the old due date.'''
        owed = round(amount * (1 + vig), 2)
        if self.loan:
            self.loan["owed"] = round(self.loan["owed"] + owed, 2)
            self.loan["borrowed"] += amount
        else:
            self.loan = {"owed": owed, "borrowed": amount, "due": self.games_played + rounds, "taken": time.time()}
        self.loans += 1
        self.balance += amount
        self._log_money("Loan", amount)

    def repay(self, amount: float, label: str = "Repaid") -> float:
        '''Pay down the debt from the balance. Returns what was actually paid.'''
        amount = round(min(amount, self.debt, self.balance), 2)
        if amount <= 0:
            return 0.0
        self.balance = round(self.balance - amount, 2)
        self.loan["owed"] = round(self.loan["owed"] - amount, 2)
        if self.loan["owed"] < 0.01:
            self.loan = None
        self._log_money(label, -amount)
        return amount

    def accrue(self, rate: float) -> float:
        '''Late interest for one round, once the due date has passed. Returns the interest added.'''
        if not self.loan or self.rounds_left >= 0:
            return 0.0
        interest = round(self.loan["owed"] * rate, 2)
        self.loan["owed"] = round(self.loan["owed"] + interest, 2)
        return interest

    def _log_money(self, label: str, delta: float) -> None:
        self.history.append({"t": time.time(), "game": label, "delta": delta, "balance": self.balance})
        del self.history[:-HISTORY_CAP]

    @property
    def games_played(self) -> int:
        return sum(g.played for g in self.games.values())

    @property
    def seconds_played(self) -> float:
        return sum(g.seconds for g in self.games.values())

    def record(self, label: str, before: float, after: float, seconds: float, game: str = "") -> None:
        '''Record one visit to a table. `label` is the table ("Blackjack · High Roller"), `game` its game.'''
        delta = after - before
        stats = self.games.setdefault(label, GameStats())
        stats.game = game or stats.game or label
        stats.record(delta, seconds)
        self.history.append({"t": time.time(), "game": label, "delta": delta, "balance": after})
        del self.history[:-HISTORY_CAP]
        self.last_played = time.time()

    def balance_series(self) -> List[float]:
        '''Balance over time, starting from the first buy-in.'''
        first = self.history[0]["balance"] - self.history[0]["delta"] if self.history else self.balance
        return [first] + [h["balance"] for h in self.history]

    # serialisation
    def to_dict(self) -> dict:
        data = asdict(self)
        data["version"] = PROFILE_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        data = dict(data)
        data.pop("version", None)
        games = {k: GameStats(**v) for k, v in data.pop("games", {}).items()}
        return cls(games=games, **data)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "player_" + hashlib.sha1(name.encode()).hexdigest()[:8]


class ProfileStore:
    def __init__(self, directory: Path):
        self.dir = directory

    def path(self, name: str) -> Path:
        return self.dir / f"{slugify(name)}.json"

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def load(self, name: str) -> Optional[Profile]:
        '''Load a profile, or None if there isn't one. Raises ValueError if the file is unreadable.'''
        path = self.path(name)
        if not path.exists():
            return None
        try:
            return Profile.from_dict(json.loads(path.read_text()))
        except (OSError, ValueError, TypeError, KeyError) as err:
            raise ValueError(f"{path.name} is unreadable ({err})") from err

    def quarantine(self, name: str) -> Path:
        '''Move an unreadable profile aside so a fresh one can be created without losing it.'''
        path = self.path(name)
        dest = path.with_name(f"{path.stem}.corrupt-{int(time.time())}.json")
        os.replace(path, dest)
        return dest

    def save(self, profile: Profile) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.path(profile.name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(profile.to_dict(), indent=2))
        os.replace(tmp, path)   # atomic: a crash mid-save never leaves a half-written profile

    def delete(self, name: str) -> None:
        self.path(name).unlink(missing_ok=True)

    def all(self) -> List[Profile]:
        '''Every readable profile, most recently played first.'''
        if not self.dir.exists():
            return []
        out = []
        for path in self.dir.glob("*.json"):
            if ".corrupt-" in path.name:
                continue
            try:
                out.append(Profile.from_dict(json.loads(path.read_text())))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return sorted(out, key=lambda p: -p.last_played)
