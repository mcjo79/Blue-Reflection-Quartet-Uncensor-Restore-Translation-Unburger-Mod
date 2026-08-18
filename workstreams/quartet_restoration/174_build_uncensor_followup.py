#!/usr/bin/env python3
"""Build and verify the first strict Quartet UNCENSOR profile.

This stage is read-only with respect to the installed game.  It extracts the
currently installed PACK11, applies the two checksum-gated te01_290 selector
edits, repacks, re-extracts, and proves that every other archive member is
unchanged.  The result is registered as an *inactive* local core profile and is
also placed in a self-contained runtime-test ZIP with guarded START/ROLLBACK
scripts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


TOOL_VERSION = "0.2.02"
STAGE = 174
PROFILE_ID = "uncensor_te01_290_pc04_udw_restore"
TARGET_ARCHIVE = "Data/PACK11.PAK"
TARGET_MEMBER = "event/b1/event_jp/te01/event_te01_290.ebd"
BASELINE_ARCHIVE_SHA256 = "bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306"
BASELINE_ARCHIVE_SIZE = 13_372_318
BASELINE_MEMBER_SHA256 = "aae752d1a63472a293136fded1c330f107cee63c0c77c2d5947648770fa8043e"
BASELINE_MEMBER_SIZE = 4_569
EDITS = ((0xE32, bytes.fromhex("38030000"), bytes.fromhex("0b020000")),
         (0xEA6, bytes.fromhex("38030000"), bytes.fromhex("0b020000")))
BUILD_REL = Path(".local/build/quartet_restoration/uncensor_te01_290_pc04_udw_restore")
REPORT_REL = Path(".local/reports/quartet_restoration/BR_QUARTET_UNCENSOR_FOLLOWUP_20260811")
MANIFEST_REL = Path(".local/build/quartet_restoration/core_profiles/uncensor_te01_290_pc04_udw_restore.json")
ZIP_NAME = "BR_QUARTET_UNCENSOR_TE01_290_PC04_UDW_RESTORE_READY.zip"


class BuildError(RuntimeError):
    pass


def require(value: bool, message: str) -> None:
    if not value:
        raise BuildError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def patch_member(data: bytes) -> bytes:
    require(len(data) == BASELINE_MEMBER_SIZE,
            f"member size mismatch: got {len(data)}, expected {BASELINE_MEMBER_SIZE}")
    require(hashlib.sha256(data).hexdigest() == BASELINE_MEMBER_SHA256,
            "member SHA-256 mismatch")
    output = bytearray(data)
    for offset, before, after in EDITS:
        actual = bytes(output[offset:offset + len(before)])
        require(actual == before,
                f"precondition mismatch at 0x{offset:X}: got {actual.hex()}, expected {before.hex()}")
        output[offset:offset + len(before)] = after
    changed = [index for index, pair in enumerate(zip(data, output)) if pair[0] != pair[1]]
    require(changed == [0xE32, 0xE33, 0xEA6, 0xEA7],
            f"unexpected changed byte offsets: {changed}")
    require(len(output) == len(data), "member size changed")
    return bytes(output)


def load_restoration_module(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py"
    spec = importlib.util.spec_from_file_location("br_restoration_stage174", path)
    require(spec is not None and spec.loader is not None, f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def safe_replace_generated(path: Path) -> None:
    if not path.exists():
        return
    marker = path / "BUILD.json"
    require(marker.is_file(), f"refusing to replace unmarked build directory: {path}")
    record = json.loads(marker.read_text(encoding="utf-8"))
    require(record.get("type") == "br_quartet_uncensor_te01_290_build",
            f"refusing to replace build with unknown marker: {marker}")
    shutil.rmtree(path)


def member_key(name: str) -> str:
    return name.replace("\\", "/").lstrip("/").casefold()


def write_runtime_scripts(package: Path) -> None:
    start = r'''#!/usr/bin/env bash
set -Eeuo pipefail
PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GAME_ROOT="${1:-${BR1_QUARTET_ROOT:-}}"
if [[ -z "$GAME_ROOT" ]]; then
  printf 'Usage: %s /path/to/BLUE REFLECTION Quartet\n' "$0" >&2
  exit 2
fi
exec "$PACKAGE_ROOT/bin/brpatcher" quartet-profile-activate \
  --project-root "$PACKAGE_ROOT" --game-root "$GAME_ROOT" \
  uncensor_te01_290_pc04_udw_restore
'''
    rollback = r'''#!/usr/bin/env bash
set -Eeuo pipefail
PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GAME_ROOT="${1:-${BR1_QUARTET_ROOT:-}}"
if [[ -z "$GAME_ROOT" ]]; then
  printf 'Usage: %s /path/to/BLUE REFLECTION Quartet\n' "$0" >&2
  exit 2
fi
exec "$PACKAGE_ROOT/bin/brpatcher" quartet-profile-rollback \
  --project-root "$PACKAGE_ROOT" --game-root "$GAME_ROOT"
'''
    status = r'''#!/usr/bin/env bash
set -Eeuo pipefail
PACKAGE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GAME_ROOT="${1:-${BR1_QUARTET_ROOT:-}}"
if [[ -z "$GAME_ROOT" ]]; then
  printf 'Usage: %s /path/to/BLUE REFLECTION Quartet\n' "$0" >&2
  exit 2
fi
exec "$PACKAGE_ROOT/bin/brpatcher" quartet-profile-status \
  --project-root "$PACKAGE_ROOT" --game-root "$GAME_ROOT"
'''
    atomic_text(package / "START.sh", start, 0o755)
    atomic_text(package / "ROLLBACK.sh", rollback, 0o755)
    atomic_text(package / "STATUS.sh", status, 0o755)


def locker_candidates() -> list[dict[str, Any]]:
    return [
        {"event_id": "te01_240", "cohort": "chapter8_training", "scene": "acting rehearsal / underwear training setup", "access": "Chapter 8 Free Time; home; Prepare for tomorrow's training; fixed slot 1", "original_quartet_delta": "22 UDW selectors -> UDW2", "confidence": "high", "ready": False, "reason": "large 22-selector surface"},
        {"event_id": "te01_250", "cohort": "chapter8_training", "scene": "expanded cast rehearsal", "access": "same fixed training sequence; slot 2", "original_quartet_delta": "changed EBD; no isolated coverage selector", "confidence": "low", "ready": False, "reason": "no minimal censorship field isolated"},
        {"event_id": "te01_260", "cohort": "chapter8_training", "scene": "Kei/Rika group rehearsal / underwear training setup", "access": "same fixed training sequence; slot 3", "original_quartet_delta": "33 of 34 UDW selectors -> UDW2", "confidence": "high", "ready": False, "reason": "large 33-selector surface"},
        {"event_id": "te01_270", "cohort": "chapter8_training", "scene": "costume measurements; actors undress", "access": "same fixed training sequence; slot 4", "original_quartet_delta": "broad non-count-conserving EBD delta", "confidence": "medium", "ready": False, "reason": "direct cue but no minimal selector field isolated"},
        {"event_id": "te01_280", "cohort": "chapter8_training", "scene": "music/staging rehearsal", "access": "same fixed training sequence; slot 5", "original_quartet_delta": "changed EBD; no isolated coverage selector", "confidence": "low", "ready": False, "reason": "no minimal censorship field isolated"},
        {"event_id": "te01_290", "cohort": "chapter8_training", "scene": "acting rehearsal / underwear training setup", "access": "same fixed training sequence; slot 6", "original_quartet_delta": "two PC04 UDW selectors 523 -> UDW2 selector 824", "confidence": "high", "ready": True, "reason": "two exact retained-target selector repoints"},
        {"event_id": "te01_300", "cohort": "chapter8_training", "scene": "short repeat/fallback practice", "access": "after the fixed training sequence", "original_quartet_delta": "two small structural deltas", "confidence": "low", "ready": False, "reason": "no coverage selector delta"},
        {"event_id": "te02_150", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "earlier Free Time; home; Prepare for tomorrow; Stretch", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no direct cue or minimal field"},
        {"event_id": "te02_160", "cohort": "pool_shower_prep", "scene": "Sanae after shower", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "two Quartet-only ITEM_BATHTOWEL_01 bindings", "confidence": "high", "ready": False, "reason": "paired spawn/bind record deletion not formally decoded"},
        {"event_id": "te02_170", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "te02_180", "cohort": "pool_shower_prep", "scene": "post-exercise shower", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "broad structural delta", "confidence": "medium", "ready": False, "reason": "camera/presentation semantics unresolved"},
        {"event_id": "te02_190", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "te02_200", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "te02_210", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "earlier fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "te02_220", "cohort": "pool_shower_prep", "scene": "Chihiro after shower", "access": "Chapter 5-era fixed Stretch sequence", "original_quartet_delta": "two Quartet-only ITEM_BATHTOWEL_01 bindings", "confidence": "high", "ready": False, "reason": "paired spawn/bind record deletion not formally decoded"},
        {"event_id": "te02_230", "cohort": "pool_shower_prep", "scene": "Shihori shower", "access": "Chapter 5-era fixed Stretch sequence", "original_quartet_delta": "source-only bounded record missing in Quartet", "confidence": "medium", "ready": False, "reason": "record semantics unresolved"},
        {"event_id": "te02_240", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "te02_250", "cohort": "pool_shower_prep", "scene": "Sarasa shower", "access": "fixed Stretch sequence", "original_quartet_delta": "broad structural delta", "confidence": "medium", "ready": False, "reason": "no minimal coverage field"},
        {"event_id": "te02_260", "cohort": "pool_shower_prep", "scene": "pool scene", "access": "fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "medium", "ready": False, "reason": "pool cue only"},
        {"event_id": "te02_270", "cohort": "pool_shower_prep", "scene": "route neighbor", "access": "fixed Stretch sequence", "original_quartet_delta": "changed EBD", "confidence": "low", "ready": False, "reason": "no minimal field"},
        {"event_id": "em01_100", "cohort": "friend_event", "scene": "post-sports bathroom/pool sequence", "access": "one-time Kei friendship event; exact trigger record unresolved", "original_quartet_delta": "six added bindings for three towel/swimsuit props", "confidence": "high", "ready": False, "reason": "three independent paired records and one-time route"},
        {"event_id": "fe08_170", "cohort": "friend_event", "scene": "Kaori cosplay changing room", "access": "one-time Kaori bond chain", "original_quartet_delta": "small changed EBD; no isolated coverage selector", "confidence": "medium", "ready": False, "reason": "location is explicit, censorship causal unit is not"},
        {"event_id": "fe13_050", "cohort": "friend_event", "scene": "Shihori pool / underwear swap / changing", "access": "Chapter 8 Shihori max-bond event; talk to Shihori", "original_quartet_delta": "15 UDW2/UDW3 selector hits across three actors", "confidence": "medium-high", "ready": False, "reason": "compound non-count-conserving event"},
        {"event_id": "fe13_090", "cohort": "friend_event", "scene": "continuation after locker-room change", "access": "automatic continuation of Shihori max-bond event", "original_quartet_delta": "three residual structural regions; no exact selector closure", "confidence": "medium", "ready": False, "reason": "prior whole-splice profile is not censorship-proven"},
    ]


def testability_matrix() -> str:
    return """# Combined player-facing testability matrix

