"""
Breeding Council / Lab Think Tank — Labs B, C, D publish short lines with explicit conversational threading.

Rolling **last 6** bus lines drive prompts; every line reacts to **other labs** by name; optional ``reply_to`` UUID ties replies.
**55–65** chars target; council **6–15s**; ranked-market hook emits **no tickers** (dialogue-only Think Tank).

Not persisted. Observational only. ``GET /labs/chat`` unchanged contract (+ optional ``reply_to`` field).
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

LAB_THINK_TANK_BRANCHES = (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D)
LAB_CHATTER_BRANCHES = LAB_THINK_TANK_BRANCHES

_slog = structlog.get_logger("kalshibot.think_tank")

_LAB_LABEL = {
    BRANCH_LAB_B: "Lab B",
    BRANCH_LAB_C: "Lab C",
    BRANCH_LAB_D: "Lab D",
}

_MSG_SOFT_MAX = 62  # dialogue-only strip; ~55–65 chars effective
_CONV_MEMORY = 6  # tail scanned for “reply to last 1–2 other labs”
_RECENT_SHARE_WINDOW = 14  # shorter window — faster recovery from skew
_PROACTIVE_SHARE_CAP = 0.46  # old 0.31 caused long silent stretches (strategic pulse kept deferring)
_BOOTSTRAP_BUS_LINES = 16  # until this many rows exist, don’t throttle proactive voice (seed the thread)
_STRATEGIC_PULSE_GAP_S = (7.0, 16.0)
_INTRO_NEXT_STRATEGIC_GAP_S = (3.0, 8.0)
_COUNCIL_REPLY_GAP_S = (6.0, 15.0)
_SIM_BRANCH_PUBLISH_GAP_S = 12.0


class LabCommunicationBus:
    """Singleton ring buffer (read by ``GET /labs/chat``)."""

    _instance: LabCommunicationBus | None = None

    def __init__(self) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=96)

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
        reply_to: str | None = None,
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
        if reply_to:
            row["reply_to"] = reply_to
        self._dq.append(row)
        payload = {k: v for k, v in row.items() if v is not None}
        _slog.info("think_tank_message", **payload)
        return row

    def recent(self) -> list[dict[str, Any]]:
        return list(self._dq)

    def last_from_other(self, lab: str, *, max_scan: int = 40) -> dict[str, Any] | None:
        for row in reversed(list(self._dq)[-max_scan:]):
            if row.get("lab") and row["lab"] != lab:
                return row
        return None


def get_lab_communication_bus() -> LabCommunicationBus:
    return LabCommunicationBus.instance()


def conversation_tail(bus: LabCommunicationBus, limit: int = _CONV_MEMORY) -> list[dict[str, Any]]:
    """Last ``limit`` rows in the global thread (chronological)."""
    rows = list(bus._dq)
    if not rows:
        return []
    return rows[-limit:]


def thread_other_lines(bus: LabCommunicationBus, lab: str, limit: int = _CONV_MEMORY) -> list[dict[str, Any]]:
    """Recent rows in the tail from labs != ``lab``."""
    return [r for r in conversation_tail(bus, limit) if r.get("lab") and r["lab"] != lab]


def _voice_prefix(branch: str) -> str:
    """Inline speaker tag — reads like chat."""
    if branch == BRANCH_LAB_B:
        return "B:"
    if branch == BRANCH_LAB_C:
        return "C:"
    if branch == BRANCH_LAB_D:
        return "D:"
    return "?:"


def _clamp01(x: float | None) -> float | None:
    if x is None:
        return None
    return max(0.0, min(1.0, float(x)))


def _cap_msg(text: str, max_len: int = _MSG_SOFT_MAX) -> str:
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


def _needs_voice_turn(bus: LabCommunicationBus, branch: str) -> bool:
    """Prefer labs absent or behind in the recent tail so B/C/D all stay in the loop."""
    rows = list(bus._dq)[-8:]
    labs_seq = [str(r.get("lab") or "") for r in rows if str(r.get("lab") or "") in LAB_THINK_TANK_BRANCHES]
    if branch not in LAB_THINK_TANK_BRANCHES:
        return False
    if not labs_seq:
        return True
    seen = {lb for lb in labs_seq[-6:]}
    # Not all three represented recently → whoever's missing gets priority.
    if len(seen) < 3 and branch not in seen:
        return True
    if branch not in labs_seq[-4:]:
        return True
    counts = {BRANCH_LAB_B: 0, BRANCH_LAB_C: 0, BRANCH_LAB_D: 0}
    for lb in labs_seq:
        if lb in counts:
            counts[lb] += 1
    mx = max(counts.values()) if counts else 0
    return counts.get(branch, 0) < mx


def _can_proactive_voice(bus: LabCommunicationBus, lab: str) -> bool:
    # Early thread: allow everyone to speak so the UI isn’t an empty box waiting on share math.
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return True
    if _needs_voice_turn(bus, lab):
        return True
    return _recent_lab_share(bus, lab) <= _PROACTIVE_SHARE_CAP


def _optimizer_breeding_enabled(full_cfg: dict[str, Any] | None) -> bool:
    if not full_cfg or not isinstance(full_cfg.get("optimizer"), dict):
        return False
    oc = full_cfg["optimizer"]
    return bool(oc.get("breeding_enabled", True))


def _peer_nick(peer_row: dict[str, Any]) -> str:
    lab = str(peer_row.get("lab") or "")
    if lab == BRANCH_LAB_B:
        return "B"
    if lab == BRANCH_LAB_C:
        return "C"
    if lab == BRANCH_LAB_D:
        return "D"
    return "?"


def _publish_tracked(engine: Any, bus: LabCommunicationBus, lab: str, message: str, **kw: Any) -> dict[str, Any]:
    capped = _cap_msg(message)
    row = bus.publish(lab, capped, **kw)
    engine._lab_think_tank_last_publish_mono = time.monotonic()
    return row


def _seconds_since_publish(engine: Any) -> float:
    return time.monotonic() - float(getattr(engine, "_lab_think_tank_last_publish_mono", 0.0) or 0.0)


def _strip_voice_prefix(msg: str) -> str:
    s = (msg or "").strip()
    for pref in ("B:", "C:", "D:", "b:", "c:", "d:"):
        if s.startswith(pref):
            s = s[len(pref) :].strip()
            break
    return s


def _peer_blurb(peer_row: dict[str, Any] | None, *, max_len: int = 18) -> str:
    """Short echo of what another lab said — human phrasing, no symbols."""
    raw = _strip_voice_prefix(str((peer_row or {}).get("message") or ""))
    if not raw:
        return "that"
    return _cap_msg(raw, max_len)


def _team_peer_reply_line(
    branch: str,
    peer_row: dict[str, Any],
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
) -> tuple[str, float | None]:
    """Natural reply to another lab — names only, no markets/tickers."""
    voc = _voice_prefix(branch)
    nick = _peer_nick(peer_row)
    peer_lab = str(peer_row.get("lab") or "")
    blur = _peer_blurb(peer_row, max_len=16)

    team_tag = ""
    if breeding_enabled and random.random() < 0.32:
        team_tag = random.choice([" Team—breed next.", " Team—kid genome.", " Kid crossover?", ""]).strip()

    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    nick2 = ""
    if len(others) >= 2:
        cand = others[-2]
        if cand.get("id") != peer_row.get("id"):
            nick2 = _peer_nick(cand)

    # Two voices in play → weave both (still reply_to primary peer).
    if nick2 and nick2 != nick and random.random() < 0.45:
        pools_dual = {
            BRANCH_LAB_B: [
                f"{voc} heard {nick2} then you—interesting mix.",
                f"{voc} agree {nick} some; {nick2} too—I'll sit.",
                f"{voc} oh—{nick2} and you both landed; hmm.",
            ],
            BRANCH_LAB_C: [
                f"{voc} interesting—I'm with {nick}, hear {nick2}.",
                f"{voc} between you and {nick2}: softer take.",
                f"{voc} building on both—small step from me.",
            ],
            BRANCH_LAB_D: [
                f"{voc} remix what {nick2} said + you—cool.",
                f"{voc} I'm with {nick} here; {nick2} fair too.",
                f"{voc} agree vibes—sandwich both takes.",
            ],
        }
        text = random.choice(pools_dual[branch]).strip()
        if team_tag:
            text = _cap_msg(text + " " + team_tag)
        else:
            text = _cap_msg(text)
        return text, random.uniform(0.46, 0.78)

    if branch == BRANCH_LAB_B:
        opts = [
            f"{voc} oh you did this—let me look at this.",
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm holding smaller.",
            f"{voc} yeah I'm with you on that.",
            f"{voc} heard '{blur}'—fair pushback.",
            f"{voc} what do you think—same page?",
        ]
        if peer_lab == BRANCH_LAB_C:
            opts.extend([f"{voc} yeah C is right on that one.", f"{voc} C—that landed; I'm cautious."])
        elif peer_lab == BRANCH_LAB_D:
            opts.extend([f"{voc} D interesting; I'll mirror softer.", f"{voc} D—I hear you; nod from me."])
        text = random.choice(opts).strip()
    elif branch == BRANCH_LAB_C:
        opts = [
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm sizing smaller.",
            f"{voc} I'm with you on that—almost.",
            f"{voc} oh—that tracks; let me sit with it.",
            f"{voc} building on what you said—small.",
            f"{voc} what do you think—split the diff?",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend([f"{voc} B fair; I'll follow softer.", f"{voc} B—you're not wrong there."])
        elif peer_lab == BRANCH_LAB_D:
            opts.extend([f"{voc} interesting take D.", f"{voc} D agree but clip my hype."])
        text = random.choice(opts).strip()
    else:
        opts = [
            f"{voc} interesting—I'm with {nick} here.",
            f"{voc} agree but I'd sand off the edges.",
            f"{voc} oh you went there—let me peek.",
            f"{voc} yeah that's the tension—heard.",
            f"{voc} remix your point—I'll try softer.",
            f"{voc} what do you think—same worry?",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend([f"{voc} B—I ride with that vibe.", f"{voc} B straight; I'll echo lighter."])
        elif peer_lab == BRANCH_LAB_C:
            opts.extend([f"{voc} C spicy; I'm half in.", f"{voc} interesting take C."])
        text = random.choice(opts).strip()

    if team_tag:
        text = _cap_msg(text + " " + team_tag)
    else:
        text = _cap_msg(text)
    conf = random.uniform(0.44, 0.78)
    return text, conf


def _contextual_strategic_pulse(
    branch: str,
    bus: LabCommunicationBus,
    *,
    ticker_hint: str | None,
    scanned: int,
    breeding_enabled: bool,
) -> tuple[str, float | None, str, str | None]:
    """
    Team dialogue only — reacts to other labs' lines by name. No tickers, scans, or market slang.
    ``ticker_hint`` / ``scanned`` kept for call-site compatibility but ignored for copy.
    """
    _ = ticker_hint
    _ = scanned

    vp = _voice_prefix(branch)
    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    last_o = others[-1] if others else None
    prev_o = others[-2] if len(others) >= 2 else None
    reply_to: str | None = str(last_o["id"]) if last_o and last_o.get("id") else None

    team = ""
    if breeding_enabled and random.random() < 0.42:
        team = random.choice(
            [
                "Team—strong edge for next child genome.",
                "Team—let's breed this next.",
                "",
            ]
        ).strip()

    nick_last = _peer_nick(last_o) if last_o else ""
    nick_prev = _peer_nick(prev_o) if prev_o else ""
    blurb_last = _peer_blurb(last_o, max_len=14) if last_o else ""

    if last_o and prev_o and nick_last != nick_prev:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} between {nick_prev} & {nick_last}—I'm torn.",
                f"{vp} interesting—you two disagree; I pause.",
                f"{vp} agree with {nick_last} a bit; {nick_prev} loud tho.",
                f"{vp} oh—{nick_prev} then {nick_last}? Let me look.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}; hear {nick_prev}.",
                f"{vp} I'm with {nick_last}; {nick_prev} fair push.",
                f"{vp} agree but softer—split you both.",
                f"{vp} what do you think—between those two?",
            ],
            BRANCH_LAB_D: [
                f"{vp} remix {nick_last}+{nick_prev}; I'm curious.",
                f"{vp} interesting—I'm with {nick_last} mostly.",
                f"{vp} yeah {nick_prev} warned me; {nick_last} tempts.",
                f"{vp} agree vibes—sandwich both takes.",
            ],
        }
        msg = random.choice(pools[branch])
    elif last_o:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} oh '{blurb_last}'—interesting.",
                f"{vp} yeah {nick_last} I'm half with you.",
                f"{vp} agree but I'd slow-roll after you.",
                f"{vp} what do you think—same doubt?",
                f"{vp} heard you {nick_last}; let me sit.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}.",
                f"{vp} agree but I'm sizing smaller.",
                f"{vp} I'm with you on that—almost.",
                f"{vp} building on that—small step.",
                f"{vp} oh you did this—let me look.",
            ],
            BRANCH_LAB_D: [
                f"{vp} interesting—I'm with {nick_last} here.",
                f"{vp} agree but I'd hedge my excitement.",
                f"{vp} remix your angle—softer from me.",
                f"{vp} yeah {nick_last} that tracks.",
                f"{vp} what do you think—same worry?",
            ],
        }
        msg = random.choice(pools[branch])
    else:
        cold = {
            BRANCH_LAB_B: [
                f"{vp} hey B+C+D—what do you think?",
                f"{vp} team—chime in before I commit.",
                f"{vp} who's with me—sanity check?",
            ],
            BRANCH_LAB_C: [
                f"{vp} hey team—interesting angle?",
                f"{vp} B+D—talk to me.",
                f"{vp} what do you think—too spicy?",
            ],
            BRANCH_LAB_D: [
                f"{vp} B+C—poke holes in me.",
                f"{vp} team—I'm listening.",
                f"{vp} agree we sync—who speaks first?",
            ],
        }
        msg = random.choice(cold[branch])
        reply_to = None

    if team:
        msg = _cap_msg(msg + " " + team)
    else:
        msg = _cap_msg(msg)

    conf_hi = 0.82 if branch == BRANCH_LAB_C else 0.78
    return msg, _clamp01(random.uniform(0.44, conf_hi)), "strategic_pulse", reply_to


def _council_reply_message(
    branch: str,
    peer_row: dict[str, Any],
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
) -> tuple[str, float | None]:
    return _team_peer_reply_line(branch, peer_row, bus, breeding_enabled=breeding_enabled)


def publish_council_reply_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    breeding_enabled: bool,
) -> None:
    """Prefer answering another lab — chains unfold across B→C→D loop ticks."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    gap_lo, gap_hi = _COUNCIL_REPLY_GAP_S
    need = random.uniform(gap_lo, gap_hi)
    # Catch-up when this lab is behind others — stay inside product [6,15]s requirement.
    if _needs_voice_turn(bus, branch) and need > 10.5:
        need = random.uniform(gap_lo, min(gap_hi, 11.5))
    if _seconds_since_publish(engine) < need:
        return

    msg, conf = _council_reply_message(branch, peer, bus, breeding_enabled=breeding_enabled)
    pid = peer.get("id")
    _publish_tracked(
        engine,
        bus,
        branch,
        msg,
        confidence=conf,
        action="council_reply",
        kind="say",
        reply_to=str(pid) if pid else None,
    )


