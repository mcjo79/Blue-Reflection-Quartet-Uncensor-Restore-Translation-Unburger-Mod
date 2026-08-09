package br1rebuild

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestPrepareArtifactsCarriesPersistentBaselineMetadata(t *testing.T) {
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
	metadata := map[string]string{"purpose": "br1_legacy_content"}
	journalPath, baselineManifest, err := PrepareArtifactsForTargetWithProgress(game, state, "synthetic_target", []OutputArtifact{{
		RelativePath: "Data/PACK.PAK",
		Path:         candidate,
	}}, []string{"synthetic_module"}, metadata, nil)
	if err != nil {
		t.Fatal(err)
	}
	journal, err := transaction.Load(journalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Metadata["target_id"] != "synthetic_target" {
		t.Fatalf("target metadata = %q", journal.Metadata["target_id"])
	}
	if journal.Metadata["baseline_manifest_path"] != baselineManifest || baselineManifest == "" {
		t.Fatalf("baseline metadata = %q, return = %q", journal.Metadata["baseline_manifest_path"], baselineManifest)
	}
	if journal.Metadata["baseline_id"] == "" || journal.Metadata["baseline_fingerprint"] == "" {
		t.Fatalf("persistent baseline identity missing: %+v", journal.Metadata)
	}
	if _, err := os.Stat(baselineManifest); err != nil {
		t.Fatalf("baseline manifest missing: %v", err)
	}
	if _, exists := metadata["baseline_manifest_path"]; exists {
		t.Fatal("caller metadata map was mutated")
	}
}

func TestRejectNonTerminalTransactionsDiscardsOnlyRecoverableMalformedPrepare(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "B1.dll"), []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(payload, []byte("patched"), 0o644); err != nil {
		t.Fatal(err)
	}
	prepared, err := transaction.PrepareWithOptions(game, state, []transaction.ChangeSpec{{RelativePath: "B1.dll", StagedPath: payload}}, []string{"quartet_legacy_dlc"}, map[string]string{
		"target_id": "blue_reflection_quartet",
		"purpose":   "br1_legacy_content",
	}, transaction.PrepareOptions{RequireHardlinkBackup: true, UseSiblingFilesystemBackupStore: true})
	if err != nil {
		t.Fatal(err)
	}
	if err := rejectNonTerminalTransactions(state, nil); err != nil {
		t.Fatal(err)
	}
	journal, err := transaction.Load(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != transaction.StatusDiscarded {
		t.Fatalf("recovered journal status = %s", journal.Status)
	}
	got, err := os.ReadFile(filepath.Join(game, "B1.dll"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "original" {
		t.Fatalf("game file changed during recovery: %q", got)
	}
}

func TestRejectNonTerminalTransactionsKeepsValidPreparedTransactionBlocked(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "B1.dll"), []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(payload, []byte("patched"), 0o644); err != nil {
		t.Fatal(err)
	}
	prepared, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{RelativePath: "B1.dll", StagedPath: payload}}, []string{"quartet_legacy_dlc"}, map[string]string{
		"target_id":              "blue_reflection_quartet",
		"purpose":                "br1_legacy_content",
		"baseline_manifest_path": filepath.Join(state, "baselines", "known", "manifest.json"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := rejectNonTerminalTransactions(state, nil); err == nil {
		t.Fatal("valid prepared transaction was not kept as a blocker")
	}
	journal, err := transaction.Load(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != transaction.StatusPrepared {
		t.Fatalf("valid prepared journal status changed to %s", journal.Status)
	}
}
