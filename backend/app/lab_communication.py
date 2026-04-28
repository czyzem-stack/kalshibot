"""
Breeding Council / Lab Think Tank — Labs B, C, D publish short lines with explicit conversational threading.

Rolling **last 6** bus lines drive prompts; every line reacts to **other labs** by name; optional ``reply_to`` UUID ties replies.
**~62** chars; **anti-repeat** vs last 8 lines; **B/D boost** + **C damp** when one lab dominates; council **6–15s**; no ticker ranked hook.

Not persisted. Observational only. ``GET /labs/chat`` unchanged contract (+ optional ``reply_to`` field).
"""

from __future__ import annotations

import random
import time
import uuid
from collections import Counter, deque
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
_ANTIREPEAT_LOOKBACK = 8  # skip lines too similar to these recent bodies


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


def _recent_message_norms(bus: LabCommunicationBus, n: int = _ANTIREPEAT_LOOKBACK) -> list[str]:
    """Lowercased message bodies from the last ``n`` rows (Think Tank anti-repeat)."""
    out: list[str] = []
    for r in list(bus._dq)[-n:]:
        m = str(r.get("message") or "").strip().lower()
        if m:
            out.append(m)
    return out


def _overlap_word_score(a: str, b: str) -> float:
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / float(min(len(wa), len(wb)))


def _too_close_to_recent(candidate: str, recent: list[str]) -> bool:
    cand = candidate.strip().lower()
    if not cand:
        return True
    for prev in recent:
        if cand == prev:
            return True
        n = min(len(cand), len(prev), 28)
        if n >= 18 and cand[:n] == prev[:n]:
            return True
        if _overlap_word_score(cand, prev) >= 0.55:
            return True
    return False


def _pick_varied(candidates: list[str], bus: LabCommunicationBus) -> str:
    """Pick a line that doesn't echo recent bus text (phrase / word-overlap guard)."""
    recent = _recent_message_norms(bus, _ANTIREPEAT_LOOKBACK)
    opts = list(candidates)
    random.shuffle(opts)
    for text in opts:
        if not _too_close_to_recent(text, recent):
            return text
    return opts[0] if opts else ""


def _c_overrepresented(bus: LabCommunicationBus, window: int = 8) -> bool:
    """True when C has clearly owned the last window — dampen C proactive monopoly."""
    labs = [r.get("lab") for r in list(bus._dq)[-window:] if r.get("lab") in LAB_THINK_TANK_BRANCHES]
    if len(labs) < 5:
        return False
    c = labs.count(BRANCH_LAB_C)
    b = labs.count(BRANCH_LAB_B)
    d = labs.count(BRANCH_LAB_D)
    return c >= 4 and c >= b + 2 and c >= d + 2


def _recent_lab_share(bus: LabCommunicationBus, lab: str, *, window: int = _RECENT_SHARE_WINDOW) -> float:
    rows = list(bus._dq)[-window:]
    if not rows:
        return 0.0
    hits = sum(1 for r in rows if r.get("lab") == lab)
    return hits / float(len(rows))


def _needs_voice_turn(bus: LabCommunicationBus, branch: str) -> bool:
    """Prefer labs absent, behind, or squeezed out by a hot lab — breaks C monopoly."""
    rows = list(bus._dq)[-10:]
    labs_seq = [str(r.get("lab") or "") for r in rows if str(r.get("lab") or "") in LAB_THINK_TANK_BRANCHES]
    if branch not in LAB_THINK_TANK_BRANCHES:
        return False
    if not labs_seq:
        return True

    tail8 = [lb for lb in labs_seq[-8:] if lb in LAB_THINK_TANK_BRANCHES]
    c_ct = tail8.count(BRANCH_LAB_C)
    b_ct = tail8.count(BRANCH_LAB_B)
    d_ct = tail8.count(BRANCH_LAB_D)

    # C ran the board — force B and D back in.
    if branch in (BRANCH_LAB_B, BRANCH_LAB_D) and c_ct >= 4 and (b_ct + d_ct) <= 3:
        return True
    # B or D vanished from the last five — pull them forward.
    last5 = [lb for lb in labs_seq[-5:] if lb in LAB_THINK_TANK_BRANCHES]
    if branch == BRANCH_LAB_B and BRANCH_LAB_B not in last5:
        return True
    if branch == BRANCH_LAB_D and BRANCH_LAB_D not in last5:
        return True

    # C does not need a "priority bump" when already dominant.
    if branch == BRANCH_LAB_C and c_ct >= 5:
        return False

    seen = {lb for lb in labs_seq[-6:]}
    if len(seen) < 3 and branch not in seen:
        return True
    if branch not in labs_seq[-4:]:
        return True
    counts = Counter(lb for lb in labs_seq if lb in (BRANCH_LAB_B, BRANCH_LAB_C, BRANCH_LAB_D))
    mx = max(counts.values()) if counts else 0
    return counts.get(branch, 0) < mx


