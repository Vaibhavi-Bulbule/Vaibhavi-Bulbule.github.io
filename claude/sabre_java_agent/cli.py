"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sabre_java_agent.hlasm.macros import EXTRA_PATH_ENV, PROJECT_ROOT_ENV


def _load_dotenv_if_available() -> None:
    # Optional — debug paths like --macros-print should still work in a
    # bare environment where python-dotenv hasn't been installed yet.
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sabre-java-agent",
        description="Generate Java from HLASM source or user stories.",
    )
    p.add_argument("--asm", type=Path, help="Path to an HLASM (.asm/.mac) source file.")
    p.add_argument("--story", type=Path, help="Path to a user story (markdown/text).")
    p.add_argument(
        "--prompt",
        type=str,
        help="Inline input. Combine with --asm/--story to add guidance.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("generated"),
        help="Output directory for generated Java sources (default: ./generated).",
    )
    p.add_argument(
        "--macros",
        type=Path,
        help=(
            "Path to an extra macro catalog (YAML) to layer on top of the "
            "bundled catalog and any <project>/.sabre/macros.yml. CLI entries "
            "win on name collision. Useful for testing a candidate macro list "
            "before promoting it."
        ),
    )
    p.add_argument(
        "--macros-print",
        action="store_true",
        help=(
            "Resolve all three catalog layers (bundled, project-local, "
            "--macros) and print them with per-entry provenance, then exit. "
            "Combine with --macros to preview an override; runs without an "
            "ANTHROPIC_API_KEY."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="With --macros-print, emit JSON instead of the pretty table.",
    )
    return p


def _print_catalog(as_json: bool) -> int:
    import json as _json

    from sabre_java_agent.hlasm.macros import dump_with_provenance

    info = dump_with_provenance()

    if as_json:
        print(_json.dumps(info, indent=2))
        return 0

    print("Sources:")
    for layer in ("bundled", "project", "cli"):
        path = info["sources"][layer]
        marker = "[+]" if path else "[ ]"
        print(f"  {marker} {layer:8s} {path or '(not present)'}")
    print()

    c = info["counts"]
    print(
        f"Resolved {c['total_resolved']} entries  "
        f"(bundled={c['bundled']}  project={c['project']}  cli={c['cli']}  "
        f"shadowed={c['shadowed']})"
    )
    print()

    if not info["entries"]:
        print("(catalog is empty — is PyYAML installed?)")
        return 0

    name_w = max(len(e["name"]) for e in info["entries"])
    cat_w = max(len(e["category"]) for e in info["entries"])
    src_w = 8

    header = f"{'NAME':<{name_w}}  {'SRC':<{src_w}}  {'CAT':<{cat_w}}  JAVA MAPPING"
    print(header)
    print("-" * len(header))
    for e in info["entries"]:
        flag = "*" if e["shadowed_in"] else " "
        mapping = e["java_mapping"]
        if len(mapping) > 70:
            mapping = mapping[:67] + "..."
        print(
            f"{e['name']:<{name_w}}  {e['source']:<{src_w}}  "
            f"{e['category']:<{cat_w}}  {flag} {mapping}"
        )
    if c["shadowed"]:
        print()
        print(f"* shadows {c['shadowed']} lower-priority entr"
              f"{'y' if c['shadowed'] == 1 else 'ies'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows default stdout/stderr is cp1252, which crashes on the
    # non-ASCII chars the model frequently emits (arrows, em dashes,
    # box-drawing). Reconfigure to UTF-8 with 'replace' so we never
    # crash on a weird char — at worst we drop a glyph.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    _load_dotenv_if_available()
    args = _build_parser().parse_args(argv)

    # Anchor "project-local" lookups to the user's invocation cwd, not to
    # `out_dir` (the agent runs with cwd=out_dir). Anything that resolves
    # `<project>/.sabre/macros.yml` consults this env var.
    os.environ[PROJECT_ROOT_ENV] = str(Path.cwd().resolve())

    if args.macros:
        macros_path = args.macros.resolve()
        if not macros_path.exists():
            print(f"Macro catalog not found: {macros_path}", file=sys.stderr)
            return 2
        # Plumbed via env var so the in-process MCP tools and the parser
        # both pick it up without threading a parameter through every call.
        os.environ[EXTRA_PATH_ENV] = str(macros_path)

    # Debug-only path: print resolved catalog and exit. No API key needed.
    if args.macros_print:
        return _print_catalog(as_json=args.json)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Add it to .env or your shell.", file=sys.stderr)
        return 2

    if not (args.asm or args.story or args.prompt):
        print(
            "Provide at least one of --asm, --story, --prompt, or --macros-print.",
            file=sys.stderr,
        )
        return 2

    # Imported lazily — only needed when actually launching the agent. Keeps
    # debug paths (--macros-print) usable without the SDK installed.
    from sabre_java_agent.agent import run
    from sabre_java_agent.prompts import asm_prompt, inline_prompt, story_prompt

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.asm:
        if not args.asm.exists():
            print(f"ASM file not found: {args.asm}", file=sys.stderr)
            return 2
        prompt = asm_prompt(str(args.asm.resolve()), str(out_dir), args.prompt)
    elif args.story:
        if not args.story.exists():
            print(f"Story file not found: {args.story}", file=sys.stderr)
            return 2
        prompt = story_prompt(str(args.story.resolve()), str(out_dir), args.prompt)
    else:
        prompt = inline_prompt(args.prompt or "", str(out_dir))

    return run(prompt, out_dir)


if __name__ == "__main__":
    sys.exit(main())
