"""Loader for the macro catalog. Reads the bundled `macros.yml` plus an
optional user override at `<project>/.sabre/macros.yml` so each project can
extend coverage without modifying the package.

Defaults are env-driven so the CLI can plumb invocation-time context
(invocation cwd, --macros file) once and have every downstream caller —
parser, MCP tools, save_macro — pick it up without a parameter chain.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


# Env vars the CLI sets before launching the agent loop.
EXTRA_PATH_ENV = "SABRE_MACROS_FILE"     # --macros override
PROJECT_ROOT_ENV = "SABRE_PROJECT_ROOT"  # invocation cwd, for .sabre/macros.yml


def _extra_path_from_env() -> str | None:
    p = os.environ.get(EXTRA_PATH_ENV)
    return p if p else None


def _project_root_from_env() -> str | None:
    p = os.environ.get(PROJECT_ROOT_ENV)
    return p if p else None


@dataclass(frozen=True)
class MacroEntry:
    name: str
    category: str
    semantics: str
    java_mapping: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "category": self.category,
            "semantics": self.semantics,
            "java_mapping": self.java_mapping,
        }


_BUNDLED = Path(__file__).with_name("macros.yml")


def _load_file(path: Path) -> list[MacroEntry]:
    if not path.exists():
        return []
    # Import lazily so the parser can run without PyYAML when only the
    # structural pass is needed (tests, debugging). If PyYAML is missing,
    # the catalog is treated as empty and every macro is reported as unknown.
    try:
        import yaml
    except ImportError:
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        MacroEntry(
            name=item["name"].upper(),
            category=item.get("category", "other"),
            semantics=item.get("semantics", ""),
            java_mapping=item.get("java_mapping", ""),
        )
        for item in raw
    ]


@lru_cache(maxsize=8)
def _load_catalog_cached(
    project_root: str | None,
    extra_path: str | None,
) -> dict[str, MacroEntry]:
    entries = _load_file(_BUNDLED)

    def _merge(extra: list[MacroEntry]) -> None:
        nonlocal entries
        for entry in extra:
            entries = [e for e in entries if e.name != entry.name] + [entry]

    if project_root:
        _merge(_load_file(Path(project_root) / ".sabre" / "macros.yml"))
    if extra_path:
        _merge(_load_file(Path(extra_path)))
    return {e.name: e for e in entries}


def load_catalog(
    project_root: str | None = None,
    extra_path: str | None = None,
) -> dict[str, MacroEntry]:
    """Load the macro catalog with layered precedence:

    1. Bundled `macros.yml` (lowest priority)
    2. `<project_root>/.sabre/macros.yml`
    3. `extra_path` — typically the CLI `--macros` flag (highest)

    Later layers override earlier ones on name collision. Unspecified args
    fall back to env vars set by the CLI; if those are also unset the layer
    is skipped.
    """
    if project_root is None:
        project_root = _project_root_from_env()
    if extra_path is None:
        extra_path = _extra_path_from_env()
    return _load_catalog_cached(project_root, extra_path)


def lookup(name: str) -> MacroEntry | None:
    return load_catalog().get(name.upper())


def _project_local_path() -> Path:
    """Default target for save_macro: <project_root>/.sabre/macros.yml.

    Resolution order: PROJECT_ROOT_ENV → cwd. Resolved at call time so a
    fresh CLI invocation always picks up the current project root."""
    root = _project_root_from_env() or str(Path.cwd())
    return Path(root) / ".sabre" / "macros.yml"


def dump_with_provenance() -> dict:
    """Resolve all three catalog layers and report per-entry source.

    Used by `--macros-print` for debugging. Returns a dict shaped for both
    pretty-printing and JSON consumption:

        {
          "sources":  {"bundled": path, "project": path|None, "cli": path|None},
          "counts":   {"bundled": N, "project": N, "cli": N,
                       "total_resolved": N, "shadowed": N},
          "entries":  [{"name", "source", "category", "semantics",
                        "java_mapping", "shadowed_in": [...]}, ...]
        }

    `shadowed_in` lists lower-priority layers that also defined the macro
    but lost the merge — useful for spotting accidental overrides.
    """
    bundled = {e.name: e for e in _load_file(_BUNDLED)}

    project_root = _project_root_from_env() or str(Path.cwd())
    project_path = Path(project_root) / ".sabre" / "macros.yml"
    project = {e.name: e for e in _load_file(project_path)} if project_path.exists() else {}

    extra_path = _extra_path_from_env()
    extra = (
        {e.name: e for e in _load_file(Path(extra_path))}
        if extra_path and Path(extra_path).exists()
        else {}
    )

    sources = {
        "bundled": str(_BUNDLED),
        "project": str(project_path) if project_path.exists() else None,
        "cli": str(extra_path) if extra_path else None,
    }

    # Resolve highest-priority-wins, tracking which lower layers were shadowed.
    resolved: list[dict] = []
    all_names = set(bundled) | set(project) | set(extra)
    for name in sorted(all_names):
        if name in extra:
            entry, src = extra[name], "cli"
        elif name in project:
            entry, src = project[name], "project"
        else:
            entry, src = bundled[name], "bundled"
        shadowed_in = []
        for other_src, layer in (("cli", extra), ("project", project), ("bundled", bundled)):
            if other_src != src and name in layer:
                shadowed_in.append(other_src)
        resolved.append(
            {
                **entry.to_dict(),
                "source": src,
                "shadowed_in": shadowed_in,
            }
        )

    counts = {
        "bundled": len(bundled),
        "project": len(project),
        "cli": len(extra),
        "total_resolved": len(resolved),
        "shadowed": sum(1 for r in resolved if r["shadowed_in"]),
    }
    return {"sources": sources, "counts": counts, "entries": resolved}


def save_macro(
    entry: MacroEntry,
    target: Path | None = None,
    overwrite: bool = False,
) -> dict:
    """Persist `entry` into the project-local catalog (or `target` if given).

    - Refuses to write to the bundled package catalog.
    - Refuses to overwrite an existing entry of the same name unless
      `overwrite=True`.
    - Preserves any leading comment block in an existing target file.
    - Writes atomically via temp file + os.replace.
    - Clears the load cache so subsequent lookups see the new entry.

    Returns a dict suitable for tool output describing what happened.
    """
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML is required to save macros") from e

    if target is None:
        target = _project_local_path()
    target = Path(target).resolve()

    if target == _BUNDLED.resolve():
        raise ValueError(
            "refusing to write the bundled package catalog; pass a different target "
            "or write to <project>/.sabre/macros.yml"
        )

    existing_list = _load_file(target) if target.exists() else []
    existing = {e.name: e for e in existing_list}
    already_present = entry.name in existing

    if already_present and not overwrite:
        raise ValueError(
            f"{entry.name} already in {target}; pass overwrite=True to replace it"
        )

    # Preserve any leading comment / blank lines so handwritten headers
    # in an existing target survive the rewrite.
    if target.exists():
        header_lines: list[str] = []
        for line in target.read_text(encoding="utf-8").splitlines(keepends=True):
            if line.strip() == "" or line.lstrip().startswith("#"):
                header_lines.append(line)
            else:
                break
        header = "".join(header_lines)
    else:
        header = (
            "# Project-local TPF/ALCS macro catalog.\n"
            "# Managed by sabre-java-agent (`hlasm_macro_save`). Edit by hand if you like.\n"
            "# Entries here override the bundled catalog on name collision.\n\n"
        )

    existing[entry.name] = entry
    payload = [e.to_dict() for e in existing.values()]

    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp file in the same directory + os.replace.
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=".macros-", suffix=".yml.tmp", dir=str(target.parent)
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(header)
            yaml.safe_dump(
                payload,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    _load_catalog_cached.cache_clear()

    return {
        "saved": entry.to_dict(),
        "target": str(target),
        "total_entries_in_target": len(existing),
        "replaced_existing": already_present,
    }
