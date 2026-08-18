#!/usr/bin/env python3
"""Fail when public/tracked project text contains machine-specific absolute paths.

The scanner intentionally describes *classes* of private paths.  It must never
encode a particular developer username or workstation path in public source.
When a Git worktree is available, only tracked files are scanned.  Transferable
source snapshots without .git use a conservative public-tree fallback.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable

TEXT_LIMIT = 8 * 1024 * 1024
EXCLUDED_PARTS = {
    ".git",
    ".local",
    "cache",
    "caches",
    "build",
    "dist",
    "backups",
    "workspace",
    "__pycache__",
}

# Match concrete user-home paths, not generic documentation such as
# regex source text that itself contains character classes.
POSIX_USER_HOME = re.compile(rb"(?<![A-Za-z0-9._-])/(?:home|Users)/[A-Za-z0-9._-]+/")
WINDOWS_USER_HOME = re.compile(
    rb"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'<>|]+[\\/])"
)
MOUNTED_RUNTIME_ROOT = re.compile(rb"(?<![A-Za-z0-9._-])/(?:mnt|media)/[A-Za-z0-9._-]+(?:/|$)")


def git_tracked_files(root: Path) -> list[Path] | None:
    if not (root / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return [root / os.fsdecode(item) for item in proc.stdout.split(b"\0") if item]


def fallback_public_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        yield path


def is_probably_text(data: bytes) -> bool:
    return b"\0" not in data[:8192]


def eval_static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = eval_static_string(node.left)
        right = eval_static_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return None
            parts.append(value.value)
        return "".join(parts)
    return None


def reconstructed_python_strings(path: Path, text: str) -> Iterable[tuple[int, bytes]]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[tuple[int, bytes]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.BinOp, ast.JoinedStr)):
            continue
        value = eval_static_string(node)
        if value is not None:
            out.append((getattr(node, "lineno", 0), value.encode("utf-8", "surrogatepass")))
    return out


def violations_for_blob(blob: bytes) -> list[str]:
    kinds: list[str] = []
    if POSIX_USER_HOME.search(blob):
        kinds.append("concrete POSIX user-home path")
    if WINDOWS_USER_HOME.search(blob):
        kinds.append("concrete Windows user-profile path")
    if MOUNTED_RUNTIME_ROOT.search(blob):
        kinds.append("mounted local absolute path")
    return kinds


def scan(root: Path) -> list[tuple[Path, int | None, str]]:
    tracked = git_tracked_files(root)
    files = tracked if tracked is not None else list(fallback_public_files(root))
    findings: list[tuple[Path, int | None, str]] = []
    for path in files:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > TEXT_LIMIT:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if not is_probably_text(data):
            continue
        for kind in violations_for_blob(data):
            findings.append((path.relative_to(root), None, kind))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, reconstructed in reconstructed_python_strings(path, text):
            for kind in violations_for_blob(reconstructed):
                findings.append((path.relative_to(root), lineno, f"statically reconstructed {kind}"))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = ap.parse_args()
    root = args.project_root.resolve()
    findings = scan(root)
    if findings:
        print("RELEASE HYGIENE: FAIL", file=sys.stderr)
        for rel, lineno, kind in findings:
            suffix = f":{lineno}" if lineno else ""
            print(f"  {rel}{suffix}: {kind}", file=sys.stderr)
        return 1
    print("RELEASE HYGIENE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
