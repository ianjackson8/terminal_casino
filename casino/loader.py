import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class Plugin:
    key: str
    name: str
    description: str
    min_bet: float
    run: Callable
    overrides: dict


def discover_plugins(plugins_dir: Path, enabled: list, overrides: dict,
                     warn: Callable[[str], None] = print) -> list[Plugin]:
    """
    Scan plugins_dir for subdirectories containing plugin.py.
    Returns registered Plugin objects in the order listed in enabled
    (or discovery order if enabled is empty).
    """
    found: dict[str, Plugin] = {}

    for subdir in sorted(plugins_dir.iterdir()):
        if not subdir.is_dir():
            continue
        plugin_file = subdir / "plugin.py"
        if not plugin_file.exists():
            continue

        key = subdir.name
        spec = importlib.util.spec_from_file_location(f"plugins.{key}.plugin", plugin_file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            warn(f"Failed to load plugin '{key}': {exc}")
            continue

        meta = getattr(module, "PLUGIN_META", None)
        run_fn = getattr(module, "run", None)
        if meta is None or run_fn is None:
            warn(f"Plugin '{key}' missing PLUGIN_META or run() — skipped.")
            continue

        found[key] = Plugin(
            key=key,
            name=meta.get("name", key),
            description=meta.get("description", ""),
            min_bet=meta.get("min_bet", 0.0),
            run=run_fn,
            overrides=overrides.get(key, {}),
        )

    if enabled:
        result = []
        for k in enabled:
            if k in found:
                result.append(found[k])
            else:
                warn(f"Enabled plugin '{k}' not found in plugins/ — skipped.")
        return result

    return list(found.values())
