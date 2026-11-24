"""Brand registry and adapter factory (CONTRACTS.md §1).

Imports are lazy inside :func:`get_adapter` so this module imports cleanly
even when some adapter modules do not exist yet; an honest error is raised
only when a missing brand is actually requested.
"""

from __future__ import annotations

import importlib
import os
from typing import Dict, Tuple

from .base import DeviceInfo, TvAdapter

BRANDS = {
    "samsung": "Samsung (Tizen)",
    "lg": "LG (webOS)",
    "sony": "Sony Bravia",
    "androidtv": "Android TV",
    "googletv": "Google TV",
    "tcl": "TCL",
    "roku": "Roku TV",
    "firetv": "Amazon Fire TV",
    "mock": "Mock TV (testing only)",
}

# brand -> (module name under this package, adapter class name).
# "googletv" is an alias of the Android TV adapter (CONTRACTS.md §1).
_ADAPTERS: Dict[str, Tuple[str, str]] = {
    "samsung": ("samsung", "SamsungAdapter"),
    "lg": ("lg", "LgAdapter"),
    "sony": ("sony", "SonyAdapter"),
    "androidtv": ("android_tv", "AndroidTvAdapter"),
    "googletv": ("android_tv", "AndroidTvAdapter"),
    "tcl": ("tcl", "TclAdapter"),
    "roku": ("roku", "RokuAdapter"),
    "firetv": ("fire_tv", "FireTvAdapter"),
    "mock": ("mock", "MockAdapter"),
}


def get_adapter(device: DeviceInfo) -> TvAdapter:
    """Return the adapter for ``device.brand``.

    Raises an honest error (never a fake adapter) when the brand is unknown,
    when the brand's adapter module is not implemented yet, or when the mock
    adapter is requested without ``MOCK_TV=true`` (CONTRACTS.md §1: the mock
    adapter must never be reachable unless the backend is started with
    ``MOCK_TV=true``).
    """
    brand = (device.brand or "").strip().lower()
    if brand not in BRANDS:
        raise ValueError(
            f"Unknown TV brand: {device.brand!r}. "
            f"Supported brands: {', '.join(sorted(BRANDS))}."
        )
    if brand == "mock" and os.environ.get("MOCK_TV", "").lower() != "true":
        raise RuntimeError(
            "The Mock TV adapter is only available when the backend is "
            "started with MOCK_TV=true."
        )
    module_name, class_name = _ADAPTERS[brand]
    try:
        module = importlib.import_module(f".{module_name}", __package__)
    except ImportError as exc:
        raise RuntimeError(
            f"The {BRANDS[brand]} adapter is not implemented yet."
        ) from exc
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise RuntimeError(
            f"The {BRANDS[brand]} adapter module does not define "
            f"{class_name}."
        ) from exc
    return cls(device)


__all__ = ["BRANDS", "get_adapter", "DeviceInfo", "TvAdapter"]
