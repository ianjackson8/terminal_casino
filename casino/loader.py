'''
Plugin discovery. Every game folder under plugins/ is run through the compliance checks
(casino.compliance); a game with any compliance error is not loaded.

Author: Ian Jackson
'''

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List

from casino.compliance import check_plugin

# log(level, message) with level "error" (game blocked) or "warn" (loaded, with warnings)
LogFn = Callable[[str, str], None]


@dataclass
class Plugin:
    key: str
    name: str
    description: str
    min_bet: float
    run: Callable
    overrides: dict
    version: str = ""
    path: Path = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class Blocked:
    key: str
    errors: List[str]


def _default_log(level: str, message: str) -> None:
    print(f"  [loader] {message}")


def discover_plugins(plugins_dir: Path, overrides: dict, log: LogFn = _default_log,
                     blocked: List[Blocked] = None) -> List[Plugin]:
    '''
    Scan plugins_dir for game folders, check each one, and return the compliant ones in
    folder-name order. Non-compliant games are logged and, if `blocked` is given, appended to it.
    '''
    found: List[Plugin] = []
    taken: Dict[str, str] = {}     # module name -> plugin key, to catch collisions between games

    if not plugins_dir.exists():
        return found
    for subdir in sorted(plugins_dir.iterdir()):
        if not subdir.is_dir() or subdir.name.startswith((".", "_")):
            continue
        key = subdir.name
        report = check_plugin(subdir, key=key, taken=taken)
        if not report.ok:
            errors = [f"{e.check}: {e.message}" for e in report.errors]
            more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
            log("error", f"Blocked '{key}': {errors[0]}{more}. Run: python -m casino.check {key}")
            if blocked is not None:
                blocked.append(Blocked(key, errors))
            continue

        for mod in report.modules:
            taken.setdefault(mod, key)
        meta = report.meta
        warnings = [f"{w.check}: {w.message}" for w in report.warnings]
        if warnings:
            log("warn", f"{meta['name']} v{meta['version']} loaded with {len(warnings)} warning"
                        f"{'s' if len(warnings) != 1 else ''}. Run: python -m casino.check {key}")
        found.append(Plugin(
            key=key,
            name=meta["name"],
            description=meta["description"],
            min_bet=float(meta["min_bet"]),
            run=report.module.run,
            overrides=overrides.get(key, {}),
            version=meta["version"],
            path=subdir,
            warnings=warnings,
        ))
    return found
