#!/usr/bin/env python3
"""Target-aware local Translation build/repack/marker/preview/prepare/install workflow.

This is a development orchestrator. Installation is opt-in and requires --install --yes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPORT_TYPE = "br_local_translation_workflow_report"
REPORT_FORMAT_VERSION = 5
DEFAULT_TRANSLATION_MODULE = "blue_reflection_translation"
RESTORATION_MODULE = "quartet_restoration"
LEGACY_DLC_MODULE = "quartet_legacy_dlc"
ROUTING_REGISTRY_RELATIVE = Path("config/translation_target_routes.json")

CURRENT_WORKSPACE_MARKER = ".br_current_source.json"


class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, details: Sequence[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = list(details or [])


@dataclass
class StepRecord:
    name: str
    status: str
    started_utc: str
    finished_utc: str
    command: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class WorkflowReport:
    type: str = REPORT_TYPE
    format_version: int = REPORT_FORMAT_VERSION
    status: str = "running"
    generated_utc: str = ""
    project_root: str = ""
    game_root: str = ""
    target_id: str = ""
    display_name: str = ""
    core_version: str = ""
    translation_tooling_version: str = ""
    translation_version: str = ""
    quartet_restoration_version: str = ""
    quartet_legacy_dlc_version: str = ""
    selected_modules: list[str] = field(default_factory=list)
    preview_only: bool = False
    install_requested: bool = False
    game_files_modified: bool = False
    commit_enabled: bool = False
    patcher_path: str = ""
    workspace_source: str = ""
    marker_source: str = ""
    payload_preview_report: str = ""
    composition_preview_report: str = ""
    composition_build_report: str = ""
    transaction_prepare_report: str = ""
    transaction_commit_report: str = ""
    transaction_journal: str = ""
    baseline_manifest: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class Runner:
    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        capture: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        rendered = [str(item) for item in command]
        return subprocess.run(
            rendered,
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env else None,
            check=True,
            text=True,
            capture_output=capture,
        )


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_generated_source(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("\t")
        if not separator:
            raise WorkflowError("invalid_workspace_provenance", f"Invalid provenance row: {path}: {line!r}")
        values[key] = value
    return values


def normalize_modules(value: str) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()
    for item in value.split(","):
        module = item.strip()
        if not module or module in seen:
            continue
        seen.add(module)
        modules.append(module)
    return modules


def resolve_case_insensitive(root: Path, relative: str) -> Path | None:
    """Resolve a safe game-relative path component-by-component.

    Windows installations copied to a case-sensitive Linux filesystem often
    contain ``Data`` or ``data`` while project metadata deliberately keeps one
    canonical spelling. Detection already accepts those layouts; the local
    build workflow must resolve them identically instead of constructing a
    case-sensitive path that does not exist.
    """
    parts = Path(relative.replace("\\", "/")).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    current = root
    for part in parts:
        exact = current / part
        if exact.exists() or exact.is_symlink():
            current = exact
            continue
        try:
            matches = [entry for entry in current.iterdir() if entry.name.casefold() == part.casefold()]
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return None
        if len(matches) != 1:
            return None
        current = matches[0]
    return current


class LocalTranslationWorkflow:
    def __init__(self, project_root: Path, runner: Runner | None = None):
        self.project_root = project_root.resolve()
        self.runner = runner or Runner()
        self.report = WorkflowReport(project_root=str(self.project_root), generated_utc=utc_now())
        self.report_dir = self.project_root / ".local/reports/core"
        self.build_dir = self.project_root / ".local/build/patcher"
        self.patcher_root = self.project_root / "Blue_Reflection_Patcher"
        self.patcher = self.build_dir / "blue-reflection-patcher-linux-x86_64"
        self.routes = self._load_routes()

    def _load_routes(self) -> dict[str, Any]:
        path = self.project_root / ROUTING_REGISTRY_RELATIVE
        if not path.is_file():
            raise WorkflowError("routing_registry_missing", f"Translation routing registry is missing: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") != "br_translation_target_routes" or data.get("format_version") != 1:
            raise WorkflowError("routing_registry_invalid", "Unsupported Translation routing registry")
        installations = data.get("installation_targets")
        content_targets = data.get("content_targets")
        if not isinstance(installations, dict) or not isinstance(content_targets, dict):
            raise WorkflowError("routing_registry_invalid", "Translation routing registry is incomplete")
        for installation_id, route in installations.items():
            if not isinstance(route, dict) or not route.get("module_id") or not route.get("content_targets"):
                raise WorkflowError("routing_registry_invalid", f"Invalid installation route: {installation_id}")
            for content_id in route["content_targets"]:
                content = content_targets.get(content_id)
                if not isinstance(content, dict) or content.get("installation_target_id") != installation_id:
                    raise WorkflowError(
                        "routing_registry_invalid",
                        f"Content route {content_id} does not belong to {installation_id}",
                    )
        return data

    def installation_route(self, target_id: str) -> dict[str, Any]:
        route = self.routes["installation_targets"].get(target_id)
        if not isinstance(route, dict):
            raise WorkflowError("unsupported_target", f"No Translation route for installation target {target_id}")
        return route

    def content_routes(self, target_id: str) -> list[tuple[str, dict[str, Any]]]:
        installation = self.installation_route(target_id)
        result: list[tuple[str, dict[str, Any]]] = []
        for content_id in installation["content_targets"]:
            route = self.routes["content_targets"].get(content_id)
            if not isinstance(route, dict):
                raise WorkflowError("routing_registry_invalid", f"Missing content route: {content_id}")
            result.append((content_id, route))
        return result

    def record_step(
        self,
        name: str,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        capture: bool = False,
        note: str = "",
    ) -> subprocess.CompletedProcess[str]:
        started = utc_now()
        rendered = [str(item) for item in command]
        try:
            result = self.runner.run(rendered, cwd=cwd, env=env, capture=capture)
        except subprocess.CalledProcessError as error:
            finished = utc_now()
            detail = (error.stderr or error.stdout or "").strip()
            self.report.steps.append(
                StepRecord(name=name, status="failed", started_utc=started, finished_utc=finished, command=rendered, note=detail)
            )
            raise WorkflowError("step_failed", f"Step failed: {name}", [detail] if detail else rendered) from error
        self.report.steps.append(
            StepRecord(name=name, status="ok", started_utc=started, finished_utc=utc_now(), command=rendered, note=note)
        )
        return result

    def ensure_project(self) -> None:
        required = [
            self.project_root / "workstreams/core/VERSION",
            self.patcher_root / "go.mod",
            self.project_root / "Blue_Reflection_Text_Tool/br_text_tool.py",
            self.project_root / "config/text_source_archives.tsv",
            self.project_root / ROUTING_REGISTRY_RELATIVE,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise WorkflowError("invalid_project", "Required project files are missing", missing)
        version_fields = {
            "core_version": "core",
            "translation_tooling_version": "translation_tooling",
            "translation_version": "translation",
            "quartet_restoration_version": "quartet_restoration",
            "quartet_legacy_dlc_version": "quartet_legacy_dlc",
        }
        for field_name, workstream_id in version_fields.items():
            version_path = self.project_root / "workstreams" / workstream_id / "VERSION"
            if not version_path.is_file():
                raise WorkflowError(
                    "invalid_project",
                    f"Required workstream VERSION is missing: {workstream_id}",
                    [str(version_path)],
                )
            version = version_path.read_text(encoding="utf-8").strip()
            if not version:
                raise WorkflowError(
                    "invalid_project",
                    f"Required workstream VERSION is empty: {workstream_id}",
                    [str(version_path)],
                )
            setattr(self.report, field_name, version)

    def ensure_patcher(self, force: bool = False) -> Path:
        source_files = list(self.patcher_root.rglob("*.go")) + [self.patcher_root / "go.mod"]
        rebuild = force or not self.patcher.is_file()
        if not rebuild and source_files:
            newest_source = max(path.stat().st_mtime_ns for path in source_files if path.is_file())
            rebuild = self.patcher.stat().st_mtime_ns < newest_source
        if rebuild:
            if shutil.which("go") is None:
                raise WorkflowError("missing_go", "Go compiler is required to build the local patcher")
            self.build_dir.mkdir(parents=True, exist_ok=True)
            self.record_step(
                "build_patcher",
                ["go", "build", "-trimpath", "-o", self.patcher, "./cmd/brpatcher"],
                cwd=self.patcher_root,
            )
        self.report.patcher_path = str(self.patcher)
        return self.patcher

    def detect_target(self, game_root: Path) -> dict[str, Any]:
        report_path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_DETECTION.json"
        self.record_step(
            "detect_target",
            [self.patcher, "detect", "--game-dir", game_root, "--json", report_path],
            capture=False,
        )
        data = json.loads(report_path.read_text(encoding="utf-8"))
        if len(data) != 1:
            raise WorkflowError("ambiguous_target", f"Expected exactly one detected installation, found {len(data)}")
        target = data[0]
        self.report.game_root = target["root"]
        self.report.target_id = target["target_id"]
        self.report.display_name = target["display_name"]
        return target

    def validate_modules(self, target_id: str, modules: list[str]) -> list[str]:
        translation_module = str(self.installation_route(target_id)["module_id"])
        if not modules:
            modules = [translation_module]
        if translation_module not in modules:
            raise WorkflowError(
                "translation_required",
                f"The local Translation workflow for {target_id} requires {translation_module}",
            )
        allowed = {translation_module}
        if target_id == "blue_reflection_quartet":
            allowed.update({RESTORATION_MODULE, LEGACY_DLC_MODULE})
        unsupported = [module for module in modules if module not in allowed]
        if unsupported:
            raise WorkflowError(
                "unsupported_modules",
                f"Unsupported module selection for {target_id}",
                unsupported,
            )
        self.report.selected_modules = modules
        return modules

    def installation_status(self, game_root: Path) -> dict[str, Any]:
        path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_INSTALLATION_STATUS.json"
        self.record_step(
            "installation_status",
            [self.patcher, "installation-status", "--game-dir", game_root, "--json", path],
        )
        status = json.loads(path.read_text(encoding="utf-8"))
        if not status.get("automatic_prepare_allowed", False):
            raise WorkflowError(
                "installation_state_unsafe",
                f"Installation state is not safe for automatic preparation: {status.get('status')}",
                status.get("active_state", {}).get("warnings", []) + status.get("baseline", {}).get("warnings", []),
            )
        return status

    def _baseline_manifest_from_status(self, status: dict[str, Any]) -> Path | None:
        active = status.get("active_state", {})
        if active.get("active") and active.get("state_path"):
            state = json.loads(Path(active["state_path"]).read_text(encoding="utf-8"))
            value = state.get("baseline_manifest_path")
            if value:
                return Path(value)
        baseline = status.get("baseline", {})
        match_id = baseline.get("matching_baseline_id")
        if match_id:
            for summary in baseline.get("baselines") or []:
                if summary.get("baseline_id") == match_id and summary.get("manifest_path"):
                    return Path(summary["manifest_path"])
        return None

    def _source_for_archive(self, game_root: Path, status: dict[str, Any], relative: str) -> tuple[Path, str]:
        manifest_path = self._baseline_manifest_from_status(status)
        if manifest_path and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest.get("files", []):
                if item.get("relative_path", "").lower() == relative.replace("\\", "/").lower():
                    stored = item.get("stored_path")
                    if item.get("existed") and stored:
                        candidate = manifest_path.parent / stored
                        if not candidate.is_file():
                            raise WorkflowError(
                                "baseline_source_invalid",
                                f"Persistent baseline source is missing: {relative}",
                                [str(candidate)],
                            )
                        expected_size = int(item.get("bytes", -1))
                        expected_hash = str(item.get("sha256", ""))
                        current_size = candidate.stat().st_size
                        current_hash = sha256_file(candidate)
                        if current_size != expected_size or current_hash != expected_hash:
                            raise WorkflowError(
                                "baseline_source_invalid",
                                f"Persistent baseline source failed verification: {relative}",
                                [
                                    f"expected={expected_hash}/{expected_size}",
                                    f"current={current_hash}/{current_size}",
                                    str(candidate),
                                ],
                            )
                        return candidate, f"persistent_baseline:{manifest.get('baseline_id', '')}"
        canonical = game_root / Path(relative)
        resolved = resolve_case_insensitive(game_root, relative)
        if resolved is not None:
            source_kind = "current_installation"
            if resolved.absolute() != canonical.absolute():
                source_kind = "current_installation_case_insensitive"
            return resolved, source_kind
        return canonical, "current_installation"

    def _canonical_source_view(self, target_id: str, relative: str, source: Path) -> Path:
        """Publish a read-only canonical-path view of one resolved source PAK.

        Marker builders intentionally use canonical game-relative paths.  A
        symlink-only generated view lets them keep that invariant while reading
        an installation whose on-disk capitalization differs.  No game file is
        copied or modified.
        """
        source_hash = sha256_file(source)
        key_material = f"{target_id}\0{relative}\0{source_hash}\0{source.stat().st_size}".encode("utf-8")
        view_id = hashlib.sha256(key_material).hexdigest()[:24]
        views_root = self.project_root / ".local/build/core/local_translation_source_views"
        view_root = views_root / target_id / view_id
        destination = view_root / Path(relative)
        if destination.is_symlink():
            try:
                if destination.resolve(strict=True) == source.resolve(strict=True):
                    return view_root
            except FileNotFoundError:
                pass
        if view_root.exists():
            shutil.rmtree(view_root)
        temporary = view_root.with_name(view_root.name + f".tmp-{os.getpid()}")
        if temporary.exists():
            shutil.rmtree(temporary)
        destination_tmp = temporary / Path(relative)
        destination_tmp.parent.mkdir(parents=True, exist_ok=True)
        destination_tmp.symlink_to(source.resolve())
        view_root.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, view_root)
        return view_root

    def marker_source_root(self, target_id: str, game_root: Path, status: dict[str, Any]) -> Path:
        relative = self.installation_route(target_id).get("marker_archive")
        if not relative:
            raise WorkflowError("unsupported_target", f"Unsupported target: {target_id}")
        source, source_kind = self._source_for_archive(game_root, status, relative)
        if not source.is_file():
            raise WorkflowError(
                "marker_source_missing",
                f"Title-marker source archive is missing: {relative}",
                [str(source)],
            )
        root = source
        for _ in Path(relative).parts:
            root = root.parent
        resolved_candidate = root / Path(relative)
        try:
            canonical_representation = resolved_candidate.resolve(strict=True) == source.resolve(strict=True)
        except FileNotFoundError:
            canonical_representation = False
        if not canonical_representation:
            root = self._canonical_source_view(target_id, relative, source)
            source_kind += ":canonical_path_view"
        self.report.marker_source = source_kind
        return root

    def _extract_current_archive(
        self,
        *,
        target_id: str,
        archive_stem: str,
        relative: str,
        source: Path,
        source_kind: str,
        gust_pak: Path,
        timeout_seconds: int = 1800,
    ) -> dict[str, Any]:
        source_hash = sha256_file(source)
        source_bytes = source.stat().st_size
        gust_hash = sha256_file(gust_pak)
        fingerprint = hashlib.sha256(
            f"{target_id}\0{relative.casefold()}\0{source_hash}\0{source_bytes}\0{gust_hash}".encode("utf-8")
        ).hexdigest()
        final = (
            self.project_root / ".local/build/core/version_workspaces"
            / target_id / fingerprint / archive_stem
        )
        manifest_name = f"{archive_stem}.json"
        marker = {
            "type": "br_current_target_archive_extraction",
            "format_version": 1,
            "target_id": target_id,
            "archive_stem": archive_stem,
            "source_archive_relative": relative,
            "source_archive_sha256": source_hash,
            "source_archive_bytes": source_bytes,
            "source_kind": source_kind,
            "gust_pak_sha256": gust_hash,
            "manifest_name": manifest_name,
        }
        marker_path = final / CURRENT_WORKSPACE_MARKER
        if marker_path.is_file() and (final / manifest_name).is_file():
            try:
                if json.loads(marker_path.read_text(encoding="utf-8")) == marker:
                    return {**marker, "workspace": final, "manifest": final / manifest_name, "status": "reused"}
            except (json.JSONDecodeError, OSError):
                pass

        final.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{archive_stem}.", dir=final.parent))
        try:
            linked = temporary / source.name
            linked.symlink_to(source.resolve())
            log_path = temporary / ".gust_pak_extract.log"
            with log_path.open("wb") as log_handle:
                result = subprocess.run(
                    [str(gust_pak), source.name],
                    cwd=temporary,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    timeout=timeout_seconds,
                    check=False,
                )
            linked.unlink(missing_ok=True)
            if result.returncode != 0:
                excerpt = log_path.read_text(encoding="utf-8", errors="replace")[:4000]
                raise WorkflowError(
                    "target_archive_extract_failed",
                    f"gust_pak failed while extracting {relative}",
                    [excerpt],
                )
            manifest = temporary / manifest_name
            if not manifest.is_file():
                candidates = sorted(temporary.glob("*.json"))
                if len(candidates) == 1:
                    candidates[0].rename(manifest)
                else:
                    raise WorkflowError(
                        "target_archive_extract_failed",
                        f"gust_pak did not create {manifest_name} for {relative}",
                        [str(path) for path in candidates],
                    )
            atomic_json(temporary / CURRENT_WORKSPACE_MARKER, marker)
            if final.exists():
                shutil.rmtree(final)
            os.replace(temporary, final)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {**marker, "workspace": final, "manifest": final / manifest_name, "status": "extracted"}

    def prepare_target_workspace(
        self,
        target_id: str,
        game_root: Path,
        status: dict[str, Any],
        gust_pak: Path,
    ) -> Path:
        rows: list[dict[str, Any]] = []
        source_kinds: set[str] = set()
        content_target_ids: list[str] = []
        for content_target_id, content_route in self.content_routes(target_id):
            content_target_ids.append(content_target_id)
            for archive in content_route.get("archives", []):
                if not archive.get("production_text", False):
                    continue
                archive_stem = str(archive["archive_stem"])
                relative = str(archive["relative_path"])
                source, source_kind = self._source_for_archive(game_root, status, relative)
                if not source.is_file():
                    raise WorkflowError(
                        "target_archive_missing",
                        f"Required current target archive is missing: {relative}",
                        [str(source)],
                    )
                extracted = self._extract_current_archive(
                    target_id=content_target_id,
                    archive_stem=archive_stem,
                    relative=relative,
                    source=source,
                    source_kind=source_kind,
                    gust_pak=gust_pak,
                )
                source_kinds.add(source_kind)
                rows.append({
                    "target_id": content_target_id,
                    "installation_target_id": target_id,
                    "archive_stem": archive_stem,
                    "source_archive_relative": relative,
                    "source_archive_sha256": extracted["source_archive_sha256"],
                    "source_archive_bytes": extracted["source_archive_bytes"],
                    "source_kind": source_kind,
                    "workspace_archive_root": extracted["workspace"].relative_to(self.project_root).as_posix(),
                    "source_manifest": extracted["manifest"].relative_to(self.project_root).as_posix(),
                    "extraction_status": extracted["status"],
                })
        fingerprint_material = "\n".join(
            f"{row['archive_stem']}:{row['source_archive_sha256']}:{row['source_archive_bytes']}"
            for row in rows
        ).encode("utf-8")
        workspace_fingerprint = hashlib.sha256(fingerprint_material).hexdigest()
        payload = {
            "type": "br_target_workspace_map",
            "format_version": 1,
            "target_id": target_id,
            "content_target_ids": content_target_ids,
            "workspace_fingerprint": workspace_fingerprint,
            "generated_utc": utc_now(),
            "archives": rows,
        }
        path = self.project_root / ".local/build/core/BR_LOCAL_TRANSLATION_TARGET_WORKSPACE_MAP.json"
        atomic_json(path, payload)
        self.report.workspace_source = (
            f"current_baseline_structural_rebase:{workspace_fingerprint[:24]}:"
            + ",".join(sorted(source_kinds))
        )
        return path

    def verify_workspace_freshness(self, target_id: str, game_root: Path, status: dict[str, Any]) -> None:
        # Kept only as a compatibility shim for older callers/tests. The production
        # workflow no longer requires a fixed workspace hash. It extracts the current
        # preserved baseline and structurally rebases canonical records onto it.
        self.installation_route(target_id)


    def find_tool(self, variable: str, executable: str) -> Path:
        candidates: list[Path] = []
        configured = os.environ.get(variable, "").strip()
        if configured:
            candidates.append(Path(configured).expanduser())
        candidates.extend(
            [
                self.project_root / ".local/vendor/gust_tools" / executable,
                Path.home() / "Downloads/gust_tools" / executable,
            ]
        )
        discovered = shutil.which(executable)
        if discovered:
            candidates.append(Path(discovered))
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()
        raise WorkflowError("missing_tool", f"Required tool was not found: {executable}")

    def validate_translation_prerequisites(self) -> None:
        repair = self.project_root / ".local/reports/translation/BR_EBM_LAYOUT_REPAIR_REPORT.json"
        if not repair.is_file():
            raise WorkflowError(
                "translation_database_not_refreshed",
                "Active-English target refresh report is missing. Run 06_repair_translation_database.sh once.",
            )
        data = json.loads(repair.read_text(encoding="utf-8"))
        if data.get("status") != "ok" or data.get("runtime_target_adapter") != "active_english":
            raise WorkflowError("translation_database_not_refreshed", "Active-English target refresh report is not valid")

    def build_loose(self, target_id: str, workspace_map: Path) -> None:
        tool = self.project_root / "Blue_Reflection_Text_Tool/br_text_tool.py"
        lock = self.project_root / "Blue_Reflection_Text_Tool/workstream_lock.sh"
        command: list[str | os.PathLike[str]] = [
            "bash",
            lock,
            self.project_root,
            "translation",
            "--",
            "python3",
            tool,
            "build-loose",
            "--project-root",
            self.project_root,
            "--title-marker",
            "none",
            "--target-workspace-map",
            workspace_map,
        ]
        for content_target_id, _ in self.content_routes(target_id):
            command.extend(["--target", content_target_id])
        self.record_step(
            "build_translation_loose",
            command,
        )
        if target_id == "blue_reflection_quartet":
            audit = self.project_root / "workstreams/translation_tooling/quartet_translation_mapping_audit.py"
            audit_report = self.project_root / ".local/reports/translation/BR_QUARTET_TRANSLATION_MAPPING_AUDIT.json"
            self.record_step(
                "audit_quartet_mapping",
                [
                    "python3",
                    audit,
                    "--project-root",
                    self.project_root,
                    "--report",
                    audit_report,
                    "--verify-loose-build",
                ],
            )

    def repack(self, gust_pak: Path) -> None:
        tool = self.project_root / "Blue_Reflection_Text_Tool/br_text_tool.py"
        lock = self.project_root / "Blue_Reflection_Text_Tool/workstream_lock.sh"
        self.record_step(
            "repack_translation",
            [
                "bash",
                lock,
                self.project_root,
                "translation_tooling",
                "--",
                "python3",
                tool,
                "repack",
                "--project-root",
                self.project_root,
                "--gust-pak",
                gust_pak,
            ],
        )

    def build_marker(self, target_id: str, source_root: Path, modules: list[str], gust_pak: Path) -> None:
        lock = self.project_root / "Blue_Reflection_Text_Tool/workstream_lock.sh"
        base = ["bash", lock, self.project_root, "translation_tooling", "--", "python3"]
        if target_id == "blue_reflection_original":
            command = base + [
                self.project_root / "workstreams/translation_tooling/blue_reflection_title_marker.py",
                "--project-root",
                self.project_root,
                "--original-root",
                source_root,
                "--gust-pak",
                gust_pak,
            ]
            config = os.environ.get("BR1_TITLE_MARKER_CONFIG", "").strip()
            if config:
                command += ["--config", Path(config).expanduser()]
        elif target_id == "second_light_original":
            gust_g1t = self.find_tool("GUST_G1T", "gust_g1t")
            marker = os.environ.get("BR_TITLE_MARKER", "UNBURGER").strip() or "UNBURGER"
            command = base + [
                self.project_root / "workstreams/translation_tooling/second_light_title_marker.py",
                "--project-root",
                self.project_root,
                "--game-root",
                source_root,
                "--gust-pak",
                gust_pak,
                "--gust-g1t",
                gust_g1t,
                "--marker",
                marker,
            ]
        elif target_id == "blue_reflection_quartet":
            gust_g1t = self.find_tool("GUST_G1T", "gust_g1t")
            variant = "combined" if RESTORATION_MODULE in modules else "unburger"
            command = base + [
                self.project_root / "workstreams/translation_tooling/quartet_title_marker.py",
                "--project-root",
                self.project_root,
                "--quartet-root",
                source_root,
                "--gust-pak",
                gust_pak,
                "--gust-g1t",
                gust_g1t,
                "--variant",
                variant,
            ]
        else:
            raise WorkflowError("unsupported_target", f"Unsupported target: {target_id}")
        self.record_step("build_title_marker", command)

    def maybe_build_composition(self, target_id: str, game_root: Path, modules: list[str], gust_pak: Path) -> None:
        needs_composition = (
            target_id == "blue_reflection_quartet"
            and (
                RESTORATION_MODULE in modules
                or (DEFAULT_TRANSLATION_MODULE in modules and LEGACY_DLC_MODULE in modules)
            )
        )
        if not needs_composition:
            return
        selected = ",".join(modules)
        preview_path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_COMPOSITION_PREFLIGHT.json"
        self.report.composition_preview_report = str(preview_path)
        self.record_step(
            "quartet_composition_preview",
            [
                self.patcher,
                "quartet-composition-preview",
                "--game-dir",
                game_root,
                "--project-root",
                self.project_root,
                "--modules",
                selected,
                "--json",
                preview_path,
            ],
        )
        preview = json.loads(preview_path.read_text(encoding="utf-8"))
        if preview.get("status") != "ready_for_composition_build":
            details = []
            for archive in preview.get("archives", []):
                if archive.get("status") not in {"not_selected", "ready_for_member_overlay", "ready_for_passthrough"}:
                    details.append(f"{archive.get('archive_relative_path')}: {archive.get('status')}")
            raise WorkflowError(
                "composition_not_ready",
                f"Quartet shared composition is not ready for {selected}: {preview.get('status')}",
                details,
            )
        build_path = self.report_dir / "BR_QUARTET_COMPOSITION_BUILD_REPORT.json"
        self.report.composition_build_report = str(build_path)
        self.record_step(
            "quartet_composition_build",
            [
                self.patcher,
                "quartet-composition-build",
                "--game-dir",
                game_root,
                "--project-root",
                self.project_root,
                "--modules",
                selected,
                "--gust-pak",
                gust_pak,
                "--timeout",
                "10m",
                "--json",
                build_path,
            ],
        )

    def payload_preview(self, game_root: Path, modules: list[str]) -> dict[str, Any]:
        path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_PAYLOAD_PREVIEW.json"
        self.report.payload_preview_report = str(path)
        self.record_step(
            "payload_preview",
            [
                self.patcher,
                "payload-preview",
                "--game-dir",
                game_root,
                "--modules",
                ",".join(modules),
                "--no-prompt",
                "--project-root",
                self.project_root,
                "--json",
                path,
            ],
        )
        preview = json.loads(path.read_text(encoding="utf-8"))
        if preview.get("commit_enabled") is not False:
            raise WorkflowError("preview_commit_enabled", "Payload preview unexpectedly enabled commit")
        if preview.get("status") != "ready" or len(preview.get("targets", [])) != 1:
            details: list[str] = []
            for target in preview.get("targets", []):
                for module in target.get("modules", []):
                    if not module.get("ready"):
                        reason = module.get("reason") or "module is not ready"
                        details.append(f"{module.get('module_id')}: {reason}")
                        for artifact in module.get("artifacts", []):
                            if not artifact.get("transaction_ready"):
                                details.append(
                                    f"{artifact.get('relative_path')}: {artifact.get('error') or artifact.get('status')}"
                                )
            raise WorkflowError(
                "payload_not_ready",
                f"Payload preview is not fully ready: {preview.get('status')}",
                details,
            )
        return preview

    def prepare(self, game_root: Path, modules: list[str]) -> dict[str, Any]:
        path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_TRANSACTION_PREPARE.json"
        self.report.transaction_prepare_report = str(path)
        self.record_step(
            "transaction_prepare",
            [
                self.patcher,
                "transaction-prepare",
                "--game-dir",
                game_root,
                "--modules",
                ",".join(modules),
                "--no-prompt",
                "--project-root",
                self.project_root,
                "--json",
                path,
            ],
        )
        prepared = json.loads(path.read_text(encoding="utf-8"))
        if prepared.get("status") not in {"prepared", "no_changes"}:
            raise WorkflowError("transaction_not_prepared", f"Unexpected transaction status: {prepared.get('status')}")
        self.report.transaction_journal = prepared.get("journal_path", "")
        self.report.baseline_manifest = prepared.get("baseline_manifest_path", "")
        return prepared

    def commit(self, journal_path: str) -> dict[str, Any]:
        if not journal_path:
            raise WorkflowError("missing_transaction_journal", "Prepared transaction did not publish a journal path")
        path = self.report_dir / "BR_LOCAL_TRANSLATION_WORKFLOW_TRANSACTION_COMMIT.json"
        self.report.transaction_commit_report = str(path)
        self.record_step(
            "transaction_commit",
            [
                self.patcher,
                "transaction-commit",
                "--journal",
                journal_path,
                "--yes",
                "--json",
                path,
            ],
        )
        committed = json.loads(path.read_text(encoding="utf-8"))
        if committed.get("status") not in {"installed", "already_installed"}:
            raise WorkflowError("transaction_not_installed", f"Unexpected commit status: {committed.get('status')}")
        return committed

    def run(
        self,
        *,
        game_root: Path,
        modules: list[str],
        preview_only: bool,
        install: bool = False,
        force_rebuild_patcher: bool = False,
    ) -> WorkflowReport:
        if preview_only and install:
            raise WorkflowError("conflicting_mode", "--preview-only and --install cannot be used together")
        self.report.preview_only = preview_only
        self.report.install_requested = install
        try:
            self.ensure_project()
            self.ensure_patcher(force=force_rebuild_patcher)
            target = self.detect_target(game_root.resolve())
            game_root = Path(target["root"])
            modules = self.validate_modules(target["target_id"], modules)
            status = self.installation_status(game_root)
            self.validate_translation_prerequisites()
            gust_pak = self.find_tool("GUST_PAK", "gust_pak")
            workspace_map = self.prepare_target_workspace(
                target["target_id"], game_root, status, gust_pak
            )
            self.build_loose(target["target_id"], workspace_map)
            self.repack(gust_pak)
            marker_source_root = self.marker_source_root(target["target_id"], game_root, status)
            self.build_marker(target["target_id"], marker_source_root, modules, gust_pak)
            self.maybe_build_composition(target["target_id"], game_root, modules, gust_pak)
            self.payload_preview(game_root, modules)
            self.report.commit_enabled = False
            if preview_only:
                self.report.status = "ready_preview_only"
            else:
                prepared = self.prepare(game_root, modules)
                self.report.commit_enabled = bool(prepared.get("commit_enabled", False) and prepared.get("status") == "prepared")
                if prepared.get("status") == "prepared" and install:
                    committed = self.commit(prepared.get("journal_path", ""))
                    self.report.status = "installed"
                    self.report.game_files_modified = committed.get("status") == "installed"
                    self.report.commit_enabled = False
                else:
                    self.report.status = "prepared" if prepared.get("status") == "prepared" else "no_changes"
        except WorkflowError as error:
            self.report.status = error.code
            self.report.errors.append(error.message)
            self.report.errors.extend(item for item in error.details if item)
            raise
        finally:
            self.report.generated_utc = utc_now()
        return self.report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build current Translation payloads for one detected PC installation, add the correct title marker, "
            "verify the payload set, prepare a transaction and optionally install it with explicit confirmation."
        )
    )
    parser.add_argument(
        "--game-dir",
        default=os.getcwd(),
        help="game directory; defaults to the current directory",
    )
    parser.add_argument(
        "--modules",
        default="",
        help="comma-separated modules; default is the Translation module registered for the detected target",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="stop after verified payload preview instead of transaction preparation",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="after preparation, atomically install the verified transaction into the game",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm game-file modification; required together with --install",
    )
    parser.add_argument(
        "--rebuild-patcher",
        action="store_true",
        help="force rebuilding the local Linux patcher binary",
    )
    parser.add_argument(
        "--json",
        default="",
        help="workflow report path; default: .local/reports/core/BR_LOCAL_TRANSLATION_WORKFLOW_REPORT.json",
    )
    return parser


def print_summary(report: WorkflowReport, report_path: Path) -> None:
    print("\nLocal Translation workflow")
    print(f"Status: {report.status}")
    if report.display_name:
        print(f"Target: {report.display_name}")
    if report.game_root:
        print(f"Game:   {report.game_root}")
    if report.selected_modules:
        print(f"Modules: {', '.join(report.selected_modules)}")
    if report.status == "installed":
        print(f"Journal: {report.transaction_journal}")
        print(f"Baseline: {report.baseline_manifest}")
        print("Installed and verified: yes")
    elif report.status == "prepared":
        print(f"Journal: {report.transaction_journal}")
        print(f"Baseline: {report.baseline_manifest}")
        print("Ready to install later: yes")
    elif report.status == "ready_preview_only":
        print("Verified payload preview: ready")
        print("Transaction prepared: no (--preview-only)")
    elif report.status == "no_changes":
        print("Selected payloads already match the installation; no transaction was needed.")
    if report.errors:
        print("Problems:")
        for item in report.errors:
            print(f"  - {item}")
    print(f"Game files modified: {'yes' if report.game_files_modified else 'no'}")
    print(f"Explicit commit available: {'yes' if report.commit_enabled else 'no'}")
    print(f"Workflow report: {report_path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.install and not args.yes:
        parser.error("--install requires --yes because game files will be modified")
    if args.yes and not args.install:
        parser.error("--yes is only valid together with --install")
    project_root = Path(__file__).resolve().parents[2]
    workflow = LocalTranslationWorkflow(project_root)
    report_path = (
        Path(args.json).expanduser().resolve()
        if args.json
        else project_root / ".local/reports/core/BR_LOCAL_TRANSLATION_WORKFLOW_REPORT.json"
    )
    try:
        report = workflow.run(
            game_root=Path(args.game_dir).expanduser(),
            modules=normalize_modules(args.modules),
            preview_only=args.preview_only,
            install=args.install,
            force_rebuild_patcher=args.rebuild_patcher,
        )
        code = 0
    except WorkflowError:
        report = workflow.report
        code = 1
    atomic_json(report_path, asdict(report))
    print_summary(report, report_path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
