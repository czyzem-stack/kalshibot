from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .settings_env import env

logger = logging.getLogger("kalshibot.alert")

# key = "branch|first N chars of message" -> monotonic time of last successful POST
_last_post_mono: dict[str, float] = {}


def _slack_url(url: str) -> bool:
    u = url.lower()
    return "hooks.slack.com" in u


async def notify_branch_engine_error(*, branch: str, message: str) -> None:
    """
    POST when an engine branch gets a new non-empty ``last_error``.

    - **Discord** incoming webhooks: JSON ``{"content": "..."}``.
    - **Slack** incoming webhooks: JSON ``{"text": "..."}``.
    """
    url = (env.alert_webhook_url or "").strip()
    if not url or not message.strip():
        return
    min_gap = max(5.0, float(env.alert_webhook_min_seconds or 120.0))
    key = f"{branch}|{message[:120]}"
    now = time.monotonic()
    if now - _last_post_mono.get(key, 0.0) < min_gap:
        return

    text = f"[kalshibot] {branch}: {message[:1800]}"
    payload: dict[str, str] = {"text": text} if _slack_url(url) else {"content": text}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        _last_post_mono[key] = now
    except Exception as e:
        logger.warning("alert_webhook post failed: %s", e)


async def post_branch_error_alerts(
    engines: dict[str, Any], *, prev_errors: dict[str, str | None]
) -> None:
    """If ``last_error`` for a branch is new or changed, enqueue a webhook POST. Updates *prev_errors* in place."""
    for br, eng in engines.items():
        cur = getattr(getattr(eng, "state", None), "last_error", None)
        cur_s = str(cur).strip() if cur else ""
        prev_raw = prev_errors.get(br)
        prev_s = str(prev_raw).strip() if prev_raw else ""
        if cur_s and cur_s != prev_s:
            asyncio.create_task(notify_branch_engine_error(branch=br, message=cur_s))
        prev_errors[br] = cur_s if cur_s else None
