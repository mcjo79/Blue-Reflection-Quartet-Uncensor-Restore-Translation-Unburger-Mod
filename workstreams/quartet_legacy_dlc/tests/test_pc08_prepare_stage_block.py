from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class Pc08PrepareStageBlockTests(unittest.TestCase):
    def test_stage_is_blocked_without_routing_acceptance(self) -> None:
        source = Path(__file__).resolve().parent.parent / "96_collect_pc08_generation_prepare_evidence.sh"
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            ws = project / "workstreams/quartet_legacy_dlc"
            ws.mkdir(parents=True)
            target = ws / source.name
            shutil.copy2(source, target)
            (ws / "VERSION").write_text("0.0.54\n", encoding="utf-8")
            original = Path(td) / "original"
            game = Path(td) / "game"
            original.mkdir()
            game.mkdir()
            result = subprocess.run(
                ["bash", str(target), "--original-dir", str(original), "--game-dir", str(game)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PC08 pozostaje zablokowane", result.stderr)


if __name__ == "__main__":
    unittest.main()
