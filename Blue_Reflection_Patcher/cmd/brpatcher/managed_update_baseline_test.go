package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestManagedQuartetUpdateUsesEarliestPreManagementBaselineAndKeepsRollbackChain(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "B1.dll")
	firstCandidate := filepath.Join(root, "candidate-v1.dll")
	secondCandidate := filepath.Join(root, "candidate-v2.dll")
	mustWriteTestFile(t, target, []byte("original-clean"))
	mustWriteTestFile(t, firstCandidate, []byte("managed-v1"))
	mustWriteTestFile(t, secondCandidate, []byte("managed-v2"))

	firstJournal, _, err := br1rebuild.PrepareArtifactsForTargetWithProgress(game, state, quartetTargetID, []br1rebuild.OutputArtifact{{
		RelativePath: "B1.dll", Path: firstCandidate,
	}}, []string{quartetTranslationModule}, map[string]string{"purpose": "br1_legacy_content"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	firstCommit, err := commitPreparedTransactionWithProgress(firstJournal, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(target); string(got) != "managed-v1" {
		t.Fatalf("first install wrote %q", got)
	}
	firstSources, active, err := activeManagedBaselineBuildSources(state, quartetTargetID, game)
	if err != nil || !active {
		t.Fatalf("first managed baseline lookup: active=%v err=%v", active, err)
	}
	if got, _ := os.ReadFile(firstSources["B1.dll"]); string(got) != "original-clean" {
		t.Fatalf("first managed build source is %q", got)
	}

	secondJournal, _, err := br1rebuild.PrepareArtifactsForTargetWithProgress(game, state, quartetTargetID, []br1rebuild.OutputArtifact{{
		RelativePath: "B1.dll", Path: secondCandidate,
	}}, []string{quartetTranslationModule}, map[string]string{"purpose": "br1_legacy_content"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	preparedSecond, err := transaction.Load(secondJournal)
	if err != nil {
		t.Fatal(err)
	}
	if preparedSecond.Metadata["active_transaction_id"] != firstCommit.TransactionID || preparedSecond.Metadata["active_state_prepare_guard"] != "expected_installed_sha256" {
		t.Fatalf("managed update journal lacks active predecessor/guard metadata: %+v", preparedSecond.Metadata)
	}
	if _, err := commitPreparedTransactionWithProgress(secondJournal, nil); err != nil {
		t.Fatal(err)
	}
	if got, _ := os.ReadFile(target); string(got) != "managed-v2" {
		t.Fatalf("second install wrote %q", got)
	}

	secondSources, active, err := activeManagedBaselineBuildSources(state, quartetTargetID, game)
	if err != nil || !active {
		t.Fatalf("second managed baseline lookup: active=%v err=%v", active, err)
	}
	cleanPath := secondSources["B1.dll"]
	if strings.TrimSpace(cleanPath) == "" {
		t.Fatal("second managed update lost its clean B1.dll source")
	}
	if got, _ := os.ReadFile(cleanPath); string(got) != "original-clean" {
		t.Fatalf("second managed build would stack on %q instead of the original baseline", got)
	}

	report, err := removeManagedInstallationFromState(quartetTargetID, "BLUE REFLECTION Quartet", game, state)
	if err != nil {
		t.Fatal(err)
	}
	if report.RollbackCount != 2 || !report.BaselineRestored {
		t.Fatalf("unexpected full managed removal after update chain: %+v", report)
	}
	if got, _ := os.ReadFile(target); string(got) != "original-clean" {
		t.Fatalf("full removal after update chain restored %q", got)
	}
}

func TestManagedQuartetUpdateRejectsExternallyChangedInstalledFileDuringPrepare(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "B1.dll")
	firstCandidate := filepath.Join(root, "candidate-v1.dll")
	secondCandidate := filepath.Join(root, "candidate-v2.dll")
	mustWriteTestFile(t, target, []byte("original-clean"))
	mustWriteTestFile(t, firstCandidate, []byte("managed-v1"))
	mustWriteTestFile(t, secondCandidate, []byte("managed-v2"))

	journal, _, err := br1rebuild.PrepareArtifactsForTargetWithProgress(game, state, quartetTargetID, []br1rebuild.OutputArtifact{{RelativePath: "B1.dll", Path: firstCandidate}}, []string{quartetTranslationModule}, map[string]string{"purpose": "br1_legacy_content"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := commitPreparedTransactionWithProgress(journal, nil); err != nil {
		t.Fatal(err)
	}
	mustWriteTestFile(t, target, []byte("external-change"))

	if _, _, err := br1rebuild.PrepareArtifactsForTargetWithProgress(game, state, quartetTargetID, []br1rebuild.OutputArtifact{{RelativePath: "B1.dll", Path: secondCandidate}}, []string{quartetTranslationModule}, map[string]string{"purpose": "br1_legacy_content"}, nil); err == nil || !strings.Contains(err.Error(), "managed target changed before update") {
		t.Fatalf("managed update accepted external target change: %v", err)
	}
	if got, _ := os.ReadFile(target); string(got) != "external-change" {
		t.Fatalf("failed update prepare rewrote external data: %q", got)
	}
}
