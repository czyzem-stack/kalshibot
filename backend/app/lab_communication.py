"""
In-process lab hive chat: Labs B / C / D publish short team-style lines for the dashboard ticker.

**v4:** Balanced rotation (~33% soft cap on proactive lines per lab), aggressive chain replies using
``last_from_other()`` (including reactions), short marquee-sized copy (≈75–95 chars).

Does **not** persist to SQLite; heartbeat + reaction traffic only.
"""

from __future__ import annotations

import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from .branch_config import BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D

LAB_CHATTER_BRANCHES = (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D)

_slog = structlog.get_logger("kalshibot.lab_chat")

_LAB_LABEL = {
    BRANCH_LAB_B: "Lab B",
    BRANCH_LAB_C: "Lab C",
    BRANCH_LAB_D: "Lab D",
}

# Marquee + fairness tuning (proactive posts honor share cap; reactive chains ignore it).
_MSG_SOFT_MAX = 92
_RECENT_SHARE_WINDOW = 48
_PROACTIVE_SHARE_CAP = 0.42  # soft cap on proactive lines; reactive chains ignore this
_HEARTBEAT_GAP_S = (12.0, 28.0)
_CHAIN_REPLY_GAP_S = 1.85  # lets two replies land on separate ticks without spamming one branch


class LabCommunicationBus:
    """Singleton ring buffer of recent hive messages (read by ``GET /labs/chat``)."""

    _instance: LabCommunicationBus | None = None

    def __init__(self) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=120)

    @classmethod
    def instance(cls) -> LabCommunicationBus:
        if cls._instance is None:
            cls._instance = LabCommunicationBus()
        return cls._instance

    def publish(
        self,
        lab: str,
        message: str,
        *,
        confidence: float | None = None,
        action: str | None = None,
        kind: str = "say",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "ts_iso": datetime.now(timezone.utc).isoformat(),
            "lab": lab,
            "label": _LAB_LABEL.get(lab, lab),
            "message": message,
            "kind": kind,
        }
        if confidence is not None:
            row["confidence"] = round(float(confidence), 4)
        if action:
            row["action"] = action
        self._dq.append(row)
        payload = {k: v for k, v in row.items() if v is not None}
        _slog.info("lab_chat_message", **payload)
        return row

    def recent(self) -> list[dict[str, Any]]:
        return list(self._dq)

    def last_from_other(self, lab: str, *, max_scan: int = 48) -> dict[str, Any] | None:
        """Most recent line from another lab (any kind — keeps agree/disagree chains coherent)."""
        for row in reversed(list(self._dq)[-max_scan:]):
            if row.get("lab") and row["lab"] != lab:
                return row
        return None


def get_lab_communication_bus() -> LabCommunicationBus:
    return LabCommunicationBus.instance()


def _clamp01(x: float | None) -> float | None:
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def _cap_msg(text: str, max_len: int = _MSG_SOFT_MAX) -> str:
    """Trim to ticker-friendly length without ugly mid-word breaks."""
    t = (text or "").strip().replace("\n", " ")
    if len(t) <= max_len:
        return t
    cut = t[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,; ") + "…"


def _recent_lab_share(bus: LabCommunicationBus, lab: str, *, window: int = _RECENT_SHARE_WINDOW) -> float:
    rows = list(bus._dq)[-window:]
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if r.get("lab") == lab)
    return hits / float(len(rows))


def _can_proactive_publish(bus: LabCommunicationBus, lab: str) -> bool:
    """Voluntary lines (heartbeat, headline scan) skip when this lab is above the soft share cap."""
    return _recent_lab_share(bus, lab) <= _PROACTIVE_SHARE_CAP


def _peer_nick(peer_row: dict[str, Any]) -> str:
    lab = str(peer_row.get("lab") or "")
    if lab == BRANCH_LAB_B:
        return "B"
    if lab == BRANCH_LAB_C:
        return "C"
    if lab == BRANCH_LAB_D:
        return "D"
    return "them"