| Target | Player route | Repeatability / save gate | Visible discriminator | Implementation state |
|---|---|---|---|---|
| `te01_240` | Chapter 8 Free Time → go home → Prepare for tomorrow's training; fixed slot 1 | One-time fixed slot; needs a Chapter 8 save before slot 1 | many actors use Original-equivalent UDW instead of UDW2 | static candidate only; too broad |
| `te01_260` | same sequence; fixed slot 3 | one-time; needs sequence before slot 3 | group UDW/UDW2 change | static candidate only; too broad |
| `te01_290` | same sequence; fixed slot 6 | one-time; use a Chapter 8 save before the sixth training scene | PC04 outfit changes in two shots; timing/camera unchanged | **ready inactive ZIP; selected** |
| `te02_160` | earlier Free Time → home → Prepare for tomorrow → Stretch | one-time fixed shower sequence; usually exhausted in a late save | Quartet-only towel should disappear | strong static lead, record deletion not decoded |
| `te02_180` | same Stretch route | one-time earlier slot | post-exercise shower presentation | unresolved broad delta |
| `te02_220` | same Stretch route during the Chihiro-era sequence | one-time earlier slot | Quartet-only towel should disappear | strong static lead, record deletion not decoded |
| `te02_230` | same Stretch route during Shihori-era sequence | one-time earlier slot | shower presentation/cut | record semantics unresolved |
| `te02_250` | same Stretch route during Sarasa-era sequence | one-time earlier slot | shower presentation | broad delta only |
| `em01_100` | advance the Kei friendship event chain | one-time and exact trigger mapping unresolved | three towel/swimsuit props | not ready |
| `fe13_050` / `fe13_090` | Chapter 8; max Shihori's bond; talk to Shihori; locker scene leads into the Common and then continuation | one-time; requires a pre-max-event save | underwear/swimsuit/changing presentation | visible, but compound and not minimal |
| `fe08_170` | advance Kaori's bond chain to the cosplay event | one-time; requires pre-event save | cosplay changing-room sequence | access known, causal patch unknown |
| School locker/changing-room map | select the school map location when unlocked | repeatable free-roam location, but no event replay control was found | environment only | useful navigation control, not an uncensor test |
| `ce01_040` wet-school scene | rainy day front-gate `...` event; alternatively use the already established wet-school capture save | weather/event is save-dependent; no replay menu | accepted main-PBB draw state / fragment shader | one Original-vs-Quartet read-only collector supplied |

