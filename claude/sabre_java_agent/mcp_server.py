"""In-process MCP server exposing the HLASM parser and macro catalog to
the agent.

Tools:

  - hlasm_parse(path):           structural parse of a .asm/.mac file
  - hlasm_macro_catalog():       list known TPF/ALCS macros and semantics
  - hlasm_macro_lookup(name):    single-macro lookup
  - hlasm_macro_save(...):       persist a new/updated macro to project catalog
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from sabre_java_agent.hlasm.macros import (
    MacroEntry,
    load_catalog,
    lookup,
    save_macro,
)
from sabre_java_agent.hlasm.parser import parse_file


def _text_response(payload: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


@tool(
    "hlasm_parse",
    "Parse an HLASM (.asm/.mac) file and return its structural outline: "
    "CSECTs, DSECTs, USING bindings, field layouts, branches, and TPF/ALCS "
    "macro calls tagged with semantics from the project's macro catalog. "
    "Call this BEFORE attempting to translate any HLASM source.",
    {"path": str},
)
async def hlasm_parse(args: dict) -> dict:
    path = Path(args["path"])
    if not path.exists():
        return _text_response({"error": f"file not found: {path}"})
    return _text_response(parse_file(path).to_dict())


@tool(
    "hlasm_macro_catalog",
    "Return the full catalog of TPF/ALCS macros known to this project, "
    "with their semantics and recommended Java mappings. Use this when "
    "you encounter unfamiliar macros or want a Java mapping hint.",
    {},
)
async def hlasm_macro_catalog(_: dict) -> dict:
    return _text_response([entry.to_dict() for entry in load_catalog().values()])


@tool(
    "hlasm_macro_lookup",
    "Look up one TPF/ALCS macro by name. Returns null if the macro is not "
    "in the catalog — in that case, ask the user instead of guessing, then "
    "persist the answer with hlasm_macro_save.",
    {"name": str},
)
async def hlasm_macro_lookup(args: dict) -> dict:
    entry = lookup(args["name"])
    return _text_response(entry.to_dict() if entry else None)


@tool(
    "hlasm_macro_save",
    "Persist a new TPF/ALCS macro entry to the project-local catalog "
    "(default: <project>/.sabre/macros.yml). Use this AFTER asking the user "
    "for the macro's semantics — never invent semantics yourself. "
    "Pass `overwrite=true` to replace an existing entry of the same name. "
    "Pass `target` (string) to write somewhere other than the project-local "
    "catalog; leave empty for the default. Refuses to write to the bundled "
    "package catalog.",
    {
        "name": str,
        "category": str,
        "semantics": str,
        "java_mapping": str,
        "target": str,
        "overwrite": bool,
    },
)
async def hlasm_macro_save(args: dict) -> dict:
    name = (args.get("name") or "").strip()
    category = (args.get("category") or "").strip()
    semantics = (args.get("semantics") or "").strip()
    java_mapping = (args.get("java_mapping") or "").strip()
    target_str = (args.get("target") or "").strip()
    overwrite = bool(args.get("overwrite", False))

    if not name:
        return _text_response({"error": "name is required"})
    if not category:
        return _text_response({"error": "category is required"})
    if not semantics:
        return _text_response({"error": "semantics is required"})
    if not java_mapping:
        return _text_response({"error": "java_mapping is required"})

    entry = MacroEntry(
        name=name.upper(),
        category=category,
        semantics=semantics,
        java_mapping=java_mapping,
    )
    target = Path(target_str) if target_str else None

    try:
        result = save_macro(entry, target=target, overwrite=overwrite)
    except (ValueError, RuntimeError) as e:
        return _text_response({"error": str(e)})
    return _text_response(result)


def build_server():
    return create_sdk_mcp_server(
        name="hlasm",
        version="0.2.0",
        tools=[hlasm_parse, hlasm_macro_catalog, hlasm_macro_lookup, hlasm_macro_save],
    )
