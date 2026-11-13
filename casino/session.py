from dataclasses import dataclass, field


@dataclass
class Player:
    name: str
    balance: float
    starting_balance: float = field(init=False)
    games_played: dict = field(default_factory=dict)
    history: list = field(init=False)   # balance after each game, starting with the buy-in

    def __post_init__(self):
        self.starting_balance = self.balance
        self.history = [self.balance]

    def record_game(self, game_name: str) -> None:
        self.games_played[game_name] = self.games_played.get(game_name, 0) + 1
        self.history.append(self.balance)

    @property
    def net(self) -> float:
        return self.balance - self.starting_balance

    @property
    def total_sessions(self) -> int:
        return sum(self.games_played.values())