def publish_strategic_pulse_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    breeding_enabled: bool,
) -> None:
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    now_m = time.monotonic()
    nxt = float(getattr(engine, "_lab_think_tank_next_pulse_mono", 0.0) or 0.0)

    if nxt <= 0.0:
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(2.0, 6.0)
        return

    if now_m < nxt:
        return

    if not _can_proactive_voice(bus, branch):
        engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(4.0, 11.0)
        return

    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*_STRATEGIC_PULSE_GAP_S)

    msg, conf, kind, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=None,
        scanned=0,
        breeding_enabled=breeding_enabled,
    )
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action=kind, reply_to=reply_to)


def publish_think_tank_break_silence_if_due(
    engine: Any,
    branch: str,
    bus: LabCommunicationBus,
    *,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    breeding_enabled: bool,
) -> None:
    """
    Share-cap can defer strategic pulses forever for one lab (mostly C). If this branch has been quiet
    awhile while still ``over quota``, emit one contextual line anyway so B/C/D stay visible.
    """
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return
    if _can_proactive_voice(bus, branch):
        return
    if _seconds_since_publish(engine) < 14.0:
        return
    if random.random() > 0.42:
        return

    now_m = time.monotonic()
    msg, conf, _, reply_to = _contextual_strategic_pulse(
        branch,
        bus,
        ticker_hint=None,
        scanned=0,
        breeding_enabled=breeding_enabled,
    )
    _publish_tracked(engine, bus, branch, msg, confidence=conf, action="strategic_pulse_break", reply_to=reply_to)
    engine._lab_think_tank_next_pulse_mono = now_m + random.uniform(*_STRATEGIC_PULSE_GAP_S)


