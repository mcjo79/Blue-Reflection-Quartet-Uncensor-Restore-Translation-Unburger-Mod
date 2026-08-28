#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "BUILD_RELEASE.sh"
IMPORT = ROOT / "IMPORT_CANONICAL_UNCENSOR_SOURCE.sh"
RELEASE_GO = ROOT / "Blue_Reflection_Patcher/cmd/unburger-release/main.go"


class CanonicalUncensorLocalSourceTests(unittest.TestCase):
    def test_normal_release_uses_local_cache_not_retail_install(self):
        text = BUILD.read_text()
        self.assertIn('.local/Uncensor/quartet_wet_school_canonical_source_v1', text)
        self.assertIn('--wet-school-canonical-payload "$CANONICAL_PAYLOAD_ROOT"', text)
        self.assertIn('LEGACY_CANONICAL_PAYLOAD_ROOT', text)
        self.assertIn('.local/Video/restored_webm', text)
        self.assertNotIn('--br1-canonical-source "$CANONICAL_SOURCE"', text)
        block = text[text.index('echo "==> Resolve canonical UNCENSOR local source"'):text.index('echo "==> Build canonical Translation record payload"')]
        self.assertNotIn('resolve_rebuild_root', block)
        self.assertNotIn('steamapps/common/BLUE REFLECTION', block)

    def test_retail_source_is_one_time_import_only(self):
        text = IMPORT.read_text()
        self.assertIn('quartet_wet_school_canonical_source_v1', text)
        self.assertIn('.local/Uncensor/', text)
        self.assertIn('LEGACY_CACHE_ROOT', text)
        self.assertIn('PACK00_02.PAK', text)
        self.assertIn('sha256sum', text)
        self.assertIn('go run ./cmd/unburger-canonical-source --import', text)
        self.assertIn('go run ./cmd/unburger-canonical-source --verify', text)

    def test_release_stager_requires_local_payload(self):
        text = RELEASE_GO.read_text()
        self.assertIn('wet-school-canonical-payload', text)
        self.assertIn('CopyWetSchoolCanonicalPayload', text)
        self.assertNotIn('br1-canonical-source', text)


if __name__ == '__main__':
    unittest.main()
