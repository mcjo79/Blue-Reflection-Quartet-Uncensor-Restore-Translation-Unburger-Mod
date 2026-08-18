#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUILD_RELEASE = PROJECT_ROOT / "BUILD_RELEASE.sh"


def extract_shell_function(text: str, name: str) -> str:
    marker = f"  {name}() {{\n"
    start = text.index(marker)
    i = start + len(marker)
    depth = 1
    in_single = False
    in_double = False
    escaped = False
    while i < len(text):
        ch = text[i]
        if escaped:
            escaped = False
            i += 1
            continue
        if ch == "\\" and not in_single:
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1].lstrip()
        i += 1
    raise ValueError(f"unterminated shell function: {name}")


class ReleaseAssetSidecarRepairTest(unittest.TestCase):
    def test_auto_candidate_repairs_malformed_sidecar_without_stdout_contamination(self):
        source = BUILD_RELEASE.read_text()
        fn = extract_shell_function(source, "verify_assets_bundle")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            patcher = root / "patcher"
            bindir = root / "bin"
            work.mkdir(); patcher.mkdir(); bindir.mkdir()

            bundle = root / "UNBURGER_DLC_ASSETS_v3.unburger-assets"
            bundle.write_bytes(b"synthetic encrypted bundle bytes for sidecar regression\n")
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            sidecar = Path(str(bundle) + ".sha256")
            sidecar.write_text(
                "    no SHA-256 sidecar; perform one-time full bundle verification before migration\n"
                "    migrated verified bundle: wrote SHA-256 sidecar /bad/path\n"
                f"{digest}  {bundle.name}\n"
            )

            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "type": "unburger_br1_dlc_source_assets",
                "format_version": 2,
                "capability": "br1_legacy_source_assets_v2",
                "reconstruction_capability": "br1_legacy_content_rebuild_v1",
                "clean_anchor_capability": "br1_legacy_clean_source_anchors_v1",
                "clean_anchor_fingerprint": "a" * 64,
                "source_fingerprint": "a" * 64,
                "source_members": [""] * 1682,
                "image_files": ["image.bin"],
                "supplemental_sources": [{
                    "capability": "second_light_dlc_source_subset_v1",
                    "root": "SECOND_LIGHT",
                    "source_members": [""] * 2942,
                    "source_fingerprint": "b" * 64,
                }],
            }))
            anchors = root / "anchors.json"
            anchors.write_text("{}\n")

            mock_go = bindir / "go"
            mock_go.write_text("#!/usr/bin/env bash\nset -euo pipefail\ncat -- \"$MOCK_MANIFEST\"\n")
            mock_go.chmod(0o755)

            q = shlex.quote
            script = root / "test.sh"
            script.write_text(f"""#!/usr/bin/env bash
set -euo pipefail
WORK_DIR={q(str(work))}
PATCHER_ROOT={q(str(patcher))}
ASSET_ANCHORS={q(str(anchors))}
ASSET_ANCHOR_FINGERPRINT={'a'*64}
ASSET_EXPECTED_BR1_COUNT=1682
ASSET_EXPECTED_SL_COUNT=2942
{fn}
bundle={q(str(bundle))}
expected={digest}
sha=\"$(verify_assets_bundle \"$bundle\" existing 1)\"
[[ \"$sha\" == \"$expected\" ]]
[[ \"$sha\" =~ ^[0-9a-f]{{64}}$ ]]
read -r side_sha side_name < \"$bundle.sha256\"
[[ \"$side_sha\" == \"$expected\" ]]
[[ \"$side_name\" == \"{bundle.name}\" ]]
sha2=\"$(verify_assets_bundle \"$bundle\" existing 1)\"
[[ \"$sha2\" == \"$expected\" ]]
printf 'broken sidecar\\n' > \"$bundle.sha256\"
if verify_assets_bundle \"$bundle\" explicit 0 >/dev/null; then
  echo 'strict explicit bundle unexpectedly repaired' >&2
  exit 99
fi
[[ \"$(cat \"$bundle.sha256\")\" == 'broken sidecar' ]]
rm -f \"$bundle.sha256\"
sha3=\"$(verify_assets_bundle \"$bundle\" existing 1)\"
[[ \"$sha3\" == \"$expected\" ]]
read -r side_sha2 side_name2 < \"$bundle.sha256\"
[[ \"$side_sha2\" == \"$expected\" ]]
[[ \"$side_name2\" == \"{bundle.name}\" ]]
""")
            script.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{bindir}:{env['PATH']}"
            env["MOCK_MANIFEST"] = str(manifest)
            proc = subprocess.run(["bash", str(script)], text=True, capture_output=True, env=env)
            self.assertEqual(proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
            self.assertNotIn("no SHA-256 sidecar", proc.stdout)
            self.assertNotIn("migrated verified bundle", proc.stdout)


if __name__ == "__main__":
    unittest.main()
