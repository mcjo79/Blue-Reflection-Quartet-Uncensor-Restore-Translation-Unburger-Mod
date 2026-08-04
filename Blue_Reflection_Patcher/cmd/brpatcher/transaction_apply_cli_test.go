package main

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestPublicCommitAndRollbackFirstInstall(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload.pak")
	mustWriteApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK"), "stock")
	mustWriteApplyTestFile(t, payload, "mod-v1")
	base, err := baseline.Ensure(game, state, "synthetic", []string{"Data/PACK.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "Data/PACK.PAK", StagedPath: payload,
		VerifiedBackupPath: base.StoredFiles["Data/PACK.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id": "synthetic", "baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	installed, err := commitPreparedTransaction(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if installed.Status != "installed" || !installed.GameFilesModified {
		t.Fatalf("unexpected install report: %+v", installed)
	}
	if got := mustReadApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK")); got != "mod-v1" {
		t.Fatalf("installed payload mismatch: %q", got)
	}
	inspection, err := installstate.Inspect(state, "synthetic", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != installstate.InspectionMatchesInstalled {
		t.Fatalf("active installation mismatch: %+v", inspection)
	}
	idempotent, err := commitPreparedTransaction(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if idempotent.Status != "already_installed" || idempotent.GameFilesModified {
		t.Fatalf("unexpected idempotent report: %+v", idempotent)
	}
	rolledBack, err := rollbackInstalledTransaction(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if rolledBack.ActiveAfterRollback || !rolledBack.GameFilesModified {
		t.Fatalf("unexpected rollback report: %+v", rolledBack)
	}
	if got := mustReadApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK")); got != "stock" {
		t.Fatalf("baseline was not restored: %q", got)
	}
}

func TestPublicUpdateRollbackRestoresPreviousActiveState(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	mustWriteApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK"), "stock")
	base, err := baseline.Ensure(game, state, "synthetic", []string{"Data/PACK.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	payload1 := filepath.Join(root, "payload-v1.pak")
	mustWriteApplyTestFile(t, payload1, "mod-v1")
	first, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "Data/PACK.PAK", StagedPath: payload1,
		VerifiedBackupPath: base.StoredFiles["Data/PACK.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id": "synthetic", "baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := commitPreparedTransaction(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	payload2 := filepath.Join(root, "payload-v2.pak")
	mustWriteApplyTestFile(t, payload2, "mod-v2")
	second, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "Data/PACK.PAK", StagedPath: payload2,
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id": "synthetic", "baseline_manifest_path": base.ManifestPath,
		"active_transaction_id": first.Journal.TransactionID,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := commitPreparedTransaction(second.JournalPath); err != nil {
		t.Fatal(err)
	}
	if got := mustReadApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK")); got != "mod-v2" {
		t.Fatalf("update payload mismatch: %q", got)
	}
	rolledBack, err := rollbackInstalledTransaction(second.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if !rolledBack.ActiveAfterRollback || rolledBack.ActiveTransactionID != first.Journal.TransactionID {
		t.Fatalf("previous active state was not restored: %+v", rolledBack)
	}
	if got := mustReadApplyTestFile(t, filepath.Join(game, "Data", "PACK.PAK")); got != "mod-v1" {
		t.Fatalf("previous mod version was not restored: %q", got)
	}
}

func TestDisplacedActiveStateReinstallRollsBackToBaseline(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "Data", "PACK.PAK")
	mustWriteApplyTestFile(t, target, "stock")
	base, err := baseline.Ensure(game, state, "synthetic", []string{"Data/PACK.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	payload1 := filepath.Join(root, "payload-v1.pak")
	mustWriteApplyTestFile(t, payload1, "mod-v1")
	first, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "Data/PACK.PAK", StagedPath: payload1,
		VerifiedBackupPath: base.StoredFiles["Data/PACK.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id": "synthetic", "baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := commitPreparedTransaction(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	mustWriteApplyTestFile(t, target, "stock")
	inspection, err := installstate.Inspect(state, "synthetic", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != installstate.InspectionDisplacedToBaseline {
		t.Fatalf("expected displaced active state: %+v", inspection)
	}
	payload2 := filepath.Join(root, "payload-v2.pak")
	mustWriteApplyTestFile(t, payload2, "mod-v2")
	second, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "Data/PACK.PAK", StagedPath: payload2,
		VerifiedBackupPath: base.StoredFiles["Data/PACK.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id": "synthetic", "baseline_manifest_path": base.ManifestPath,
		"active_transaction_id": first.Journal.TransactionID,
		"active_state_status":   installstate.InspectionDisplacedToBaseline,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := commitPreparedTransaction(second.JournalPath); err != nil {
		t.Fatal(err)
	}
	rolledBack, err := rollbackInstalledTransaction(second.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if rolledBack.ActiveAfterRollback {
		t.Fatalf("displaced reinstall rollback should return to baseline, not stale mod: %+v", rolledBack)
	}
	if got := mustReadApplyTestFile(t, target); got != "stock" {
		t.Fatalf("baseline was not restored after displaced reinstall rollback: %q", got)
	}
}

func mustWriteApplyTestFile(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
		t.Fatal(err)
	}
}

func mustReadApplyTestFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}
