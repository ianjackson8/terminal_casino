import time
from typing import List

from casino.profiles import Profile


class Player:
    '''
    One sitting at the casino. Wraps the persistent Profile and adds this-session numbers.
    Balance lives on the profile so saving always captures it.
    '''

    def __init__(self, profile: Profile, returning: bool = False):
        self.profile = profile
        self.returning = returning
        self.starting_balance = profile.balance
        self.history: List[float] = [profile.balance]   # balance after each game this session
        self.games_played: dict = {}
        self.starting_debt = profile.debt                # owed to the loan shark when they sat down
        self.started = time.time()
        self.dirty = not returning                       # unsaved changes?
        self.saved_at = None
        profile.sessions += 1

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def balance(self) -> float:
        return self.profile.balance

    @balance.setter
    def balance(self, value: float) -> None:
        self.profile.balance = value

    def record_game(self, label: str, before: float, seconds: float, game: str = "") -> None:
        self.profile.record(label, before, self.balance, seconds, game=game)
        self.games_played[label] = self.games_played.get(label, 0) + 1
        self.history.append(self.balance)
        self.dirty = True

    def money_moved(self) -> None:
        '''Call after the balance changes outside a game (a loan, a repayment, a collection).'''
        self.history.append(self.balance)
        self.dirty = True

    def mark_saved(self) -> None:
        self.dirty = False
        self.saved_at = time.time()

    @property
    def net(self) -> float:
        '''This session's result: borrowed chips don't count, interest and fees do.'''
        return (self.balance - self.profile.debt) - (self.starting_balance - self.starting_debt)

    @property
    def total_sessions(self) -> int:
        return sum(self.games_played.values())
