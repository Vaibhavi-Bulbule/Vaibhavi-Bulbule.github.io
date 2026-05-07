# Sabre Java Agent

A Claude Agent SDK agent that produces Java code for Sabre Airlines workloads from
two kinds of input:

1. **Legacy IBM HLASM source** (TPF / ALCS assembler) — converted into idiomatic Java.
2. **User stories** (markdown / Jira-style) — implemented as Java code with JUnit tests.

The agent runs locally, reads/writes files in your project, and can shell out to
`mvn` / `gradle` to compile what it produces.

## Requirements

- Python 3.10+
- An `ANTHROPIC_API_KEY`
- Java 17+ and Maven (only if you want the agent to compile its output)

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
# put your key into .env
```

## Usage

Three modes — pick one per run:

```powershell
# 1. Inline prompt — paste ASM or describe the story
sabre-java-agent --prompt "Convert this ENTNC routine to Java: ..." --out .\out

# 2. Convert an HLASM source file
sabre-java-agent --asm .\examples\sample_alcs.asm --out .\out

# 3. Implement a user story
sabre-java-agent --story .\examples\sample_story.md --out .\out
```

You can mix flags — e.g. `--asm foo.asm --prompt "target Java 17 records"` to add
guidance on top of a file.

### `--macros <path>` — try a candidate catalog without committing it

```powershell
sabre-java-agent --asm .\src\fare.asm --macros .\candidate-macros.yml --out .\out
```

The CLI catalog is layered on top of the bundled and project-local catalogs;
entries here win on name collision. Useful for iterating on a candidate macro
list before promoting it to `<project>/.sabre/macros.yml`.

### `--macros-print` — debug what the agent will actually see

```powershell
# pretty table
sabre-java-agent --macros-print
sabre-java-agent --macros-print --macros .\candidate-macros.yml

# JSON, for piping into jq / scripts
sabre-java-agent --macros-print --json
```

Resolves all three layers (bundled / `<project>/.sabre/macros.yml` /
`--macros`), prints each entry with its source, flags entries that shadow
lower-priority layers with `*`, and exits. Does not call the API, so it
runs without an `ANTHROPIC_API_KEY`.

## What it does

- Reads inputs (file or inline).
- For HLASM input: runs a real structural parse (CSECTs, DSECTs, USING
  bindings, branches, TPF/ALCS macro calls) before the model touches the
  source — so the model translates from facts, not from staring at columns.
- Plans the Java structure (package, classes, methods, tests).
- Writes Java source under `--out` (default: `./generated`).
- Documents non-obvious HLASM → Java mappings as inline comments **only when
  the original mainframe semantics would surprise a Java reader**
  (register conventions, ECB work areas, TPF macros).
- Optionally compiles via Maven if a `pom.xml` is present in `--out`.

## HLASM macro catalog

The agent calls an in-process MCP server (`sabre_java_agent/mcp_server.py`)
exposing four tools:

- `hlasm_parse(path)` — structural outline (CSECTs, DSECTs, USING bindings,
  field layouts, branches, macro calls).
- `hlasm_macro_catalog()` — full catalog of known TPF/ALCS macros.
- `hlasm_macro_lookup(name)` — single-macro lookup; returns null if unknown
  so the agent asks instead of guessing.
- `hlasm_macro_save({name, category, semantics, java_mapping, overwrite?, target?})`
  — persist a new macro into the project-local catalog so future runs
  recognize it. The agent calls this only after asking the user for the
  semantics. Refuses to overwrite without `overwrite=true`; refuses to
  modify the bundled package catalog at all.

When the parser encounters an unknown macro, the agent's discovery flow is:
**parse → ask user for semantics → save via `hlasm_macro_save` → continue
translation**. Subsequent runs in the same project pick up the learned
entry automatically.

**Catalog precedence** (each layer overrides the previous on name collision):

1. Bundled — `sabre_java_agent/hlasm/macros.yml` (~46 common TPF/ALCS macros)
2. Project-local — `<cwd>/.sabre/macros.yml`
3. CLI — `--macros <path>`

You can drive the parser standalone for debugging — it accepts `--macros` too:

```powershell
py -3 -m sabre_java_agent.hlasm.parser .\examples\sample_alcs.asm
py -3 -m sabre_java_agent.hlasm.parser .\examples\sample_alcs.asm --macros .\examples\extra_macros.yml
```

## What it does NOT do

- It does not guess at TPF macro behavior it has not seen — if a macro is
  unfamiliar it asks or stubs an interface so you can wire the real adapter.
- It does not rewrite untouched code.
- It does not invent acceptance criteria — if a story is ambiguous it asks.

## Project layout

```
sabre_java_agent/
  agent.py        # SDK query loop
  prompts.py      # HLASM/ALCS-specialized system prompt + templates
  cli.py          # argparse entrypoint
examples/
  sample_alcs.asm
  sample_story.md
```
