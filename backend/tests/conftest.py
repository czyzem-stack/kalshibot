"""Force plain logging in tests (before ``backend.app.main`` is imported and ``configure_logging`` runs)."""
from __future__ import annotations

import os

# Must run before any import of `app` that would load settings / main.
os.environ.setdefault("LOG_JSON", "0")
os.environ.setdefault("LOG_LEVEL", "INFO")