The game exposes Gallery artwork and Freespace media, but the audited UI/localized strings do not expose an event/cutscene replay selector.  Free-roam access to the locker map therefore does not make one-time EBD scenes replayable.
"""


def locker_report() -> str:
    return """# Locker/changing-room accessibility audit

## Result

`te01_290` is the smallest strict selector restoration and the best late-game test candidate.  It belongs to the six-scene Chapter 8 **Prepare for tomorrow's training** sequence.  The guide describes that sequence as showing the girls in underwear; the local message/EBD ordering maps `te01_240`, `250`, `260`, `270`, `280`, and `290` to the six fixed scenes, followed by the short `te01_300` fallback.  A Chapter 8 save that has not consumed slot 6 can reach it by going home and choosing that preparation option until the sixth fixed scene.

This is a save gate, not a replay feature.  If the save has already consumed the fixed sequence, the event cannot be selected from the school locker room or Gallery.  No native event/cutscene replay entry was found in the audited help/menu/Freespace strings.  The school locker/changing room is a repeatable map location, but it does not expose arbitrary EBD playback.

## Other plausible cohorts

- `te02_150`–`te02_270` form the earlier pool/shower preparation cohort.  The player route is home → Prepare for tomorrow → Stretch during the relevant Free Time chapter.  These are fixed one-time slots; `te02_160` and `te02_220` have the clearest Quartet-only towel bindings, but safely removing their paired create/bind records still requires opcode closure.
- `fe13_050`/`fe13_090` are the explicit Shihori locker-room max-bond sequence in Chapter 8.  They are highly visible but compound, one-time, and require a pre-event Shihori save.
- `fe08_170` explicitly moves the cast to the changing room for Kaori's cosplay outfits.  Its location/access is clear; no minimal censorship-causing field is isolated.
- `em01_100` adds three paired Quartet-only towel/swimsuit item bindings.  Its exact one-time friendship trigger remains unresolved in the EPD container, so it is not the immediate player-facing target.

