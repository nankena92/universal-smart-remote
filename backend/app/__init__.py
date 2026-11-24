"""``app`` package wrapper.

Layout quirk: the FastAPI entrypoint lives in ``backend/app.py`` while the
sub-packages live in ``backend/app/``. Python resolves the name ``app`` to
the *package* when both exist, so this ``__init__`` loads ``../app.py`` once
(via importlib, under the private name ``_smart_remote_entry``) and
re-exports its ``app`` (the FastAPI instance). That makes all of these work:

- ``uvicorn app:app`` / ``from app import app`` with ``backend/`` on ``sys.path``
- ``python backend/app.py`` (run as ``__main__``; the entry is loaded a
  second time under its private name, sharing the imported submodules)
- ``from app.adapters import get_adapter`` (adapters package, unaffected)

If the entrypoint cannot be loaded (e.g. FastAPI is not installed in the
current environment), the failure is swallowed so that importing the
sub-packages — e.g. ``app.adapters`` in the adapters-only test suite —
keeps working; only ``from app import app`` is then unavailable.
"""

from __future__ import annotations

import importlib.util
import sys
import warnings
from pathlib import Path

_ENTRY_NAME = "_smart_remote_entry"

if _ENTRY_NAME not in sys.modules:
    _entry_path = Path(__file__).resolve().parent.parent / "app.py"
    if _entry_path.is_file():
        try:
            _spec = importlib.util.spec_from_file_location(_ENTRY_NAME, _entry_path)
            if _spec is not None and _spec.loader is not None:
                _mod = importlib.util.module_from_spec(_spec)
                sys.modules[_ENTRY_NAME] = _mod
                _spec.loader.exec_module(_mod)
                app = _mod.app
                __all__ = ["app"]
        except Exception as exc:  # noqa: BLE001 - keep adapters importable
            warnings.warn(
                f"Could not load backend entrypoint {_entry_path}: {exc}. "
                "Sub-packages (e.g. app.adapters) remain importable, but "
                "'from app import app' is unavailable.",
                RuntimeWarning,
                stacklevel=2,
            )
    else:  # pragma: no cover - entrypoint missing entirely
        warnings.warn(
            "backend/app.py not found next to the app package.",
            RuntimeWarning,
            stacklevel=2,
        )
else:  # pragma: no cover - entry already loaded (e.g. __main__ run)
    app = sys.modules[_ENTRY_NAME].app
    __all__ = ["app"]
