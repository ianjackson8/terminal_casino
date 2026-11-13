'''
Tables: one game can be offered at several tables with different stakes and rules, like a real
casino floor. Tables are configured on the casino side (game_settings.json → "tables"); a game
only declares which rules it accepts (PLUGIN_META["rules"]) and plays by the table it's handed.

    "tables": [
        {"id": "bj_high", "game": "ai_blackjack", "name": "High Roller",
         "min_bet": 100, "max_bet": 5000, "rules": {"num_decks": 2}}
    ]

Every game also gets a default table (id = plugin key, its PLUGIN_META min bet, default rules)
unless it has configured tables.

Author: Ian Jackson
'''

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RULE_TYPES = {"int", "float", "bool", "choice"}
TABLE_FIELDS = {"id", "game", "name", "min_bet", "max_bet", "rules"}


@dataclass
class Table:
    id: str
    plugin: object                  # casino.loader.Plugin
    name: str
    min_bet: float
    max_bet: Optional[float]
    rules: Dict[str, object] = field(default_factory=dict)   # full rule set: defaults + overrides
    overrides: Dict[str, object] = field(default_factory=dict)
    is_default: bool = False

    @property
    def label(self) -> str:
        '''Name used in logs and stats. The game's original table (id = plugin key) keeps the plain game
        name, so its stats carry over when other tables are added.'''
        if self.is_default or self.id == self.plugin.key:
            return self.plugin.name
        return f"{self.plugin.name} · {self.name}"

    def to_run_arg(self) -> dict:
        '''The `table` argument handed to the game's run().'''
        return {"id": self.id, "name": self.name, "min_bet": self.min_bet,
                "max_bet": self.max_bet, "rules": dict(self.rules)}

    def to_config(self) -> dict:
        return {"id": self.id, "game": self.plugin.key, "name": self.name, "min_bet": self.min_bet,
                "max_bet": self.max_bet, "rules": dict(self.overrides)}


#== Rule schema (declared by games) ==#

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_rule_value(spec: dict, value) -> Optional[str]:
    '''Why `value` isn't valid for a rule spec, or None if it is.'''
    kind = spec.get("type")
    if kind == "bool":
        return None if isinstance(value, bool) else "must be true or false"
    if kind == "choice":
        choices = spec.get("choices", [])
        return None if value in choices else f"must be one of {', '.join(map(str, choices))}"
    if kind == "int" and not (isinstance(value, int) and not isinstance(value, bool)):
        return "must be a whole number"
    if kind == "float" and not _is_number(value):
        return "must be a number"
    if "min" in spec and value < spec["min"]:
        return f"must be at least {spec['min']}"
    if "max" in spec and value > spec["max"]:
        return f"must be at most {spec['max']}"
    return None


def check_rule_schema(schema) -> List[str]:
    '''Problems with a game's PLUGIN_META["rules"] declaration.'''
    if not isinstance(schema, dict):
        return [f"must be a dict of rule name → spec, not {type(schema).__name__}"]
    problems = []
    for name, spec in schema.items():
        where = f"rule '{name}'"
        if not isinstance(name, str) or not ID_RE.match(name):
            problems.append(f"{where}: names must be lowercase snake_case")
        if not isinstance(spec, dict):
            problems.append(f"{where}: spec must be a dict")
            continue
        kind = spec.get("type")
        if kind not in RULE_TYPES:
            problems.append(f"{where}: type must be one of {', '.join(sorted(RULE_TYPES))}")
            continue
        if not isinstance(spec.get("label"), str) or not spec["label"].strip():
            problems.append(f"{where}: needs a 'label'")
        if kind == "choice" and (not isinstance(spec.get("choices"), list) or not spec["choices"]):
            problems.append(f"{where}: a choice rule needs a non-empty 'choices' list")
            continue
        for bound in ("min", "max"):
            if bound in spec and not _is_number(spec[bound]):
                problems.append(f"{where}: '{bound}' must be a number")
        if "default" not in spec:
            problems.append(f"{where}: needs a 'default'")
        else:
            why = check_rule_value(spec, spec["default"])
            if why:
                problems.append(f"{where}: default {spec['default']!r} {why}")
    return problems


def default_rules(schema: dict) -> dict:
    return {name: spec["default"] for name, spec in (schema or {}).items()}


def format_rule(spec: dict, value) -> str:
    label = spec.get("label", "?")
    if spec.get("type") == "bool":
        return label if value else f"no {label[0].lower() + label[1:]}"
    return f"{label} {value}"


