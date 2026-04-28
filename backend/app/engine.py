"""Compatibility re-exports. Trading logic lives in :mod:`app.engines` (``engine`` + ``dual_engine_loop``).

**Two “testing” paths (see ``.cursor/rules/architecture-breeding.md``):** (1) this module and ``dual_engine_loop`` drive
**visible** paper PnL for Live + Lab A–D (+ child engines). (2) **B/C/D child-lab** breeding/GA is scheduled from
``optimizer_claude`` / ``lab_breeding``; it is **not** what updates the B/C/D chart by itself. Breeding can run on the
interval even when ``optimizer.enabled`` and ``adaptive_enabled`` are false, if ``breeding_enabled`` is true.
"""

from __future__ import annotations
import sys
from types import ModuleType

from .engines import engine as _engine
from .engines.dual_engine_loop import dual_engine_loop

# ``import *`` omits private module-level names; ``app.*`` and tests need ``_name`` re-exports.
_m: ModuleType = sys.modules[__name__]
_skip = {
    "__name__",
    "__file__",
    "__package__",
    "__doc__",
    "__spec__",
    "__loader__",
    "__cached__",
    "__builtins__",
    "__annotations__",
    "__dict__",
    "__all__",
}
for _k, _v in vars(_engine).items():
    if _k in _skip:
        continue
    if _k.startswith("__"):
        continue
    setattr(_m, _k, _v)
setattr(_m, "dual_engine_loop", dual_engine_loop)
