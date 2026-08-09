package main

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestArtifactPreparationCarriesBaselineThroughCommitAndActivation(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "PACK.PAK")
	candidate := filepath.Join(root, "candidate.pak")
	if err := os.WriteFile(target, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(candidate, []byte("patched"), 0o644); err != nil {
		t.Fatal(err)
	}
	journal, baselineManifest, err := br1rebuild.PrepareArtifactsForTargetWithProgress(game, state, "synthetic_target", []br1rebuild.OutputArtifact{{
		RelativePath: "Data/PACK.PAK",
		Path:         candidate,
	}}, []string{"synthetic_module"}, map[string]string{"purpose": "br1_legacy_content"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	preparedJournal, err := transaction.Load(journal)
	if err != nil {
		t.Fatal(err)
	}
	manifest, stored, err := baseline.LoadAndVerify(baselineManifest)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.FormatVersion != baseline.ManifestFormatVersion || manifest.StorageRoot != preparedJournal.BackupRoot {
		t.Fatalf("baseline storage is not the game-side transaction backup: manifest=%+v journal=%+v", manifest, preparedJournal)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(baselineManifest), "files")); !os.IsNotExist(err) {
		t.Fatalf("AppData-style full baseline payload was created: %v", err)
	}
	if got := stored["Data/PACK.PAK"]; got == "" || filepath.Clean(got) != filepath.Clean(filepath.Join(preparedJournal.BackupRoot, "backup", "Data", "PACK.PAK")) {
		t.Fatalf("baseline stored path = %q", got)
	}
	report, err := commitPreparedTransactionWithProgress(journal, nil)
	if err != nil {
		t.Fatalf("commit rejected helper-prepared journal: %v", err)
	}
	if report.BaselineManifestPath != baselineManifest || report.BaselineManifestPath == "" {
		t.Fatalf("commit baseline = %q, prepare baseline = %q", report.BaselineManifestPath, baselineManifest)
	}
	active, exists, err := installstate.Load(state, "synthetic_target", game)
	if err != nil {
		t.Fatal(err)
	}
	if !exists || active.TransactionID != report.TransactionID || active.BaselineManifestPath != baselineManifest {
		t.Fatalf("active installation state not published from helper transaction: %+v exists=%v", active, exists)
	}
	got, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "patched" {
		t.Fatalf("game file = %q", got)
	}
	if _, err := os.Stat(preparedJournal.BackupRoot); err != nil {
		t.Fatalf("active game-side rollback store disappeared: %v", err)
	}
	rolledBack, err := rollbackInstalledTransactionWithProgress(journal, nil)
	if err != nil {
		t.Fatal(err)
	}
	if rolledBack.ActiveAfterRollback {
		t.Fatal("first-install rollback unexpectedly left active state")
	}
	if _, err := os.Stat(preparedJournal.BackupRoot); !os.IsNotExist(err) {
		t.Fatalf("terminal rollback store survived cleanup: %v", err)
	}
	if _, err := os.Stat(filepath.Dir(baselineManifest)); !os.IsNotExist(err) {
		t.Fatalf("inactive baseline metadata/payload survived cleanup: %v", err)
	}
	restored, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(restored) != "original" {
		t.Fatalf("rollback restored %q", restored)
	}
}