def rules_summary(table: Table) -> str:
    '''Short description of how this table differs from the game's defaults.'''
    schema = getattr(table.plugin, "rules", {}) or {}
    parts = [format_rule(schema[k], v) for k, v in table.overrides.items() if k in schema]
    return " · ".join(parts)


#== Table config (game_settings.json) ==#

def check_table_config(cfg, plugin, seen_ids: set) -> List[str]:
    '''Problems with one entry of game_settings.json "tables" for an installed plugin.'''
    if not isinstance(cfg, dict):
        return ["each table must be an object"]
    problems = []
    tid = cfg.get("id")
    if not isinstance(tid, str) or not ID_RE.match(tid):
        problems.append(f"id {tid!r} must be lowercase snake_case")
    elif tid in seen_ids:
        problems.append(f"id '{tid}' is used by another table")
    if not isinstance(cfg.get("name"), str) or not cfg["name"].strip():
        problems.append("needs a 'name'")
    lo, hi = cfg.get("min_bet"), cfg.get("max_bet")
    if not _is_number(lo) or lo < 0:
        problems.append(f"min_bet must be a number >= 0 (got {lo!r})")
    if hi is not None and (not _is_number(hi) or (_is_number(lo) and hi < lo)):
        problems.append(f"max_bet must be empty or a number >= min_bet (got {hi!r})")
    unknown = set(cfg) - TABLE_FIELDS
    if unknown:
        problems.append(f"unknown field(s) {', '.join(sorted(unknown))}")
    if not getattr(plugin, "accepts_table", False):
        problems.append(f"{plugin.name} v{plugin.version} doesn't accept table settings "
                        "(its run() has no `table` parameter), so it can't run custom tables")
        return problems
    rules = cfg.get("rules", {})
    schema = getattr(plugin, "rules", {}) or {}
    if not isinstance(rules, dict):
        problems.append("rules must be an object")
        return problems
    for name, value in rules.items():
        if name not in schema:
            supported = ", ".join(schema) or "none"
            problems.append(f"rule '{name}' isn't supported by {plugin.name} (supported: {supported})")
            continue
        why = check_rule_value(schema[name], value)
        if why:
            problems.append(f"rule '{name}' = {value!r} {why}")
    return problems


def build_tables(plugins: list, settings: dict, log: Callable[[str, str], None] = None) -> List[Table]:
    '''
    All valid tables, grouped by game in plugin order. Invalid table configs are skipped and logged.
    Disabled tables are included; filter with `disabled_tables` for the lobby.
    '''
    log = log or (lambda level, msg: None)
    by_key = {p.key: p for p in plugins}
    configured: Dict[str, List[dict]] = {}
    for cfg in settings.get("tables") or []:
        game = cfg.get("game") if isinstance(cfg, dict) else None
        if game not in by_key:
            log("warn", f"Table {cfg.get('id', '?') if isinstance(cfg, dict) else '?'}: game '{game}' isn't installed; skipped")
            continue
        configured.setdefault(game, []).append(cfg)

    tables: List[Table] = []
    seen: set = set(by_key)        # default table ids are the plugin keys
    for plugin in plugins:
        schema = getattr(plugin, "rules", {}) or {}
        cfgs = configured.get(plugin.key, [])
        valid = []
        for cfg in cfgs:
            # a configured table may reuse its own game's key as its id (it replaces the default table)
            problems = check_table_config(cfg, plugin, seen - {plugin.key})
            if problems:
                log("error", f"Table '{cfg.get('id', '?')}' ({plugin.name}) not opened: {problems[0]}"
                             + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""))
                continue
            seen.add(cfg["id"])
            overrides = dict(cfg.get("rules") or {})
            valid.append(Table(id=cfg["id"], plugin=plugin, name=cfg["name"].strip(),
                               min_bet=float(cfg["min_bet"]),
                               max_bet=None if cfg.get("max_bet") is None else float(cfg["max_bet"]),
                               rules={**default_rules(schema), **overrides}, overrides=overrides))
        if not valid:
            valid = [Table(id=plugin.key, plugin=plugin, name=plugin.name, min_bet=plugin.min_bet,
                           max_bet=None, rules=default_rules(schema), is_default=True)]
        tables.extend(valid)
    return tables


def open_tables(tables: List[Table], settings: dict) -> List[Table]:
    disabled = set(settings.get("disabled_tables") or [])
    return [t for t in tables if t.id not in disabled]


def bet_range(table: Table, money: Callable[[float], str]) -> str:
    if table.max_bet is None:
        return f"{money(table.min_bet)}+"
    return f"{money(table.min_bet)} – {money(table.max_bet)}"
