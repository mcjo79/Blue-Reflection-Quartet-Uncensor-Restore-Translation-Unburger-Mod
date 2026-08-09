package installstate

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestActiveStateClassifiesInstalledBaselineAndUnknownFiles(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	stateRoot := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	writeFile(t, target, "original")
	writeFile(t, payload, "translated")

	base, err := baseline.Ensure(game, stateRoot, "blue_reflection_original", []string{"DATA/PACK01.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := transaction.Prepare(game, stateRoot, []transaction.ChangeSpec{{
		RelativePath: "DATA/PACK01.PAK", StagedPath: payload,
		VerifiedBackupPath: base.StoredFiles["DATA/PACK01.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id":              "blue_reflection_original",
		"baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	committed, err := transaction.Commit(prepared.JournalPath)
	if err != nil || committed.Status != transaction.StatusCommitted {
		t.Fatalf("commit: %v %+v", err, committed)
	}
	active, err := Activate(stateRoot, "blue_reflection_original", game, base.ManifestPath, prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if active.BaselineID != base.Manifest.BaselineID {
		t.Fatalf("baseline mismatch: %+v", active)
	}

	inspection, err := Inspect(stateRoot, "blue_reflection_original", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != InspectionMatchesInstalled {
		t.Fatalf("unexpected installed status: %+v", inspection)
	}

	writeFile(t, target, "original")
	inspection, err = Inspect(stateRoot, "blue_reflection_original", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != InspectionDisplacedToBaseline {
		t.Fatalf("unexpected displaced status: %+v", inspection)
	}

	writeFile(t, target, "external-change")
	inspection, err = Inspect(stateRoot, "blue_reflection_original", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != InspectionChangedUnclassified {
		t.Fatalf("unexpected changed status: %+v", inspection)
	}
}

func TestActiveStateHistoryRestoresPreviousStateAcrossUpdateRollback(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	stateRoot := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload1 := filepath.Join(root, "payload", "v1.PAK")
	payload2 := filepath.Join(root, "payload", "v2.PAK")
	writeFile(t, target, "original")
	writeFile(t, payload1, "translated-v1")
	writeFile(t, payload2, "translated-v2")

	base, err := baseline.Ensure(game, stateRoot, "blue_reflection_original", []string{"DATA/PACK01.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	first, err := transaction.Prepare(game, stateRoot, []transaction.ChangeSpec{{
		RelativePath: "DATA/PACK01.PAK", StagedPath: payload1,
		VerifiedBackupPath: base.StoredFiles["DATA/PACK01.PAK"],
	}}, []string{"blue_reflection_translation"}, map[string]string{"target_id": "blue_reflection_original"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	firstActive, err := Activate(stateRoot, "blue_reflection_original", game, base.ManifestPath, first.JournalPath)
	if err != nil {
		t.Fatal(err)
	}

	second, err := transaction.Prepare(game, stateRoot, []transaction.ChangeSpec{{
		RelativePath: "DATA/PACK01.PAK", StagedPath: payload2,
	}}, []string{"blue_reflection_translation"}, map[string]string{"target_id": "blue_reflection_original"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(second.JournalPath); err != nil {
		t.Fatal(err)
	}
	secondActive, err := Activate(stateRoot, "blue_reflection_original", game, base.ManifestPath, second.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if secondActive.PreviousStatePath == "" {
		t.Fatalf("previous active state was not archived: %+v", secondActive)
	}

	if _, err := transaction.Rollback(second.JournalPath); err != nil {
		t.Fatal(err)
	}
	var secondReconcileEvents []transaction.ProgressEvent
	restored, exists, err := ReconcileRollbackWithProgress(stateRoot, "blue_reflection_original", game, second.JournalPath, func(event transaction.ProgressEvent) {
		secondReconcileEvents = append(secondReconcileEvents, event)
	})
	if err != nil {
		t.Fatal(err)
	}
	if !exists || restored.TransactionID != firstActive.TransactionID {
		t.Fatalf("previous state was not restored: %+v exists=%v", restored, exists)
	}
	if got := readFile(t, target); got != "translated-v1" {
		t.Fatalf("update rollback restored %q", got)
	}
	for _, event := range secondReconcileEvents {
		if event.Phase == "verify_previous_state" && event.FileBytesTotal > 0 {
			t.Fatalf("fully covered rollback reread previous-state bytes: %+v", event)
		}
	}

	if _, err := transaction.Rollback(first.JournalPath); err != nil {
		t.Fatal(err)
	}
	var firstReconcileEvents []transaction.ProgressEvent
	_, exists, err = ReconcileRollbackWithProgress(stateRoot, "blue_reflection_original", game, first.JournalPath, func(event transaction.ProgressEvent) {
		firstReconcileEvents = append(firstReconcileEvents, event)
	})
	if err != nil {
		t.Fatal(err)
	}
	if exists {
		t.Fatal("first install rollback unexpectedly left an active state")
	}
	if got := readFile(t, target); got != "original" {
		t.Fatalf("first rollback restored %q", got)
	}
	for _, event := range firstReconcileEvents {
		if event.Phase == "verify_baseline_state" && event.FileBytesTotal > 0 {
			t.Fatalf("fully covered baseline rollback reread restored bytes: %+v", event)
		}
	}
}

func writeFile(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
		t.Fatal(err)
	}
}

func readFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestActiveStateAndTransactionResolveExistingGamePathsCaseInsensitively(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	stateRoot := filepath.Join(root, "state")
	actualTarget := filepath.Join(game, "data", "pack01.pak")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	writeFile(t, actualTarget, "older-revision-original")
	writeFile(t, payload, "translated")

	base, err := baseline.Ensure(game, stateRoot, "blue_reflection_original", []string{"DATA/PACK01.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	stored := base.StoredFiles["DATA/PACK01.PAK"]
	if stored == "" {
		t.Fatalf("canonical baseline path was not captured: %+v", base.StoredFiles)
	}
	prepared, err := transaction.Prepare(game, stateRoot, []transaction.ChangeSpec{{
		RelativePath: "DATA/PACK01.PAK", StagedPath: payload,
		VerifiedBackupPath: stored,
	}}, []string{"blue_reflection_translation"}, map[string]string{
		"target_id":              "blue_reflection_original",
		"baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if got := readFile(t, actualTarget); got != "translated" {
		t.Fatalf("case-preserving commit wrote %q", got)
	}
	if _, err := os.Lstat(filepath.Join(game, "DATA")); !os.IsNotExist(err) {
		t.Fatalf("commit created a duplicate differently-cased DATA directory: %v", err)
	}
	if _, err := Activate(stateRoot, "blue_reflection_original", game, base.ManifestPath, prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	inspection, err := Inspect(stateRoot, "blue_reflection_original", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != InspectionMatchesInstalled {
		t.Fatalf("case-insensitive active state was not recognized: %+v", inspection)
	}
	if _, err := transaction.Rollback(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if got := readFile(t, actualTarget); got != "older-revision-original" {
		t.Fatalf("case-preserving rollback restored %q", got)
	}
}
