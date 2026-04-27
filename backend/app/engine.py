"""Compatibility re-exports. Trading logic lives in :mod:`app.engines` (``engine`` + ``dual_engine_loop``).

# LABS BREEDING v0.1 IMPROVEMENT — real active children + stronger competitive traits + better toasts.
Internal breeding/adoption runs on the optimizer cadence (``optimizer_claude`` / ``lab_breeding``), not inside the
per-branch tick loop.
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
