"""Agent runtime: thin wrapper around the Claude Agent SDK `query()` loop."""

from __future__ import annotations

import asyncio
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
    async for message in query(prompt=prompt, options=options):
        # The SDK yields typed messages; we surface assistant text and tool
        # activity so the user can follow along. Anything unrecognized is
        # printed via repr so we never silently drop signal.
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
            # Final result envelope — SDK signals end of run here.
            err = getattr(message, "is_error", False)
            return 1 if err else 0
        else:
            # User/system messages echoed by the SDK; ignore unless debugging.
            pass

    # Loop ended without an explicit ResultMessage.
    return 0 if last_text else 1


def run(prompt: str, cwd: Path) -> int:
    return asyncio.run(_run(prompt, cwd))
