package main

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/plan/installstate"
)

func TestRemoveManagedInstallationRollsBackEntireUpdateChain(t *testing.T) {
	useSyntheticGuidedPrepare(t)
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload1 := filepath.Join(root, "payload", "PACK01-v1.PAK")
	payload2 := filepath.Join(root, "payload", "PACK01-v2.PAK")
	mustWriteTestFile(t, target, []byte("original"))
	mustWriteTestFile(t, payload1, []byte("translated-v1"))
	mustWriteTestFile(t, payload2, []byte("translated-v2"))

	originalHash, _ := hashRegularFile(target)
	hash1, _ := hashRegularFile(payload1)
	first, err := executeGuidedPayloadAction(syntheticPreparePreview(game, state, payload1, target, hash1, originalHash), guidedActionInstall, os.Stdout)
	if err != nil {
		t.Fatal(err)
	}
	installedHash1, _ := hashRegularFile(target)
	hash2, _ := hashRegularFile(payload2)
	second, err := executeGuidedPayloadAction(syntheticPreparePreview(game, state, payload2, target, hash2, installedHash1), guidedActionInstall, os.Stdout)
	if err != nil {
		t.Fatal(err)
	}
	if first.CommitReport.TransactionID == second.CommitReport.TransactionID {
		t.Fatal("update did not create a distinct transaction")
	}

	report, err := removeManagedInstallationFromState("blue_reflection_original", "BLUE REFLECTION", game, state)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "removed" || report.RollbackCount != 2 || !report.BaselineRestored || !report.GameFilesModified {
		t.Fatalf("unexpected removal report: %+v", report)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("complete removal did not restore baseline: %q", got)
	}
	if _, exists, err := installstate.Load(state, "blue_reflection_original", game); err != nil || exists {
		t.Fatalf("active state survived complete removal: exists=%v err=%v", exists, err)
	}
}

func TestRemoveManagedInstallationClearsDisplacedStateWithoutRewritingGame(t *testing.T) {
	useSyntheticGuidedPrepare(t)
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	mustWriteTestFile(t, target, []byte("original"))
	mustWriteTestFile(t, payload, []byte("translated"))
	originalHash, _ := hashRegularFile(target)
	payloadHash, _ := hashRegularFile(payload)
	result, err := executeGuidedPayloadAction(syntheticPreparePreview(game, state, payload, target, payloadHash, originalHash), guidedActionInstall, os.Stdout)
	if err != nil {
		t.Fatal(err)
	}
	journal, err := loadTransactionCommandContext(result.PrepareReport.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	backup := filepath.Join(journal.Journal.TransactionRoot, filepath.FromSlash(journal.Journal.Files[0].BackupPath))
	data, err := os.ReadFile(backup)
	if err != nil {
		t.Fatal(err)
	}
	mustWriteTestFile(t, target, data)

	report, err := removeManagedInstallationFromState("blue_reflection_original", "BLUE REFLECTION", game, state)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "removed" || report.RollbackCount != 1 || report.StaleStateRecordCleared || report.GameFilesModified {
		t.Fatalf("unexpected displaced removal report: %+v", report)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("displaced removal rewrote game unexpectedly: %q", got)
	}
}

func TestRemoveManagedInstallationRejectsExternalChanges(t *testing.T) {
	useSyntheticGuidedPrepare(t)
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	mustWriteTestFile(t, target, []byte("original"))
	mustWriteTestFile(t, payload, []byte("translated"))
	originalHash, _ := hashRegularFile(target)
	payloadHash, _ := hashRegularFile(payload)
	if _, err := executeGuidedPayloadAction(syntheticPreparePreview(game, state, payload, target, payloadHash, originalHash), guidedActionInstall, os.Stdout); err != nil {
		t.Fatal(err)
	}
	mustWriteTestFile(t, target, []byte("external-change"))
	if _, err := removeManagedInstallationFromState("blue_reflection_original", "BLUE REFLECTION", game, state); err == nil {
		t.Fatal("complete removal accepted an externally changed managed file")
	}
	if got, _ := os.ReadFile(target); string(got) != "external-change" {
		t.Fatalf("failed removal overwrote external change: %q", got)
	}
}