def _publish_tracked(engine: Any, bus: LabCommunicationBus, lab: str, message: str, **kw: Any) -> dict[str, Any]:
    capped = _cap_msg(message)
    row = bus.publish(lab, capped, **kw)
    engine._lab_chatter_last_publish_mono = time.monotonic()
    return row


def _seconds_since_last_publish(engine: Any) -> float:
    return time.monotonic() - float(getattr(engine, "_lab_chatter_last_publish_mono", 0.0) or 0.0)


def _initial_heartbeat_delay(lab: str) -> float:
    """Stagger first beats so B/C/D all speak soon after restart without stacking one lab."""
    if lab == BRANCH_LAB_B:
        return random.uniform(3.5, 9.0)
    if lab == BRANCH_LAB_C:
        return random.uniform(6.0, 12.0)
    return random.uniform(8.5, 14.5)


def _heartbeat_message(lab: str, *, ticker_hint: str | None, scanned: int) -> tuple[str, float | None, str]:
    tick = (ticker_hint or "SCAN").strip()[:22]
    if lab == BRANCH_LAB_B:
        msg = random.choice(
            [
                f"{tick}: cautious take — playing it safe until spreads tighten.",
                f"{tick}: not convinced yet; clipping risk while structure proves itself.",
                f"{tick}: slow lane — waiting for confirmation before size.",
                f"Scanned {scanned} rows — {tick} needs cleaner tape before I commit.",
            ]
        )
        conf = random.uniform(0.42, 0.62)
        return msg, _clamp01(conf), "heartbeat"
    if lab == BRANCH_LAB_C:
        msg = random.choice(
            [
                f"{tick}: edge looks juicy — going hard if guardrails hold.",
                f"{tick}: I'm in if momentum confirms — pressing small then scaling.",
                f"{tick}: stalking continuation; aggression pays when flow agrees.",
                f"{tick}: tape looks alive — sizing up if next pass lights.",
            ]
        )
        conf = random.uniform(0.58, 0.88)
        return msg, _clamp01(conf), "heartbeat"
    msg = random.choice(
        [
            f"{tick}: wild idea — testing a chaotic hedge while paper stays cheap.",
            f"{tick}: D here being chaotic — probing weird-side convexity.",
            f"{tick}: sandbox curveball — I'll chase asymmetry others skip.",
            f"{tick}: experimental lane — stress-testing a spicy variant.",
        ]
    )
    conf = random.uniform(0.35, 0.92)
    return msg, _clamp01(conf), "heartbeat"


