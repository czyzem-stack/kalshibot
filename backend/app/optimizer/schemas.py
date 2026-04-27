"""Pydantic schemas for Claude optimizer JSON responses."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RuleDeltaOp(BaseModel):
    """Single rule mutation from Claude."""

    op: Literal["add", "patch", "modify", "delete"] = Field(description="add | patch | modify | delete")
    rule: dict[str, Any] | None = Field(
        default=None,
        description="Full rule object for add; patch fields for patch; ignored for delete",
    )
    rule_name: str | None = Field(
        default=None,
        description="Target rule name for patch/delete (must match existing rule name)",
    )


class BetRecommendation(BaseModel):
    target: str = ""
    field: str = ""
    current: Any = None
    suggested: Any = None
    reason: str = ""
    confidence: str = "medium"


class LabParameterPatch(BaseModel):
    """Optional scalar overrides for Lab A (validated separately)."""

    balance_fraction_per_window: float | None = None
    window_minutes: int | None = None


class ClaudeOptimizerResponse(BaseModel):
    """
    Expanded Claude output: reasoning, optional rule deltas, bet recommendations, trend notes.
    JSON-only; validated after parse.
    """

    reasoning: str = ""
    summary: str = ""
    rule_operations: list[RuleDeltaOp] = Field(default_factory=list)
    lab_parameter_patch: LabParameterPatch | None = None
    recommendations: list[BetRecommendation] = Field(default_factory=list)
    trend_notes: list[str] = Field(default_factory=list)
    propose_new_rule_family: bool = False
    held_out_simulation: dict[str, Any] = Field(default_factory=dict)

    @field_validator("recommendations", mode="before")
    @classmethod
    def _coerce_recs(cls, v: Any) -> Any:
        if v is None:
            return []
        return v

    @field_validator("rule_operations", mode="before")
    @classmethod
    def _coerce_ops(cls, v: Any) -> Any:
        if v is None:
            return []
        return v


def parse_claude_optimizer_json(raw: str) -> tuple[ClaudeOptimizerResponse | None, dict[str, Any]]:
    """
    Parse model JSON text. On failure returns (None, {"parse_error": ...}).
    """
    raw = raw.strip()
    if raw.startswith("```"):
        end = raw.rfind("```")
        if end > 3:
            raw = raw[3:end].strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
        raw = raw.strip()
    if not raw:
        return None, {"parse_error": "empty"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, {"parse_error": str(e), "snippet": raw[:400]}
    if not isinstance(data, dict):
        return None, {"parse_error": "root must be object"}
    try:
        return ClaudeOptimizerResponse.model_validate(data), data
    except Exception as e:
        return None, {"parse_error": str(e), "data": data}
