"""The interface the eval harness depends on. Nothing here knows about Anthropic."""

from typing import Literal, Protocol

from pydantic import BaseModel


class TicketResponse(BaseModel):
    """The agent's final structured answer for one ticket."""

    action: Literal["refund", "deny_refund", "escalate", "answer"]
    order_id: str | None = None
    reply: str


class ToolCall(BaseModel):
    name: str
    input: dict
    output: dict


class AgentResult(BaseModel):
    ticket: str
    trace_id: str | None = None  # look up with `rgate trace <id>`
    response: TicketResponse | None  # None when the model's final text wasn't valid JSON
    raw_output: str
    tool_calls: list[ToolCall] = []
    model: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


class Agent(Protocol):
    def run(self, ticket: str) -> AgentResult: ...
