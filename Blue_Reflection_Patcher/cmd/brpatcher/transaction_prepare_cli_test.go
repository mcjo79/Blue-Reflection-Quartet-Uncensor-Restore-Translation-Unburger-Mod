package main

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestPreparePayloadTransactionStagesAndBacksUpWithoutGameEdit(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	report, err := preparePayloadTransaction(preview)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "prepared" || !report.CommitEnabled || report.PreparedChangeCount != 1 || report.BackupCount != 1 {
		t.Fatalf("unexpected prepare report: %+v", report)
	}
	if report.BaselineAction != "created" || report.BaselineID == "" || report.BaselineManifestPath == "" || report.BaselineFileCount != 1 {
		t.Fatalf("persistent baseline was not recorded: %+v", report)
	}
	if _, err := os.Stat(report.BaselineManifestPath); err != nil {
		t.Fatalf("baseline manifest is missing: %v", err)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("prepare modified game target: %q", got)
	}
	journal, err := transaction.Load(report.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != transaction.StatusPrepared || len(journal.Files) != 1 {
		t.Fatalf("unexpected journal: %+v", journal)
	}
	staged := filepath.Join(journal.TransactionRoot, filepath.FromSlash(journal.Files[0].StagedPath))
	backup := filepath.Join(journal.TransactionRoot, filepath.FromSlash(journal.Files[0].BackupPath))
	if got, _ := os.ReadFile(staged); string(got) != "translated" {
		t.Fatalf("unexpected staged payload: %q", got)
	}
	if got, _ := os.ReadFile(backup); string(got) != "original" {
		t.Fatalf("unexpected backup: %q", got)
	}
	if _, err := preparePayloadTransaction(preview); err == nil {
		t.Fatal("second prepare unexpectedly accepted a non-terminal transaction")
	}
	discarded, err := transaction.DiscardPrepared(report.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if discarded.Status != transaction.StatusDiscarded {
		t.Fatalf("unexpected discard status: %s", discarded.Status)
	}
	if _, err := os.Stat(staged); !os.IsNotExist(err) {
		t.Fatalf("staged payload survived discard: %v", err)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("discard modified game target: %q", got)
	}
	if _, err := os.Stat(report.BaselineManifestPath); err != nil {
		t.Fatalf("discard removed persistent baseline: %v", err)
	}
}

func TestPreparePayloadTransactionRejectsStaleSource(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)
	mustWriteTestFile(t, payload, []byte("changed-after-preview"))

	if _, err := preparePayloadTransaction(preview); err == nil {
		t.Fatal("stale payload source was accepted")
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("stale prepare modified game target: %q", got)
	}
	if entries, err := os.ReadDir(filepath.Join(state, "transactions")); err == nil && len(entries) != 0 {
		t.Fatalf("failed stale prepare left transaction state: %v", entries)
	}
}

func TestPreparePayloadTransactionNoopCreatesNoJournal(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("same"))
	mustWriteTestFile(t, target, []byte("same"))
	hash, _ := hashRegularFile(payload)
	preview := syntheticPreparePreview(game, state, payload, target, hash, hash)
	preview.Targets[0].Modules[0].Artifacts[0].DesiredAction = "noop"

	report, err := preparePayloadTransaction(preview)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "no_changes" || report.JournalPath != "" || report.NoopCount != 1 {
		t.Fatalf("unexpected no-op report: %+v", report)
	}
	if report.BaselineID != "" || report.BaselineManifestPath != "" {
		t.Fatalf("no-op prepare unexpectedly created a baseline: %+v", report)
	}
}

func syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash string) payloadpreview.Preview {
	sourceInfo, _ := os.Stat(payload)
	targetInfo, _ := os.Stat(target)
	return payloadpreview.Preview{
		Type: payloadpreview.PreviewType, FormatVersion: payloadpreview.PreviewFormatVersion,
		Status: "ready", GeneratedUTC: time.Now().UTC(), ProjectRoot: filepath.Dir(filepath.Dir(payload)), CommitEnabled: false,
		Targets: []payloadpreview.TargetPreview{{
			TargetID: "blue_reflection_original", DisplayName: "BLUE REFLECTION", GameRoot: game,
			SelectedModules: []string{"blue_reflection_translation"}, StateDirectory: state,
			Status: "ready", ReadyArtifactCount: 1, PendingModuleCount: 0,
			Modules: []payloadpreview.ModulePreview{{
				ModuleID: "blue_reflection_translation", Ready: true,
				Artifacts: []payloadpreview.ArtifactPreview{{
					ModuleID: "blue_reflection_translation", RelativePath: "DATA/PACK01.PAK",
					SourcePath: payload, SourceSHA256: sourceHash, SourceBytes: sourceInfo.Size(), ReportVerified: true,
					TargetPath: target, TargetExists: true, TargetSHA256: targetHash, TargetBytes: targetInfo.Size(),
					DesiredAction: "replace", TransactionReady: true, Status: "ready",
				}},
			}},
		}},
	}
}

func mustWriteTestFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestPreparePayloadTransactionUpdatesRecordedActiveInstallWithoutRecapturingModdedBaseline(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload1 := filepath.Join(root, "payload", "PACK01-v1.PAK")
	payload2 := filepath.Join(root, "payload", "PACK01-v2.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload1, []byte("translated-v1"))
	mustWriteTestFile(t, payload2, []byte("translated-v2"))
	mustWriteTestFile(t, target, []byte("original"))

	sourceHash1, _ := hashRegularFile(payload1)
	originalHash, _ := hashRegularFile(target)
	firstPreview := syntheticPreparePreview(game, state, payload1, target, sourceHash1, originalHash)
	first, err := preparePayloadTransaction(firstPreview)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := installstate.Activate(state, "blue_reflection_original", game, first.BaselineManifestPath, first.JournalPath); err != nil {
		t.Fatal(err)
	}

	sourceHash2, _ := hashRegularFile(payload2)
	installedHash, _ := hashRegularFile(target)
	secondPreview := syntheticPreparePreview(game, state, payload2, target, sourceHash2, installedHash)
	second, err := preparePayloadTransaction(secondPreview)
	if err != nil {
		t.Fatal(err)
	}
	if second.Status != "prepared" || second.ActiveStateStatus != installstate.InspectionMatchesInstalled {
		t.Fatalf("active installation update was not prepared safely: %+v", second)
	}
	if second.BaselineID != first.BaselineID || second.BaselineSource != "preserved_active_installation_baseline" {
		t.Fatalf("active update did not preserve the original baseline: first=%+v second=%+v", first, second)
	}
	manifest, stored, err := baseline.LoadAndVerify(second.BaselineManifestPath)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.BaselineID != first.BaselineID {
		t.Fatalf("unexpected replacement baseline: %+v", manifest)
	}
	if got, _ := os.ReadFile(stored["DATA/PACK01.PAK"]); string(got) != "original" {
		t.Fatalf("modded file was captured as persistent baseline: %q", got)
	}
	journal, err := transaction.Load(second.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	backup := filepath.Join(journal.TransactionRoot, filepath.FromSlash(journal.Files[0].BackupPath))
	if got, _ := os.ReadFile(backup); string(got) != "translated-v1" {
		t.Fatalf("update transaction backup did not preserve the previous installed state: %q", got)
	}
	if got, _ := os.ReadFile(target); string(got) != "translated-v1" {
		t.Fatalf("update prepare modified active game file: %q", got)
	}
	if _, err := transaction.DiscardPrepared(second.JournalPath); err != nil {
		t.Fatal(err)
	}
}

func TestPreparePayloadTransactionBlocksUnclassifiedChangesToRecordedActiveInstall(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload1 := filepath.Join(root, "payload", "PACK01-v1.PAK")
	payload2 := filepath.Join(root, "payload", "PACK01-v2.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload1, []byte("translated-v1"))
	mustWriteTestFile(t, payload2, []byte("translated-v2"))
	mustWriteTestFile(t, target, []byte("original"))

	hash1, _ := hashRegularFile(payload1)
	originalHash, _ := hashRegularFile(target)
	first, err := preparePayloadTransaction(syntheticPreparePreview(game, state, payload1, target, hash1, originalHash))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := installstate.Activate(state, "blue_reflection_original", game, first.BaselineManifestPath, first.JournalPath); err != nil {
		t.Fatal(err)
	}

	mustWriteTestFile(t, target, []byte("external-change"))
	hash2, _ := hashRegularFile(payload2)
	externalHash, _ := hashRegularFile(target)
	_, err = preparePayloadTransaction(syntheticPreparePreview(game, state, payload2, target, hash2, externalHash))
	if err == nil {
		t.Fatal("unclassified active installation change was accepted")
	}
}
