"""Structural HLASM parser.

This is not a full assembler. It tokenizes lines, joins continuations, and
extracts the structural facts a translator needs:

  - CSECT / DSECT boundaries and the labels each contains
  - USING directives (DSECT-to-register bindings)
  - Field layouts inside DSECTs (DC / DS entries)
  - Branch targets inside CSECTs
  - Macro invocations with raw operand text and a semantic tag from the
    catalog (or `unknown` if the macro is not catalogued)

Run as a script for a quick sanity check:

    python -m sabre_java_agent.hlasm.parser examples\\sample_alcs.asm
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sabre_java_agent.hlasm.instructions import (
    BASE_INSTRUCTIONS,
    DIRECTIVES,
    ZERO_OPERAND_OPS,
)
from sabre_java_agent.hlasm.macros import lookup as lookup_macro


# HLASM source lines: cols 1-71 source, 72 continuation, 73-80 sequence.
# We accept free-form input but honor the column-72 continuation marker if
# present.
_SRC_END = 71
_CONT_COL = 71  # zero-based index for column 72


@dataclass
class Line:
    lineno: int
    label: str
    op: str
    operands: str
    comment: str
    raw: str


@dataclass
class Field:
    name: str
    type: str       # DC | DS
    layout: str     # raw operand, e.g. "CL8" or "PL5" or "0F"
    comment: str


@dataclass
class MacroCall:
    lineno: int
    name: str
    operands: str
    category: str
    semantics: str
    java_mapping: str
    known: bool


@dataclass
class Branch:
    lineno: int
    op: str
    target: str


@dataclass
class Section:
    name: str
    kind: str  # CSECT | DSECT | RSECT
    start_line: int
    labels: list[str] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    macro_calls: list[MacroCall] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)


@dataclass
class Using:
    lineno: int
    section: str
    register: str


@dataclass
class ParseResult:
    path: str
    sections: list[Section] = field(default_factory=list)
    usings: list[Using] = field(default_factory=list)
    unknown_macros: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sections": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "start_line": s.start_line,
                    "labels": s.labels,
                    "entry_points": s.entry_points,
                    "fields": [f.__dict__ for f in s.fields],
                    "macro_calls": [m.__dict__ for m in s.macro_calls],
                    "branches": [b.__dict__ for b in s.branches],
                }
                for s in self.sections
            ],
            "usings": [u.__dict__ for u in self.usings],
            "unknown_macros": sorted(set(self.unknown_macros)),
            "stats": self.stats,
        }


# Branch ops that take a target label as their operand.
_BRANCH_OPS = {
    "B", "BE", "BNE", "BH", "BNH", "BL", "BNL", "BZ", "BNZ", "BM", "BNM",
    "BP", "BNP", "BO", "BNO", "BCT", "BAS", "BAL", "J", "JE", "JNE", "JH",
    "JL", "JNH", "JNL", "JZ", "JNZ",
}


def _join_continuations(raw_lines: list[str]) -> list[tuple[int, str]]:
    """Honor HLASM column-72 continuation. Returns (orig_lineno, joined_line)."""
    joined: list[tuple[int, str]] = []
    buf: str | None = None
    buf_lineno = 0
    for i, line in enumerate(raw_lines, start=1):
        # Strip trailing newline only; preserve internal columns.
        body = line.rstrip("\r\n")
        is_cont = len(body) > _CONT_COL and body[_CONT_COL] != " "
        src = body[:_SRC_END]
        if buf is None:
            buf = src
            buf_lineno = i
        else:
            # Continuation lines start in column 16 (index 15); strip leading
            # whitespace and append.
            buf = buf + src.lstrip()
        if not is_cont:
            joined.append((buf_lineno, buf))
            buf = None
    if buf is not None:
        joined.append((buf_lineno, buf))
    return joined


_LINE_RE = re.compile(
    r"""^
        (?P<label>\S*)              # label or empty
        \s+
        (?P<op>\S+)                 # op
        (?:\s+(?P<rest>\S.*))?      # operands + optional comment
        $""",
    re.VERBOSE,
)


def tokenize(joined: list[tuple[int, str]]) -> list[Line]:
    out: list[Line] = []
    for lineno, text in joined:
        if not text.strip() or text.lstrip().startswith("*"):
            continue
        # If column 1 is whitespace there is no label.
        if text and text[0] == " ":
            text_for_match = " " + text.lstrip()
            m = re.match(r"^\s+(?P<op>\S+)(?:\s+(?P<rest>\S.*))?$", text_for_match)
            if not m:
                continue
            label = ""
            op = m.group("op")
            rest = m.group("rest") or ""
        else:
            m = _LINE_RE.match(text)
            if not m:
                continue
            label = m.group("label")
            op = m.group("op")
            rest = m.group("rest") or ""

        op_upper = op.upper()
        # Split rest into operands (first whitespace-delimited token) + comment.
        # For zero-operand ops the entire `rest` is a comment.
        if op_upper in ZERO_OPERAND_OPS:
            operands = ""
            comment = rest.strip()
        elif rest:
            sub = re.match(r"^(\S+)(?:\s+(.*))?$", rest)
            operands = sub.group(1) if sub else rest
            comment = (sub.group(2) or "").strip() if sub else ""
        else:
            operands = ""
            comment = ""

        out.append(Line(lineno, label, op_upper, operands, comment, text))
    return out


def analyze(lines: list[Line], path: str) -> ParseResult:
    result = ParseResult(path=path)
    current: Section | None = None
    counts = {"instructions": 0, "macros": 0, "labels": 0}

    def open_section(name: str, kind: str, lineno: int) -> Section:
        sec = Section(name=name or f"<unnamed-{kind.lower()}>", kind=kind, start_line=lineno)
        result.sections.append(sec)
        return sec

    for ln in lines:
        # Section boundaries.
        if ln.op == "CSECT":
            current = open_section(ln.label, "CSECT", ln.lineno)
            continue
        if ln.op == "DSECT":
            current = open_section(ln.label, "DSECT", ln.lineno)
            continue
        if ln.op == "RSECT":
            current = open_section(ln.label, "RSECT", ln.lineno)
            continue
        if ln.op == "END":
            current = None
            continue

        # USING / DROP — track DSECT-to-register bindings.
        if ln.op == "USING" and ln.operands:
            parts = [p.strip() for p in ln.operands.split(",")]
            if len(parts) >= 2:
                result.usings.append(
                    Using(lineno=ln.lineno, section=parts[0], register=parts[1])
                )
            continue

        if current is None:
            continue

        # Track labels declared on instruction / data lines (not directives
        # that already consumed the label).
        if ln.label and ln.op not in {"USING", "DROP", "EQU"}:
            current.labels.append(ln.label)
            counts["labels"] += 1

        # DSECT field layout — DC/DS entries become field descriptors.
        if current.kind == "DSECT" and ln.op in {"DC", "DS"}:
            if ln.label:
                current.fields.append(
                    Field(name=ln.label, type=ln.op, layout=ln.operands, comment=ln.comment)
                )
            continue

        # Branches inside a CSECT.
        if ln.op in _BRANCH_OPS and current.kind in {"CSECT", "RSECT"}:
            current.branches.append(
                Branch(lineno=ln.lineno, op=ln.op, target=ln.operands)
            )
            counts["instructions"] += 1
            continue

        # Native instructions or directives — count and move on.
        if ln.op in BASE_INSTRUCTIONS:
            counts["instructions"] += 1
            continue
        if ln.op in DIRECTIVES:
            continue

        # Anything else is a macro call. Look it up in the catalog.
        entry = lookup_macro(ln.op)
        call = MacroCall(
            lineno=ln.lineno,
            name=ln.op,
            operands=ln.operands,
            category=entry.category if entry else "unknown",
            semantics=entry.semantics if entry else "",
            java_mapping=entry.java_mapping if entry else "",
            known=entry is not None,
        )
        current.macro_calls.append(call)
        counts["macros"] += 1
        if entry is None:
            result.unknown_macros.append(ln.op)
        # Heuristic: ALCS entry macros register the section as an entry point.
        if entry and entry.category == "control" and ln.op.startswith("ENT"):
            current.entry_points.append(ln.label or current.name)

    result.stats = counts
    return result


def parse_file(path: str | Path) -> ParseResult:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    joined = _join_continuations(raw)
    lines = tokenize(joined)
    return analyze(lines, str(p))


def _main(argv: list[str]) -> int:
    import argparse
    import os

    from sabre_java_agent.hlasm.macros import EXTRA_PATH_ENV

    p = argparse.ArgumentParser(prog="hlasm-parse")
    p.add_argument("path", help="Path to an HLASM source file (.asm/.mac).")
    p.add_argument(
        "--macros",
        help="Optional extra macro catalog (YAML) layered on top of the bundled one.",
    )
    args = p.parse_args(argv[1:])

    if args.macros:
        os.environ[EXTRA_PATH_ENV] = str(Path(args.macros).resolve())

    result = parse_file(args.path)
    json.dump(result.to_dict(), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
