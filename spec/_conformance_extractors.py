# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Per-language symbol extractors for spec/validate_conformance.py.

Each function returns ``dict[exported_name, kind]`` where ``kind`` is one of
``function``, ``instance``, ``type``, or ``decorator``. Split out of
``validate_conformance.py`` so the main script stays under the 500-LOC ceiling.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _python_module_kinds(src_root: Path) -> dict[str, str]:
    """Scan Python source modules to build a name→kind map.

    Walks all .py files under *src_root*, collects module-level definitions,
    and returns a mapping from symbol name to its kind string.
    """
    kind_map: dict[str, str] = {}
    if not src_root.is_dir():
        return kind_map
    for py_file in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind_map[node.name] = "function"
            elif isinstance(node, ast.ClassDef):
                kind_map[node.name] = "type"
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        kind_map[target.id] = "instance"
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and not node.target.id.startswith("_")
            ):
                kind_map[node.target.id] = "instance"
    return kind_map


def get_python_exports(repo_root: Path | None = None) -> dict[str, str]:
    """Parse Python __all__ from __init__.py and determine kind for each name."""
    repo_root = repo_root or _REPO_ROOT
    init_path = repo_root / "src" / "provide" / "telemetry" / "__init__.py"
    if not init_path.exists():
        return {}

    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    all_names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__" and isinstance(node.value, ast.List):
                    all_names = [
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]

    src_root = repo_root / "src" / "provide" / "telemetry"
    kind_map = _python_module_kinds(src_root)

    result: dict[str, str] = {}
    for name in all_names:
        result[name] = kind_map.get(name, "instance")
    return result


def get_go_exports(repo_root: Path | None = None) -> dict[str, str]:
    """Parse exported symbol names and kinds from all non-test Go files in go/."""
    repo_root = repo_root or _REPO_ROOT
    go_dir = repo_root / "go"
    if not go_dir.is_dir():
        return {}
    exports: dict[str, str] = {}
    kind_patterns: list[tuple[str, str]] = [
        (r"^func ([A-Z][A-Za-z0-9]*)", "function"),
        (r"^var ([A-Z][A-Za-z0-9]*)", "instance"),
        (r"^type ([A-Z][A-Za-z0-9]*)", "type"),
    ]
    for go_file in sorted(go_dir.glob("*.go")):
        if go_file.name.endswith("_test.go"):
            continue
        text = go_file.read_text(encoding="utf-8")
        for pattern, kind in kind_patterns:
            for match in re.finditer(pattern, text, re.MULTILINE):
                exports[match.group(1)] = kind
        # Multi-line var blocks: var (\n  Name Type\n)
        for block in re.finditer(r"^var\s*\(\n(.*?)\n\)", text, re.MULTILINE | re.DOTALL):
            for line in block.group(1).splitlines():
                m = re.match(r"^\s+([A-Z][A-Za-z0-9]*)\b", line.strip())
                if m:
                    exports[m.group(1)] = "instance"
    return exports


def _parse_rust_use_exports(use_body: str) -> list[str]:
    """Extract exported symbol names from a Rust ``pub use`` statement body."""
    body = use_body.strip()
    names: list[str] = []
    if "{" in body and "}" in body:
        items = body[body.index("{") + 1 : body.rindex("}")]
        for item in re.split(r"\s*,\s*", items.strip()):
            if not item:
                continue
            if " as " in item:
                names.append(item.split(" as ")[1].strip())
            else:
                names.append(item.rsplit("::", 1)[-1].strip())
        return names

    target = body.rsplit("::", 1)[-1].strip()
    if " as " in target:
        return [target.split(" as ")[1].strip()]
    return [target]


