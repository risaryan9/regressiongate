"""Pydantic models for dataset rows (cases) and the dataset manifest."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump when the Case shape changes (fields added, removed or renamed).
SCHEMA_VERSION = 1

Action = Literal["refund", "deny_refund", "escalate", "answer"]
ToolName = Literal["lookup_order", "check_refund_policy", "escalate"]


class Case(BaseModel):
    # Reject unknown keys so a typo like "alowed_actions" fails instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    ticket: str = Field(min_length=1)
    # More than one action is allowed where a reasonable agent could go either way.
    allowed_actions: list[Action] = Field(min_length=1)
    expected_order_id: str | None = None  # None means "don't check the order id"
    must_call: list[ToolName] = []
    must_not_call: list[ToolName] = []
    reply_criteria: str = Field(min_length=1)  # what the LLM judge looks for in the reply
    tags: list[str] = []

    @model_validator(mode="after")
    def _tools_dont_conflict(self):
        overlap = set(self.must_call) & set(self.must_not_call)
        if overlap:
            raise ValueError(f"tools in both must_call and must_not_call: {sorted(overlap)}")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    version: int = Field(ge=1)  # bump on every change to cases.jsonl
    schema_version: int = Field(ge=1)  # bump when the Case shape changes
    row_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
