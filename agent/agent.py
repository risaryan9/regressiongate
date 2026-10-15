"""Support-ticket agent: a plain tool-use loop over the Anthropic Messages API."""

import json

import anthropic
from pydantic import ValidationError

from agent.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from agent.protocol import AgentResult, TicketResponse, ToolCall
from agent.tools import TOOL_FUNCS, TOOL_SCHEMAS

DEFAULT_MODEL = "claude-haiku-5-5"


class SupportAgent:
    def __init__(self, model: str = DEFAULT_MODEL, max_turns: int = 6):
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        self.model = model
        self.max_turns = max_turns

    def run(self, ticket: str) -> AgentResult:
        messages: list[dict] = [{"role": "user", "content": ticket}]
        tool_calls: list[ToolCall] = []
        tokens_in = tokens_out = 0
        text = ""

        for _ in range(self.max_turns):
            resp = self.client.messages.create(
                model=self.model,
                # Haiku 5.5 thinks by default; leave room so the final JSON isn't truncated.
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            tokens_in += resp.usage.input_tokens
            tokens_out += resp.usage.output_tokens
            messages.append({"role": "assistant", "content": resp.content})
            text = "".join(b.text for b in resp.content if b.type == "text")

            if resp.stop_reason != "tool_use":
                break

            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                output = self._call_tool(block.name, block.input)
                tool_calls.append(ToolCall(name=block.name, input=block.input, output=output))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output)})
            messages.append({"role": "user", "content": results})
        else:
            return self._result(ticket, None, text, tool_calls, tokens_in, tokens_out, "max_turns exceeded")

        response, error = self._parse(text)
        return self._result(ticket, response, text, tool_calls, tokens_in, tokens_out, error)

    @staticmethod
    def _call_tool(name: str, args: dict) -> dict:
        func = TOOL_FUNCS.get(name)
        if func is None:
            return {"error": f"unknown tool {name}"}
        try:
            return func(**args)
        except TypeError as e:  # model sent bad arguments; report back instead of crashing
            return {"error": str(e)}

    @staticmethod
    def _parse(text: str) -> tuple[TicketResponse | None, str | None]:
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return TicketResponse.model_validate_json(cleaned), None
        except ValidationError as e:
            return None, f"invalid JSON output: {e.errors()[0]['msg']}"

    def _result(self, ticket, response, text, tool_calls, tokens_in, tokens_out, error) -> AgentResult:
        return AgentResult(
            ticket=ticket,
            response=response,
            raw_output=text,
            tool_calls=tool_calls,
            model=self.model,
            prompt_version=PROMPT_VERSION,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=error,
        )


if __name__ == "__main__":
    import sys

    result = SupportAgent().run(" ".join(sys.argv[1:]) or "I want a refund for order A1001, it arrived broken.")
    print(result.model_dump_json(indent=2))