def get_rust_exports(repo_root: Path | None = None) -> dict[str, str]:
    """Parse exported symbol names and kinds from rust/src/lib.rs via regex."""
    repo_root = repo_root or _REPO_ROOT
    lib_path = repo_root / "rust" / "src" / "lib.rs"
    if not lib_path.exists():
        return {}
    text = lib_path.read_text(encoding="utf-8")
    exports: dict[str, str] = {}

    # Direct declarations with kind
    kind_patterns: list[tuple[str, str]] = [
        (r"^\s*pub\s+(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
        (r"^\s*pub\s+struct\s+([A-Za-z_][A-Za-z0-9_]*)", "type"),
        (r"^\s*pub\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)", "type"),
        (r"^\s*pub\s+type\s+([A-Za-z_][A-Za-z0-9_]*)", "type"),
        (r"^\s*pub\s+static\s+(?:mut\s+)?([A-Za-z_][A-Za-z0-9_]*)", "instance"),
        (r"^\s*pub\s+const\s+([A-Za-z_][A-Za-z0-9_]*)", "instance"),
    ]
    for pattern, kind in kind_patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            exports[match.group(1)] = kind

    # Re-exports: determine kind from submodule source files
    rust_src = repo_root / "rust" / "src"
    sub_kinds: dict[str, str] = {}
    if rust_src.is_dir():
        for rs_file in sorted(rust_src.rglob("*.rs")):
            if rs_file.name == "lib.rs":
                continue
            rs_text = rs_file.read_text(encoding="utf-8")
            for pattern, kind in kind_patterns:
                for m in re.finditer(pattern, rs_text, re.MULTILINE):
                    sub_kinds[m.group(1)] = kind

    for match in re.finditer(r"^\s*pub\s+use\s+(.+?);", text, re.MULTILINE | re.DOTALL):
        for name in _parse_rust_use_exports(match.group(1)):
            exports[name] = sub_kinds.get(name, exports.get(name, "instance"))

    return exports


def _get_typescript_src_kinds(ts_src_dir: Path) -> dict[str, str]:
    """Scan TypeScript source files for top-level export declarations to get kinds."""
    kind_map: dict[str, str] = {}
    if not ts_src_dir.is_dir():
        return kind_map
    fn_pattern = re.compile(r"^export\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE)
    const_pattern = re.compile(r"^export\s+const\s+(\w+)", re.MULTILINE)
    class_pattern = re.compile(r"^export\s+(?:abstract\s+)?class\s+(\w+)", re.MULTILINE)
    type_pattern = re.compile(r"^export\s+(?:type|interface|enum)\s+(\w+)", re.MULTILINE)
    for ts_file in sorted(ts_src_dir.glob("*.ts")):
        if ts_file.name.startswith("react"):
            continue
        text = ts_file.read_text(encoding="utf-8")
        for m in fn_pattern.finditer(text):
            kind_map[m.group(1)] = "function"
        for m in const_pattern.finditer(text):
            kind_map[m.group(1)] = "instance"
        for m in class_pattern.finditer(text):
            kind_map[m.group(1)] = "type"
        for m in type_pattern.finditer(text):
            kind_map[m.group(1)] = "type"
    return kind_map


def get_typescript_exports(repo_root: Path | None = None) -> dict[str, str]:
    """Parse TypeScript export names and kinds from index.ts and source files."""
    repo_root = repo_root or _REPO_ROOT
    index_path = repo_root / "typescript" / "src" / "index.ts"
    if not index_path.exists():
        return {}
    text = index_path.read_text(encoding="utf-8")

    ts_src_dir = repo_root / "typescript" / "src"
    src_kinds = _get_typescript_src_kinds(ts_src_dir)

    exports: dict[str, str] = {}

    # export type { ... } → kind "type"
    for block in re.finditer(r"export\s+type\s+\{([^}]+)\}", text):
        for item in re.split(r"\s*,\s*", block.group(1).strip()):
            if not item:
                continue
            name = item.split(" as ")[-1].strip() if " as " in item else item.strip()
            exports[name] = "type"

    # export { ... } → look up kind from source files
    for block in re.finditer(r"export\s+\{([^}]+)\}", text):
        # Skip if this is a "export type {" block (already handled above)
        raw = block.group(0)
        if "export type " in raw:
            continue
        for item in re.split(r"\s*,\s*", block.group(1).strip()):
            if not item:
                continue
            parts = item.split(" as ")
            original = parts[0].strip()
            exported = parts[-1].strip()
            kind = src_kinds.get(original, src_kinds.get(exported, "function"))
            exports[exported] = kind

    return exports