## Selection rationale

The selected `te01_290` profile changes only two already-understood selector dwords, uses a retained Quartet-native `PC04_UDW` table entry and asset, preserves the target event layout, and has a documented Chapter 8 route.  The expected visual test is narrow: PC04 changes from UDW2 to UDW in the two affected shots; every other actor, animation, camera, message, and timing remains identical.

The machine-readable census is `LOCKER_ROOM_CANDIDATES.json`; the combined route/save/visibility matrix is `TESTABILITY_MATRIX.md`.
"""


def wet_report() -> str:
    return """# Wet-opacity last-mile closure

The static branch remains closed at one binary observation.  The accepted main-PBB draw must be compared between Original and Quartet for the bound blend/depth/raster state and fragment/pixel-shader identity.

- If the normalized blend/depth/raster state differs, the surviving cause is pass-local state construction from the version-specific G1S path.
- If those states are equal while fragment/pixel-shader identity differs, the surviving cause is the PBB shader alpha/output semantic delta.

No additional A/B patch is justified.  `wet_main_pbb_collector.py` is a read-only qrenderdoc UI script for exactly one user-selected accepted draw.  Run it once on an Original RDC and once on a Quartet RDC.  It writes only the selected event/action identity, normalized fixed-function state, and fragment/pixel-shader identity/disassembly digest; it does not launch a game, write process memory, or edit game files.
"""


def build(project_root: Path, game_root: Path, gust_pak: Path) -> tuple[Path, dict[str, Any]]:
    installed = game_root / TARGET_ARCHIVE
    require(installed.is_file(), f"installed archive missing: {installed}")
    require(installed.stat().st_size == BASELINE_ARCHIVE_SIZE, "installed PACK11 size mismatch")
    require(sha256_file(installed) == BASELINE_ARCHIVE_SHA256, "installed PACK11 SHA-256 mismatch")
    module = load_restoration_module(project_root)

    build_root = project_root / BUILD_REL
    report_root = project_root / REPORT_REL
    safe_replace_generated(build_root)
    if report_root.exists():
        marker = report_root / "SUMMARY.json"
        require(marker.is_file(), f"refusing to replace unmarked report directory: {report_root}")
        shutil.rmtree(report_root)
    build_root.mkdir(parents=True)
    atomic_json(build_root / "BUILD.json", {"type": "br_quartet_uncensor_te01_290_build", "stage": STAGE, "tool_version": TOOL_VERSION})

    with tempfile.TemporaryDirectory(prefix="br-stage174-", dir=build_root) as temporary_name:
        temporary = Path(temporary_name)
        extracted = temporary / "baseline"
        manifest_path, manifest = module._extract_pak_for_repack_test(
            archive=installed, destination=extracted, gust_pak=gust_pak,
            timeout_seconds=600, log_name="extract.log")
        before_members_raw = module._manifest_member_hashes(extracted, manifest)
        before_members = {member_key(row["name"]): row for row in before_members_raw.values()}
        target = before_members.get(TARGET_MEMBER.casefold())
        require(target is not None, f"target member missing: {TARGET_MEMBER}")
        source_path = extracted / Path(target["name"])
        source_data = source_path.read_bytes()
        candidate_data = patch_member(source_data)
        candidate_sha = hashlib.sha256(candidate_data).hexdigest()

        candidate_path = build_root / "candidate" / TARGET_MEMBER
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_bytes(candidate_data)

        stage_dir = temporary / "stage"
        module._copy_repack_input_tree(extracted, stage_dir)
        staged_target = stage_dir / Path(target["name"])
        staged_target.write_bytes(candidate_data)
        stage_manifest = stage_dir / manifest_path.name
        output_name = str(manifest["safe_output_name"])
        module._run_gust_pak(gust_pak=gust_pak, argument_name=stage_manifest.name,
                             cwd=stage_dir, log_path=build_root / "repack.log", timeout_seconds=600)
        repacked = stage_dir / output_name
        require(repacked.is_file(), "gust_pak did not produce PACK11")

        profile_archive = build_root / "profile" / "Data" / "PACK11.PAK"
        profile_archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repacked, profile_archive)

        verify_dir = temporary / "verify"
        _, verify_manifest = module._extract_pak_for_repack_test(
            archive=profile_archive, destination=verify_dir, gust_pak=gust_pak,
            timeout_seconds=600, log_name="verify.log")
        after_members_raw = module._manifest_member_hashes(verify_dir, verify_manifest)
        after_members = {member_key(row["name"]): row for row in after_members_raw.values()}
        require(set(before_members) == set(after_members), "archive member name set changed")
        changed = [key for key in sorted(before_members) if before_members[key]["sha256"] != after_members[key]["sha256"]]
        require(changed == [TARGET_MEMBER.casefold()], f"unexpected changed members: {changed}")
        require(after_members[TARGET_MEMBER.casefold()]["sha256"] == candidate_sha, "repacked member digest mismatch")
        require(module._gust_manifest_semantic_signature(manifest) == module._gust_manifest_semantic_signature(verify_manifest),
                "stable gust manifest semantics changed")

    archive_sha = sha256_file(profile_archive)
    archive_size = profile_archive.stat().st_size
    local_profile_path = (BUILD_REL / "profile" / "Data" / "PACK11.PAK").as_posix()
    core_manifest = {
        "schema_version": 1, "profile_id": PROFILE_ID,
        "target_relative_path": TARGET_ARCHIVE,
        "baseline_sha256": BASELINE_ARCHIVE_SHA256, "baseline_size": BASELINE_ARCHIVE_SIZE,
        "profile_sha256": archive_sha, "profile_size": archive_size,
        "local_profile_path": local_profile_path,
        "changed_member_count": 1, "changed_members": [TARGET_MEMBER],
        "runtime_validated": False, "workstream_id": "quartet_restoration",
        "workstream_version": TOOL_VERSION,
    }
    atomic_json(project_root / MANIFEST_REL, core_manifest)

    package = build_root / "runtime_package"
    (package / "bin").mkdir(parents=True)
    subprocess.run(["go", "build", "-trimpath", "-o", str(package / "bin/brpatcher"), "./cmd/brpatcher"],
                   cwd=project_root / "Blue_Reflection_Patcher", check=True)
    package_profile = package / local_profile_path
    package_profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile_archive, package_profile)
    package_manifest = package / MANIFEST_REL
    package_manifest.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(package_manifest, core_manifest)
    write_runtime_scripts(package)
    atomic_text(package / "README.md", """# te01_290 PC04 UDW restoration runtime test