def _chain_reply(lab: str, peer_row: dict[str, Any]) -> tuple[str, float | None]:
    """Short agree / disagree / build-on reply referencing the other lab."""
    nick = _peer_nick(peer_row)
    peer_lab = str(peer_row.get("lab") or "")
    snippet = _cap_msg(str(peer_row.get("message") or ""), 36)

    if lab == BRANCH_LAB_B:
        opts = [
            f"{nick}: cautious take — I'll fade speed, not always direction.",
            f"Hearing {nick}: playing it safe until that thesis survives another pass.",
            f"{nick} went loud ({snippet}) — I'm smaller until liquidity proves it.",
            f"Interesting from {nick} — still sitting out until spreads behave.",
            f"Align partly with {nick}: not convinced yet on timing — watching.",
        ]
        if peer_lab == BRANCH_LAB_C:
            opts.extend(
                [
                    f"C you're aggressive — I'll hedge your YES lean with tight risk.",
                    f"Cool heat from C — B waits for a cleaner NO entry.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"D that's chaotic — wild idea, I'll paper-tiny the hedge side.",
                    f"D pushing weird risk — I'm only nibbling after confirmation.",
                ]
            )
        text = random.choice(opts)
        return text, random.uniform(0.44, 0.62)

    if lab == BRANCH_LAB_C:
        opts = [
            f"{nick}: agree on setup — I'm sizing small then leaning in if tape confirms.",
            f"I'm with {nick} but going hard only if flow holds — edge looks juicy.",
            f"Piggybacking {nick}: momentum wins here if we don't choke execution.",
            f"{nick} ({snippet}) — I'll press while liquidity prints.",
            f"Pushback gently: {nick} might be early — I'm still tempted to hit.",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend(
                [
                    f"B stays cautious — I'll buy dips faster if your NO thesis cracks.",
                    f"B playing defense — C grabs convex YES when rules align.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"D you're chaotic — C rides your chaos with tighter stops.",
                    f"D wild idea — I'm amplifying if volatility expands.",
                ]
            )
        text = random.choice(opts)
        return text, random.uniform(0.62, 0.86)

    opts = [
        f"{nick}: testing something crazy — skew opposite tail just to learn.",
        f"Building on {nick}: I'll run a sandbox twist with higher variance.",
        f"{nick} ({snippet}) — disagree on timing, agree there's asymmetry.",
        f"D here being chaotic — remixing {nick}'s frame with weirder fills.",
        f"What do you think {nick}? I'm piloting a funky hedge variant.",
    ]
    if peer_lab == BRANCH_LAB_B:
        opts.extend(
            [
                f"B you're tight — I'll chase convex chaos around your caution.",
                f"B says wait — D runs tiny lottery tickets anyway.",
            ]
        )
    elif peer_lab == BRANCH_LAB_C:
        opts.extend(
            [
                f"C you're wild — I'll bolt experimental exits onto your momentum.",
                f"C going hard — I'll pair it with oddball structure for tail juice.",
            ]
        )
    text = random.choice(opts)
    return text, random.uniform(0.38, 0.78)


def publish_chain_reply_if_due(engine: Any, branch: str, bus: LabCommunicationBus) -> None:
    """React to the last other-lab line whenever cooldown allows (no heavy RNG gate)."""
    if branch not in LAB_CHATTER_BRANCHES:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    if _seconds_since_last_publish(engine) < _CHAIN_REPLY_GAP_S:
        return

    msg, conf = _chain_reply(branch, peer)
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action="chain_reply", kind="say")
    engine._lab_chatter_last_reaction_mono = time.monotonic()


def publish_heartbeat_if_due(
    engine: Any,
    branch: str,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    bus: LabCommunicationBus,
) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    now_m = time.monotonic()
    nxt = float(getattr(engine, "_lab_chatter_next_heartbeat_mono", 0.0) or 0.0)

    if nxt <= 0.0:
        engine._lab_chatter_next_heartbeat_mono = now_m + _initial_heartbeat_delay(branch)
        return

    if now_m < nxt:
        return

    if not _can_proactive_publish(bus, branch):
        # Soft cap: defer rather than blast — reactions still carry the conversation.
        engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(5.0, 11.0)
        return

    # Heartbeats share the same cadence bucket for every breeder lab.
    engine._lab_chatter_next_heartbeat_mono = now_m + random.uniform(*_HEARTBEAT_GAP_S)

    hint = None
    for snap in snapshots.values():
        if isinstance(snap, dict):
            t = snap.get("ticker") or snap.get("market_ticker")
            if t:
                hint = str(t)
                break
    msg, conf, kind = _heartbeat_message(branch, ticker_hint=hint or "markets", scanned=scanned)
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action=kind)