def _can_proactive_voice(bus: LabCommunicationBus, lab: str) -> bool:
    # Early thread: allow everyone to speak so the UI isn’t an empty box waiting on share math.
    if len(bus._dq) < _BOOTSTRAP_BUS_LINES:
        return True
    if _needs_voice_turn(bus, lab):
        return True
    if lab == BRANCH_LAB_C and _c_overrepresented(bus):
        return False
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
    """Varied natural reply — always anchored to peer(s); anti-repeat vs recent bus lines."""
    voc = _voice_prefix(branch)
    nick = _peer_nick(peer_row)
    peer_lab = str(peer_row.get("lab") or "")
    blur = _peer_blurb(peer_row, max_len=14)

    team_tag = ""
    if breeding_enabled and random.random() < 0.34:
        team_tag = random.choice(
            [
                " Team—strong edge here.",
                " Team—breed next.",
                " Building on that for next child.",
                "",
            ]
        ).strip()

    others = thread_other_lines(bus, branch, _CONV_MEMORY)
    nick2 = ""
    if len(others) >= 2:
        cand = others[-2]
        if cand.get("id") != peer_row.get("id"):
            nick2 = _peer_nick(cand)

    def _finish(text: str) -> tuple[str, float | None]:
        t = text.strip()
        if team_tag:
            t = _cap_msg(t + " " + team_tag)
        else:
            t = _cap_msg(t)
        return t, random.uniform(0.44, 0.78)

    # Two other voices in tail — weave both (reply_to stays primary peer).
    if nick2 and nick2 != nick and random.random() < 0.48:
        pools_dual: dict[str, list[str]] = {
            BRANCH_LAB_B: [
                f"{voc} heard {nick2} then you—interesting mix.",
                f"{voc} agree {nick} some; {nick2} too—I'll sit.",
                f"{voc} oh—{nick2} and you both landed; hmm.",
                f"{voc} between {nick2} & you—I'm torn.",
                f"{voc} yeah {nick2} loud; you calmer—I'll lean you.",
                f"{voc} what do you think—split those two?",
                f"{voc} building on both—small nudge from me.",
                f"{voc} interesting—I'm half with {nick2}, half you.",
            ],
            BRANCH_LAB_C: [
                f"{voc} interesting—I'm with {nick}, hear {nick2}.",
                f"{voc} between you and {nick2}: softer take.",
                f"{voc} building on both—small step from me.",
                f"{voc} agree {nick} vibe; {nick2} also fair.",
                f"{voc} oh you two—let me sit with that.",
                f"{voc} what do you think team—too spicy?",
                f"{voc} yeah {nick2} warned me; you tempt me.",
                f"{voc} interesting mix—I'll clip size.",
            ],
            BRANCH_LAB_D: [
                f"{voc} remix what {nick2} said + you—cool.",
                f"{voc} I'm with {nick} here; {nick2} fair too.",
                f"{voc} agree vibes—sandwich both takes.",
                f"{voc} heard {nick2} then you—layered take.",
                f"{voc} interesting—I'll soften the edges.",
                f"{voc} what do you think—same tension?",
                f"{voc} building on both—quiet nod from me.",
                f"{voc} yeah {nick2} + you—I'll mirror lighter.",
            ],
        }
        raw = _pick_varied(pools_dual[branch], bus)
        return _finish(raw)

    if branch == BRANCH_LAB_B:
        opts = [
            f"{voc} oh you did this—let me look.",
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm holding smaller.",
            f"{voc} yeah I'm with you on that.",
            f"{voc} heard '{blur}'—fair pushback.",
            f"{voc} what do you think—same page?",
            f"{voc} too spicy for me—thanks {nick}.",
            f"{voc} slow down—I'm chewing on that.",
            f"{voc} nod—I'll echo lighter than you.",
            f"{voc} hmm—half agree, half scared.",
            f"{voc} you went bold; I'm parking.",
            f"{voc} fair—I'll sit one beat out.",
            f"{voc} interesting—need a second read.",
            f"{voc} agree vibes—just not my size.",
            f"{voc} oh that landed—I'm cautious.",
            f"{voc} what do you think team—chime in?",
        ]
        if peer_lab == BRANCH_LAB_C:
            opts.extend(
                [
                    f"{voc} yeah C is right on that one.",
                    f"{voc} C—that hit; I'm still small.",
                    f"{voc} C spicy; I'll fade my own hype.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"{voc} D interesting; I'll mirror softer.",
                    f"{voc} D—I hear you; nod from me.",
                    f"{voc} D wild; I'll leash my side.",
                ]
            )
        raw = _pick_varied(opts, bus)
        return _finish(raw)

    if branch == BRANCH_LAB_C:
        opts = [
            f"{voc} interesting take {nick}.",
            f"{voc} agree but I'm sizing smaller.",
            f"{voc} I'm with you on that—almost.",
            f"{voc} oh—that tracks; let me sit with it.",
            f"{voc} building on what you said—small.",
            f"{voc} what do you think—split the diff?",
            f"{voc} too spicy for me—clipping.",
            f"{voc} heard '{blur}'—interesting angle.",
            f"{voc} yeah—soft yes from me.",
            f"{voc} pause—need team read too.",
            f"{voc} agree but I'd sand the edge off.",
            f"{voc} oh you did this—let me look.",
            f"{voc} remix your frame—small follow.",
            f"{voc} fair push—I'll under-size.",
            f"{voc} interesting—who else weighs in?",
            f"{voc} what do you think team?",
            f"{voc} building on that—quiet step.",
            f"{voc} agree vibe—cap my own rush.",
        ]
        if peer_lab == BRANCH_LAB_B:
            opts.extend(
                [
                    f"{voc} B fair; I'll follow softer.",
                    f"{voc} B—you're not wrong there.",
                    f"{voc} B tight; I'll match calmer.",
                ]
            )
        elif peer_lab == BRANCH_LAB_D:
            opts.extend(
                [
                    f"{voc} interesting take D.",
                    f"{voc} D agree but clip my hype.",
                    f"{voc} D—I ride half your energy.",
                ]
            )
        raw = _pick_varied(opts, bus)
        return _finish(raw)

    opts = [
        f"{voc} interesting—I'm with {nick} here.",
        f"{voc} agree but I'd sand off the edges.",
        f"{voc} oh you went there—let me peek.",
        f"{voc} yeah that's the tension—heard.",
        f"{voc} remix your point—I'll try softer.",
        f"{voc} what do you think—same worry?",
        f"{voc} too spicy for me—passing light.",
        f"{voc} building on that—small nod.",
        f"{voc} heard '{blur}'—interesting.",
        f"{voc} slow roll—I'll mirror light.",
        f"{voc} agree but I'm not full send.",
        f"{voc} oh you did this—let me look.",
        f"{voc} team—need a second opinion.",
        f"{voc} fair—I'll echo quieter.",
        f"{voc} interesting take—half in.",
        f"{voc} what do you think—push or park?",
    ]
    if peer_lab == BRANCH_LAB_B:
        opts.extend(
            [
                f"{voc} B—I ride with that vibe.",
                f"{voc} B straight; I'll echo lighter.",
                f"{voc} yeah B is right on that one.",
            ]
        )
    elif peer_lab == BRANCH_LAB_C:
        opts.extend(
            [
                f"{voc} C spicy; I'm half in.",
                f"{voc} interesting take C.",
                f"{voc} C—that tracks; I'll clip.",
            ]
        )
    raw = _pick_varied(opts, bus)
    return _finish(raw)


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
                "Team—strong edge here.",
                "Team—let's breed this next.",
                "",
            ]
        ).strip()

    nick_last = _peer_nick(last_o) if last_o else ""
    nick_prev = _peer_nick(prev_o) if prev_o else ""
    blurb_last = _peer_blurb(last_o, max_len=12) if last_o else ""

    if last_o and prev_o and nick_last != nick_prev:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} between {nick_prev} & {nick_last}—I'm torn.",
                f"{vp} interesting—you two disagree; I pause.",
                f"{vp} agree with {nick_last} a bit; {nick_prev} loud tho.",
                f"{vp} oh—{nick_prev} then {nick_last}? Let me look.",
                f"{vp} what do you think team—pick a lane?",
                f"{vp} heard both—I'm parking one beat.",
                f"{vp} yeah {nick_prev} scared me; {nick_last} tempts.",
                f"{vp} building on both—quiet take.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}; hear {nick_prev}.",
                f"{vp} I'm with {nick_last}; {nick_prev} fair push.",
                f"{vp} agree but softer—split you both.",
                f"{vp} what do you think—between those two?",
                f"{vp} oh—layered; let me sit.",
                f"{vp} too spicy if I merge both—clipping.",
                f"{vp} yeah {nick_prev} + {nick_last}—I'm small.",
                f"{vp} building on that thread—small yes.",
            ],
            BRANCH_LAB_D: [
                f"{vp} remix {nick_last}+{nick_prev}; I'm curious.",
                f"{vp} interesting—I'm with {nick_last} mostly.",
                f"{vp} yeah {nick_prev} warned me; {nick_last} tempts.",
                f"{vp} agree vibes—sandwich both takes.",
                f"{vp} what do you think—third way?",
                f"{vp} heard both—I'll soften mine.",
                f"{vp} oh you two—fun tension.",
                f"{vp} building on both—light echo.",
            ],
        }
        msg = _pick_varied(pools[branch], bus)
    elif last_o:
        pools = {
            BRANCH_LAB_B: [
                f"{vp} oh '{blurb_last}'—interesting.",
                f"{vp} yeah {nick_last} I'm half with you.",
                f"{vp} agree but I'd slow-roll after you.",
                f"{vp} what do you think—same doubt?",
                f"{vp} heard you {nick_last}; let me sit.",
                f"{vp} too spicy for me—thanks.",
                f"{vp} interesting take {nick_last}.",
                f"{vp} building on that—small nod.",
                f"{vp} oh you did this—let me look.",
                f"{vp} agree but I'm not full send.",
            ],
            BRANCH_LAB_C: [
                f"{vp} interesting take {nick_last}.",
                f"{vp} agree but I'm sizing smaller.",
                f"{vp} I'm with you on that—almost.",
                f"{vp} building on that—small step.",
                f"{vp} oh you did this—let me look.",
                f"{vp} what do you think team?",
                f"{vp} yeah {nick_last}—fair push.",
                f"{vp} too spicy—clipping my side.",
                f"{vp} heard '{blurb_last}'—interesting.",
                f"{vp} agree vibes—under-size me.",
            ],
            BRANCH_LAB_D: [
                f"{vp} interesting—I'm with {nick_last} here.",
                f"{vp} agree but I'd hedge my excitement.",
                f"{vp} remix your angle—softer from me.",
                f"{vp} yeah {nick_last} that tracks.",
                f"{vp} what do you think—same worry?",
                f"{vp} building on that—quiet follow.",
                f"{vp} oh '{blurb_last}'—noted.",
                f"{vp} too spicy—I'll mirror light.",
                f"{vp} agree but sand the edge.",
                f"{vp} interesting take {nick_last}.",
            ],
        }
        msg = _pick_varied(pools[branch], bus)
    else:
        cold = {
            BRANCH_LAB_B: [
                f"{vp} hey B+C+D—what do you think?",
                f"{vp} team—chime in before I commit.",
                f"{vp} who's with me—sanity check?",
                f"{vp} B+C+D—ping me cold.",
                f"{vp} what do you think—too loud?",
                f"{vp} need reads before I lean.",
            ],
            BRANCH_LAB_C: [
                f"{vp} hey team—interesting angle?",
                f"{vp} B+D—talk to me.",
                f"{vp} what do you think—too spicy?",
                f"{vp} team—who's first?",
                f"{vp} B+D—sanity check me.",
                f"{vp} what do you think team?",
            ],
            BRANCH_LAB_D: [
                f"{vp} B+C—poke holes in me.",
                f"{vp} team—I'm listening.",
                f"{vp} agree we sync—who speaks first?",
                f"{vp} B+C—what do you think?",
                f"{vp} team—need your brakes.",
                f"{vp} hey—chime before I go.",
            ],
        }
        msg = _pick_varied(cold[branch], bus)
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
