"""Agent runtime: thin wrapper around the Claude Agent SDK `query()` loop."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query

from sabre_java_agent.mcp_server import build_server
from sabre_java_agent.prompts import SYSTEM_PROMPT


ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "Bash",
    "mcp__hlasm__hlasm_parse",
    "mcp__hlasm__hlasm_macro_catalog",
    "mcp__hlasm__hlasm_macro_lookup",
    "mcp__hlasm__hlasm_macro_save",
]


async def _run(prompt: str, cwd: Path) -> int:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        allowed_tools=ALLOWED_TOOLS,
        cwd=str(cwd),
        permission_mode="acceptEdits",
        mcp_servers={"hlasm": build_server()},
    )

    last_text = ""
    result_code: int | None = None

    # Hold the generator explicitly so we can deterministically aclose it.
    # Returning early from inside `async for` leaves the SDK's internal
    # async generator partially-iterated; Python's GC-time aclose then
    # races with the SDK's still-active coroutines and prints a benign
    # but ugly "aclose(): asynchronous generator is already running" error.
    gen = query(prompt=prompt, options=options)
    try:
        async for message in gen:
            msg_type = type(message).__name__
            if msg_type == "AssistantMessage":
                for block in getattr(message, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        print(text)
                        last_text = text
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        print(f"[tool] {tool_name}")
            elif msg_type == "ResultMessage":
                err = getattr(message, "is_error", False)
                result_code = 1 if err else 0
                # Keep iterating so the generator finishes naturally.
            # Other message types (user/system echoes) are ignored.
    finally:
        with contextlib.suppress(Exception):
            await gen.aclose()

    if result_code is not None:
        return result_code
    return 0 if last_text else 1


def run(prompt: str, cwd: Path) -> int:
    return asyncio.run(_run(prompt, cwd))
