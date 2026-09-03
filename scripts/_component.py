"""Import the integration's protocol modules without pulling in Home Assistant.

``custom_components/panasonic_wifan/__init__.py`` imports Home Assistant, so the
package cannot be imported normally from a plain Python process. This builds a
stand-in package whose ``__init__`` never runs, so the protocol modules — which
need nothing beyond aiohttp — can be loaded by tests and by the discovery
scripts.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "panasonic_wifan"
)
PACKAGE = "panasonic_wifan_protocol"


def load(*names: str):
    """Load the named modules from the integration, returning them in order."""
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(COMPONENT_DIR)]
        sys.modules[PACKAGE] = package

    modules = []
    for name in names:
        qualified = f"{PACKAGE}.{name}"
        if qualified not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                qualified, COMPONENT_DIR / f"{name}.py"
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load {name} from {COMPONENT_DIR}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[qualified] = module
            spec.loader.exec_module(module)
        modules.append(sys.modules[qualified])

    return modules[0] if len(modules) == 1 else modules


def use_threaded_dns() -> None:
    """Resolve host names with the standard library instead of aiodns.

    aiohttp reaches for aiodns whenever it is installed, and the aiodns/pycares
    pair drifts out of step often enough to break these scripts with a
    ``TypeError`` from inside the resolver. A script makes a handful of
    requests, so the threaded resolver costs nothing.
    """
    from aiohttp import connector, resolver

    connector.DefaultResolver = resolver.ThreadedResolver