This package is inactive until `START.sh` is run. Close the game first.

1. `./STATUS.sh \"/path/to/BLUE REFLECTION Quartet\"`
2. `./START.sh \"/path/to/BLUE REFLECTION Quartet\"`
3. Start the game yourself and use a Chapter 8 save before the sixth **Prepare for tomorrow's training** scene. Repeat that home option until `te01_290` plays.
4. Verify only PC04's outfit changes in the two affected shots. Exit the game.
5. `./ROLLBACK.sh \"/path/to/BLUE REFLECTION Quartet\"`

Activation is checksum-gated to the exact clean PACK11. Rollback is refused if the active archive drifts. The transaction layer keeps a same-filesystem backup. Do not combine this isolated PACK11 profile with another open local-profile transaction.
""")

    report_root.mkdir(parents=True)
    candidates = locker_candidates()
    atomic_json(report_root / "LOCKER_ROOM_CANDIDATES.json", {
        "schema_version": 1, "generated_stage": STAGE, "selected_candidate": PROFILE_ID,
        "native_event_replay_found": False, "candidates": candidates,
    })
    atomic_text(report_root / "LOCKER_ROOM_AUDIT.md", locker_report())
    atomic_text(report_root / "TESTABILITY_MATRIX.md", testability_matrix())
    atomic_text(report_root / "WET_OPACITY_LAST_MILE.md", wet_report())

    collector_source = project_root / "workstreams/quartet_restoration/174_wet_main_pbb_collector.py"
    require(collector_source.is_file(), f"missing wet collector: {collector_source}")
    shutil.copy2(collector_source, report_root / "wet_main_pbb_collector.py")
    summary = {
        "type": "br_quartet_uncensor_followup_summary", "schema_version": 1,
        "stage": STAGE, "tool_version": TOOL_VERSION, "status": "ready_inactive_runtime_test",
        "profile_id": PROFILE_ID, "target_archive": TARGET_ARCHIVE, "target_member": TARGET_MEMBER,
        "baseline_archive_sha256": BASELINE_ARCHIVE_SHA256, "baseline_archive_size": BASELINE_ARCHIVE_SIZE,
        "baseline_member_sha256": BASELINE_MEMBER_SHA256, "baseline_member_size": BASELINE_MEMBER_SIZE,
        "candidate_member_sha256": hashlib.sha256(patch_member((project_root / "titles/blue_reflection/workspace/quartet/archives/PACK11" / TARGET_MEMBER).read_bytes())).hexdigest(),
        "profile_archive_sha256": archive_sha, "profile_archive_size": archive_size,
        "member_count": len(before_members), "unchanged_member_count_verified": len(before_members) - 1,
        "changed_members": [TARGET_MEMBER], "changed_byte_offsets": ["0xE32", "0xE33", "0xEA6", "0xEA7"],
        "runtime_validated": False, "profile_activated": False, "installed_game_modified": False,
        "production_write_performed": False, "executable_edited": False,
        "selected_access_route": "Chapter 8 Free Time -> home -> Prepare for tomorrow's training -> fixed scene 6",
        "save_gate": "requires a Chapter 8 save before the sixth fixed training scene",
        "wet_discriminator": "accepted main-PBB draw fixed-function state plus fragment/pixel-shader identity",
    }
    atomic_json(report_root / "SUMMARY.json", summary)
    shutil.copy2(project_root / MANIFEST_REL, report_root / "PROFILE_MANIFEST.json")
    atomic_text(report_root / "PATCH_RECIPE.json", json.dumps({
        "profile_id": PROFILE_ID, "target_archive": TARGET_ARCHIVE, "target_member": TARGET_MEMBER,
        "expected_member_size": BASELINE_MEMBER_SIZE, "expected_member_sha256": BASELINE_MEMBER_SHA256,
        "edits": [{"offset_hex": f"0x{o:X}", "expected_before_hex": b.hex(), "replacement_hex": a.hex()} for o, b, a in EDITS],
    }, indent=2, sort_keys=True) + "\n")

    for source in (report_root / "LOCKER_ROOM_AUDIT.md", report_root / "LOCKER_ROOM_CANDIDATES.json",
                   report_root / "TESTABILITY_MATRIX.md", report_root / "WET_OPACITY_LAST_MILE.md",
                   report_root / "wet_main_pbb_collector.py", report_root / "SUMMARY.json",
                   report_root / "PROFILE_MANIFEST.json", report_root / "PATCH_RECIPE.json"):
        destination = package / "reports" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    zip_path = project_root / ".local/reports/quartet_restoration" / ZIP_NAME
    temporary_zip = zip_path.with_name(zip_path.name + ".tmp")
    temporary_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package).as_posix())
    os.replace(temporary_zip, zip_path)
    zip_sha = sha256_file(zip_path)
    atomic_text(zip_path.with_suffix(zip_path.suffix + ".sha256"), f"{zip_sha}  {zip_path.name}\n")
    summary["runtime_zip"] = zip_path.name
    summary["runtime_zip_sha256"] = zip_sha
    atomic_json(report_root / "SUMMARY.json", summary)
    return zip_path, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[2])
    parser.add_argument("--game-root", required=True)
    parser.add_argument("--gust-pak", default=None)
    args = parser.parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    game_root = Path(args.game_root).expanduser().resolve()
    gust_pak = Path(args.gust_pak).expanduser().resolve() if args.gust_pak else project_root / ".local/vendor/gust_tools/gust_pak"
    zip_path, summary = build(project_root, game_root, gust_pak)
    print(f"Ready inactive profile: {PROFILE_ID}")
    print(f"ZIP: {zip_path}")
    print(f"SHA-256: {summary['runtime_zip_sha256']}")
    print("Installed game files were not modified; no game was launched.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BuildError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