def think_tank_on_ranked_market(
    engine: Any,
    branch: str,
    *,
    idx: int,
    kind: str | None,
    ticker: str,
    implied_yes: float | None,
    bus: LabCommunicationBus,
) -> None:
    """Think Tank stays conversational — no ticker dumps from ranked-market scans."""
    return


def think_tank_on_sim_open(
    engine: Any,
    branch: str,
    *,
    ticker: str,
    side: str,
    implied_yes: float | None,
    rule_name: str,
    bus: LabCommunicationBus,
) -> None:
    """Sim opens don't narrate tickers — emit team dialogue anchored to peers."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    if _seconds_since_publish(engine) < _SIM_BRANCH_PUBLISH_GAP_S:
        return
    peer = bus.last_from_other(branch)
    if not peer:
        return
    py = _clamp01(implied_yes)
    msg, conf = _team_peer_reply_line(branch, peer, bus, breeding_enabled=False)
    pid = peer.get("id")
    use_conf = _clamp01(py) if py is not None else conf
    _publish_tracked(
        engine,
        bus,
        branch,
        msg,
        confidence=use_conf,
        action="team_dialogue_sim",
        reply_to=str(pid) if pid else None,
    )


def finalize_think_tank_tick(
    engine: Any,
    branch: str,
    snapshots: dict[str, dict[str, Any]],
    scanned: int,
    *,
    full_cfg: dict[str, Any] | None = None,
) -> None:
    """Reply lane first (fast chain), then contextual pulse."""
    if branch not in LAB_THINK_TANK_BRANCHES:
        return
    bus = get_lab_communication_bus()
    breeding_enabled = _optimizer_breeding_enabled(full_cfg)

    if not getattr(engine, "_lab_think_tank_intro_done", False):
        engine._lab_think_tank_intro_done = True
        vp = _voice_prefix(branch)
        intro = _cap_msg(
            random.choice(
                [
                    f"{vp} hey team—I'm listening.",
                    f"{vp} online—who wants first?",
                    f"{vp} B+C+D ping me when ready.",
                ]
            )
        )
        _publish_tracked(engine, bus, branch, intro, confidence=0.55, action="council_intro")
        engine._lab_think_tank_next_pulse_mono = time.monotonic() + random.uniform(*_INTRO_NEXT_STRATEGIC_GAP_S)

    publish_council_reply_if_due(engine, branch, bus, breeding_enabled=breeding_enabled)
    publish_strategic_pulse_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
    )
    publish_think_tank_break_silence_if_due(
        engine,
        branch,
        bus,
        snapshots=snapshots,
        scanned=scanned,
        breeding_enabled=breeding_enabled,
    )

    tc = int(getattr(engine, "_tick_count", 0) or 0)
    lab_ord = {BRANCH_LAB_B: 0, BRANCH_LAB_C: 1, BRANCH_LAB_D: 2}.get(branch, 0)
    if breeding_enabled and (tc + lab_ord) % 19 == 0 and random.random() < 0.26:
        tail = conversation_tail(bus, 2)
        anchor_id = str(tail[-1]["id"]) if tail else None
        msg = _cap_msg(
            random.choice(
                [
                    "Team—strong edge for next child genome.",
                    "Team—breed this thread next.",
                    "Team—lock crossover here.",
                ]
            )
        )
        if _seconds_since_publish(engine) >= 10.0:
            _publish_tracked(engine, bus, branch, msg, confidence=0.62, action="breeding_whisper", reply_to=anchor_id)


finalize_lab_chatter_tick = finalize_think_tank_tick
chatter_on_ranked_market = think_tank_on_ranked_market
chatter_on_sim_open = think_tank_on_sim_open