def chatter_on_ranked_market(
    engine: Any,
    branch: str,
    *,
    idx: int,
    kind: str | None,
    ticker: str,
    implied_yes: float | None,
    bus: LabCommunicationBus,
) -> None:
    """Immediate chatter on ranked-market evaluation (throttled per tick)."""
    if branch not in LAB_CHATTER_BRANCHES:
        return
    n = int(getattr(engine, "_lab_chatter_msgs_this_tick", 0) or 0)
    if n >= 7:
        return
    tk = (ticker or "").strip()[:18] or "?"
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None
    side_hint = f"{pct}% YES" if pct is not None else "YES ?"

    # Only one proactive headline per tick per lab — prevents asset-loop flooding from crowding others out.
    if idx == 0:
        if not bool(getattr(engine, "_lab_chatter_headline_sent", False)) and _can_proactive_publish(bus, branch):
            engine._lab_chatter_headline_sent = True
            if branch == BRANCH_LAB_B:
                msg = f"B → cautious read on {tk} (~{side_hint}) — want cleaner odds before size."
            elif branch == BRANCH_LAB_C:
                msg = f"C → lead pick {tk} (~{side_hint}) — going hard if gates stay green."
            else:
                msg = f"D → wild angle on {tk} (~{side_hint}) — testing chaotic convexity."
            conf = py if py is not None else random.uniform(0.52, 0.76)
            _publish_tracked(engine, bus, branch, msg, confidence=_clamp01(conf), action="market_scan")
            engine._lab_chatter_msgs_this_tick = n + 1
        return

    if kind == "no_rule" and idx < 4 and random.random() < 0.55:
        if not _can_proactive_publish(bus, branch):
            return
        if branch == BRANCH_LAB_B:
            msg = f"{tk}: no rule match (~{side_hint}) — skipping; edge not proved."
        elif branch == BRANCH_LAB_C:
            msg = f"{tk}: no aligned rule (~{side_hint}) — still tempted but passing."
        else:
            msg = f"{tk}: pass (~{side_hint}) — chasing chaos elsewhere unless rule fires."
        _publish_tracked(engine, bus, branch, msg, confidence=_clamp01(py), action="skip_no_rule")
        engine._lab_chatter_msgs_this_tick = n + 1
    elif idx < 4 and random.random() < 0.82:
        peer = bus.last_from_other(branch)
        if peer and _seconds_since_last_publish(engine) >= _CHAIN_REPLY_GAP_S:
            msg, conf = _chain_reply(branch, peer)
            _publish_tracked(engine, bus, branch, msg, confidence=conf, action="scan_chain", kind="say")
            engine._lab_chatter_msgs_this_tick = n + 1


def chatter_on_sim_open(engine: Any, branch: str, *, ticker: str, side: str, implied_yes: float | None, rule_name: str, bus: LabCommunicationBus) -> None:
    if branch not in LAB_CHATTER_BRANCHES:
        return
    tk = (ticker or "").strip()[:16]
    py = _clamp01(implied_yes)
    pct = int(round((py or 0.0) * 100)) if py is not None else None
    rn = (rule_name or "").strip()[:22]
    ys = f"{pct}%" if pct is not None else "?%"
    if branch == BRANCH_LAB_B:
        msg = f"Sim {side.upper()} {tk} (~{ys} YES) via “{rn}” — tiny size, reversible."
    elif branch == BRANCH_LAB_C:
        msg = f"Filled sim {side.upper()} {tk} (~{ys}) — rule “{rn}”; pressing edge."
    else:
        msg = f"Sandbox {side.upper()} {tk} (~{ys}) — “{rn}”; chaotic tiny test."
    _publish_tracked(engine, bus, branch, msg, confidence=py, action=f"open_sim_{side}")


def finalize_lab_chatter_tick(engine: Any, branch: str, snapshots: dict[str, dict[str, Any]], scanned: int) -> None:
    """Chain replies first (team banter), heartbeat second — keeps Labs B/C/D visibly alive."""
    if branch not in LAB_CHATTER_BRANCHES:
        return
    bus = get_lab_communication_bus()

    # One guaranteed opener per lab process — ticker feels alive immediately after restart (before heartbeat primes).
    if not getattr(engine, "_lab_chatter_bootstrap_done", False):
        engine._lab_chatter_bootstrap_done = True
        hint = None
        for snap in snapshots.values():
            if isinstance(snap, dict):
                t = snap.get("ticker") or snap.get("market_ticker")
                if t:
                    hint = str(t)
                    break
        msg, conf, kind = _heartbeat_message(branch, ticker_hint=hint or "markets", scanned=max(1, int(scanned)))
        _publish_tracked(engine, bus, branch, msg, confidence=conf, action=f"{kind}_bootstrap")
        engine._lab_chatter_next_heartbeat_mono = time.monotonic() + random.uniform(*_HEARTBEAT_GAP_S)

    publish_chain_reply_if_due(engine, branch, bus)
    publish_chain_reply_if_due(engine, branch, bus)
    publish_heartbeat_if_due(engine, branch, snapshots=snapshots, scanned=scanned, bus=bus)
    publish_chain_reply_if_due(engine, branch, bus)
