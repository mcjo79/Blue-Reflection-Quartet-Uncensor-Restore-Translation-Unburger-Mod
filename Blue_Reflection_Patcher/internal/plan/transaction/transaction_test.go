package transaction

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func write(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
		t.Fatal(err)
	}
}

func read(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestPrepareCommitRollbackExistingAndNewFiles(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	staged := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(game, "Data", "A.PAK"), "original-a")
	write(t, filepath.Join(staged, "A.PAK"), "patched-a")
	write(t, filepath.Join(staged, "B.PAK"), "new-b")

	prepared, err := Prepare(game, state, []ChangeSpec{
		{RelativePath: "Data/A.PAK", StagedPath: filepath.Join(staged, "A.PAK")},
		{RelativePath: "Data/B.PAK", StagedPath: filepath.Join(staged, "B.PAK")},
	}, []string{"translation", "restoration"}, map[string]string{"target_id": "quartet"})
	if err != nil {
		t.Fatal(err)
	}
	if read(t, filepath.Join(game, "Data", "A.PAK")) != "original-a" {
		t.Fatal("prepare modified an existing game file")
	}
	if _, err := os.Stat(filepath.Join(game, "Data", "B.PAK")); !os.IsNotExist(err) {
		t.Fatal("prepare created a new game file")
	}
	if len(prepared.Journal.Files) != 2 {
		t.Fatalf("unexpected prepared journal: %+v", prepared.Journal)
	}
	for _, record := range prepared.Journal.Files {
		if record.StagedStorageMethod != "reflink" && record.StagedStorageMethod != "copy" {
			t.Fatalf("unexpected staged storage method for %s: %q", record.RelativePath, record.StagedStorageMethod)
		}
		if record.OriginalExisted && record.BackupStorageMethod != "hardlink" && record.BackupStorageMethod != "reflink" && record.BackupStorageMethod != "copy" {
			t.Fatalf("unexpected backup storage method for %s: %q", record.RelativePath, record.BackupStorageMethod)
		}
	}
	write(t, filepath.Join(staged, "A.PAK"), "source-mutated-after-prepare")
	stagedPrivate := filepath.Join(prepared.Journal.TransactionRoot, filepath.FromSlash(prepared.Journal.Files[0].StagedPath))
	if read(t, stagedPrivate) != "patched-a" {
		t.Fatal("private staged payload changed after its source was modified")
	}
	journal, err := Commit(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusCommitted || read(t, filepath.Join(game, "Data", "A.PAK")) != "patched-a" || read(t, filepath.Join(game, "Data", "B.PAK")) != "new-b" {
		t.Fatalf("commit result is invalid: %+v", journal)
	}
	for _, record := range journal.Files {
		if record.InstalledStorageMethod != "reflink" && record.InstalledStorageMethod != "copy" && record.InstalledStorageMethod != "already_present" {
			t.Fatalf("unexpected installed storage method for %s: %q", record.RelativePath, record.InstalledStorageMethod)
		}
	}
	journal, err = Rollback(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusRolledBack || read(t, filepath.Join(game, "Data", "A.PAK")) != "original-a" {
		t.Fatalf("rollback result is invalid: %+v", journal)
	}
	if _, err := os.Stat(filepath.Join(game, "Data", "B.PAK")); !os.IsNotExist(err) {
		t.Fatal("rollback did not remove transaction-owned new file")
	}
}

func TestCommitRejectsExternalModificationAfterPrepare(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload")
	write(t, target, "original")
	write(t, payload, "patched")
	prepared, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{RelativePath: "Data/A.PAK", StagedPath: payload}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	write(t, target, "external-change")
	if _, err := Commit(prepared.JournalPath); err == nil {
		t.Fatal("expected commit conflict")
	}
	if read(t, target) != "external-change" {
		t.Fatal("commit conflict overwrote external modification")
	}
}

func TestRollbackRejectsExternalModificationAfterCommit(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload")
	write(t, target, "original")
	write(t, payload, "patched")
	prepared, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{RelativePath: "Data/A.PAK", StagedPath: payload}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	write(t, target, "external-change")
	if _, err := Rollback(prepared.JournalPath); err == nil {
		t.Fatal("expected rollback conflict")
	}
	if read(t, target) != "external-change" {
		t.Fatal("rollback conflict overwrote external modification")
	}
}

func TestRejectsEscapingAndDuplicatePaths(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	payload := filepath.Join(root, "payload")
	write(t, payload, "patched")
	if _, err := Prepare(game, filepath.Join(root, "state-a"), []ChangeSpec{{RelativePath: "../escape", StagedPath: payload}}, nil, nil); err == nil {
		t.Fatal("expected path escape rejection")
	}
	if _, err := Prepare(game, filepath.Join(root, "state-b"), []ChangeSpec{
		{RelativePath: "Data/A.PAK", StagedPath: payload},
		{RelativePath: "data/a.pak", StagedPath: payload},
	}, nil, nil); err == nil {
		t.Fatal("expected case-insensitive duplicate rejection")
	}
}

func TestDiscardPreparedVerifiesAndRemovesPrivatePayloads(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload")
	write(t, target, "original")
	write(t, payload, "patched")
	prepared, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{RelativePath: "Data/A.PAK", StagedPath: payload}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	journal, err := DiscardPrepared(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusDiscarded || read(t, target) != "original" {
		t.Fatalf("discard result is invalid: %+v", journal)
	}
	if _, err := os.Stat(filepath.Join(journal.TransactionRoot, "staged")); !os.IsNotExist(err) {
		t.Fatal("discard retained staged payload directory")
	}
	if _, err := os.Stat(filepath.Join(journal.TransactionRoot, "backup")); !os.IsNotExist(err) {
		t.Fatal("discard retained backup directory")
	}
	loaded, err := Load(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if loaded.Status != StatusDiscarded {
		t.Fatalf("discard audit journal was not retained: %+v", loaded)
	}
}

func TestDiscardPreparedRejectsChangedGameFile(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload")
	write(t, target, "original")
	write(t, payload, "patched")
	prepared, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{RelativePath: "Data/A.PAK", StagedPath: payload}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	write(t, target, "external-change")
	if _, err := DiscardPrepared(prepared.JournalPath); err == nil {
		t.Fatal("discard accepted a changed game target")
	}
	if read(t, target) != "external-change" {
		t.Fatal("failed discard overwrote external change")
	}
}

func TestPrepareUsesVerifiedPersistentBaselineBackup(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload", "A.PAK")
	persistent := filepath.Join(root, "baseline", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")
	write(t, persistent, "original")
	if err := os.Chmod(persistent, 0o444); err != nil {
		t.Fatal(err)
	}
	prepared, err := Prepare(game, state, []ChangeSpec{{
		RelativePath:       "Data/A.PAK",
		StagedPath:         payload,
		VerifiedBackupPath: persistent,
	}}, nil, map[string]string{"baseline_id": "test"})
	if err != nil {
		t.Fatal(err)
	}
	backup := filepath.Join(prepared.Journal.TransactionRoot, filepath.FromSlash(prepared.Journal.Files[0].BackupPath))
	if read(t, backup) != "original" {
		t.Fatal("transaction backup did not use the verified baseline content")
	}
	if read(t, target) != "original" {
		t.Fatal("prepare modified the game file")
	}
	if _, err := DiscardPrepared(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if read(t, persistent) != "original" {
		t.Fatal("discard modified the persistent baseline")
	}
}

func TestPrepareRejectsMismatchedPersistentBaseline(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload", "A.PAK")
	persistent := filepath.Join(root, "baseline", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")
	write(t, persistent, "different")
	if _, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{
		RelativePath:       "Data/A.PAK",
		StagedPath:         payload,
		VerifiedBackupPath: persistent,
	}}, nil, nil); err == nil {
		t.Fatal("mismatched persistent baseline was accepted")
	}
}

func TestPrepareRejectsAnalyticalPAKSibling(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, payload, "patched")
	if _, err := Prepare(game, filepath.Join(root, "state"), []ChangeSpec{{
		RelativePath: "DATA/PACK00_02.PAK_", StagedPath: payload,
	}}, nil, nil); err == nil {
		t.Fatal("transaction accepted preserved analytical .PAK_ target")
	}
}

func TestCopyRegularFileVerifiedRejectsWrongHashAndRemovesDestination(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "source")
	destination := filepath.Join(root, "destination")
	write(t, source, "payload")
	if err := copyRegularFileVerified(source, destination, 0o644, "0000000000000000000000000000000000000000000000000000000000000000"); err == nil {
		t.Fatal("expected verified copy hash mismatch")
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Fatal("failed verified copy retained destination")
	}
}

func TestCommitAndRollbackReportByteProgress(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original-progress-data")
	write(t, payload, "patched-progress-data-with-more-bytes")
	prepared, err := Prepare(game, state, []ChangeSpec{{RelativePath: "Data/A.PAK", StagedPath: payload}}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	var commitEvents []ProgressEvent
	if _, err := CommitWithProgress(prepared.JournalPath, func(event ProgressEvent) {
		commitEvents = append(commitEvents, event)
	}); err != nil {
		t.Fatal(err)
	}
	assertProgressComplete(t, commitEvents, "commit", "Data/A.PAK")

	var rollbackEvents []ProgressEvent
	if _, err := RollbackWithProgress(prepared.JournalPath, func(event ProgressEvent) {
		rollbackEvents = append(rollbackEvents, event)
	}); err != nil {
		t.Fatal(err)
	}
	assertProgressComplete(t, rollbackEvents, "rollback", "Data/A.PAK")
	for _, event := range rollbackEvents {
		if event.Phase == "verify_backup" && event.FileBytesTotal != 0 {
			t.Fatalf("rollback still performs a redundant full backup verification pass: %+v", event)
		}
	}
	if got := read(t, target); got != "original-progress-data" {
		t.Fatalf("rollback restored %q", got)
	}
}

func assertProgressComplete(t *testing.T, events []ProgressEvent, operation, relativePath string) {
	t.Helper()
	if len(events) == 0 {
		t.Fatalf("%s did not emit progress", operation)
	}
	seenPath := false
	seenPositiveTotal := false
	for _, event := range events {
		if event.Operation != operation {
			t.Fatalf("unexpected progress operation %q", event.Operation)
		}
		if event.RelativePath == relativePath {
			seenPath = true
		}
		if event.OverallBytesTotal > 0 {
			seenPositiveTotal = true
		}
		if event.OverallBytesDone > event.OverallBytesTotal && event.OverallBytesTotal > 0 {
			t.Fatalf("progress exceeded total: %+v", event)
		}
	}
	last := events[len(events)-1]
	if last.Phase != "complete" || last.OverallBytesDone != last.OverallBytesTotal {
		t.Fatalf("%s progress did not finish: %+v", operation, last)
	}
	if !seenPath || !seenPositiveTotal {
		t.Fatalf("%s progress lacks path or byte totals: %+v", operation, events)
	}
}

func TestPrepareWithProgressReportsByteAccuratePhases(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(game, "Data", "A.PAK"), "original-a")
	write(t, filepath.Join(payload, "A.PAK"), "patched-a-with-more-bytes")

	var events []ProgressEvent
	prepared, err := PrepareWithProgress(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   filepath.Join(payload, "A.PAK"),
	}}, []string{"quartet_legacy_dlc"}, map[string]string{"target_id": "blue_reflection_quartet"}, func(event ProgressEvent) {
		events = append(events, event)
	})
	if err != nil {
		t.Fatal(err)
	}
	if prepared.Journal.Status != StatusPrepared {
		t.Fatalf("unexpected prepared status: %s", prepared.Journal.Status)
	}
	if len(events) == 0 {
		t.Fatal("prepare progress emitted no events")
	}
	seen := map[string]bool{}
	for _, event := range events {
		if event.Operation != "prepare" {
			t.Fatalf("unexpected operation %q", event.Operation)
		}
		if event.RelativePath != "Data/A.PAK" {
			t.Fatalf("unexpected path %q", event.RelativePath)
		}
		if event.OverallBytesDone < 0 || event.OverallBytesTotal < 0 || event.OverallBytesDone > event.OverallBytesTotal {
			t.Fatalf("invalid overall progress: %+v", event)
		}
		seen[event.Phase] = true
	}
	for _, phase := range []string{"verify_candidate", "stage", "verify_staged", "verify_current", "verify_backup_source", "backup", "verify_backup", "complete"} {
		if !seen[phase] {
			t.Fatalf("missing prepare phase %q", phase)
		}
	}
	last := events[len(events)-1]
	if last.Phase != "complete" || last.OverallBytesDone != last.OverallBytesTotal {
		t.Fatalf("prepare progress did not finish at 100%%: %+v", last)
	}
}

func TestPrepareCanKeepHardlinkBackupsOnGameFilesystem(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")

	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   payload,
	}}, []string{"quartet_legacy_dlc"}, nil, PrepareOptions{
		RequireHardlinkBackup:        true,
		UseGameFilesystemBackupStore: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if prepared.Journal.BackupRoot == "" {
		t.Fatal("external backup root was not recorded")
	}
	expectedRoot := filepath.Join(game, ".unburger-patcher", "transaction-backups", prepared.Journal.TransactionID)
	if prepared.Journal.BackupRoot != expectedRoot {
		t.Fatalf("backup root = %q, expected %q", prepared.Journal.BackupRoot, expectedRoot)
	}
	record := prepared.Journal.Files[0]
	if record.BackupStorageMethod != "hardlink" {
		t.Fatalf("backup storage method = %q", record.BackupStorageMethod)
	}
	backup := filepath.Join(prepared.Journal.BackupRoot, filepath.FromSlash(record.BackupPath))
	backupInfo, err := os.Stat(backup)
	if err != nil {
		t.Fatal(err)
	}
	targetInfo, err := os.Stat(target)
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(backupInfo, targetInfo) {
		t.Fatal("backup is not a hardlink to the original target")
	}
	if _, err := ValidatePrepared(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := DiscardPrepared(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(expectedRoot); !os.IsNotExist(err) {
		t.Fatal("discard retained game-filesystem backup root")
	}
	if got := read(t, target); got != "original" {
		t.Fatalf("discard changed target to %q", got)
	}
}

func TestLoadRejectsTamperedExternalBackupRoot(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	write(t, filepath.Join(game, "Data", "A.PAK"), "original")
	write(t, payload, "patched")
	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   payload,
	}}, nil, nil, PrepareOptions{UseGameFilesystemBackupStore: true})
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	var journal Journal
	if err := json.Unmarshal(data, &journal); err != nil {
		t.Fatal(err)
	}
	journal.BackupRoot = filepath.Join(root, "unrelated")
	data, err = json.MarshalIndent(journal, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(prepared.JournalPath, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Load(prepared.JournalPath); err == nil {
		t.Fatal("tampered backup root was accepted")
	}
}

func TestGameFilesystemBackupSupportsCommitAndRollback(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")

	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   payload,
	}}, []string{"quartet_legacy_dlc"}, nil, PrepareOptions{
		RequireHardlinkBackup:        true,
		UseGameFilesystemBackupStore: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if got := read(t, target); got != "patched" {
		t.Fatalf("commit installed %q", got)
	}
	journal, err := Rollback(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusRolledBack {
		t.Fatalf("rollback status = %q", journal.Status)
	}
	if got := read(t, target); got != "original" {
		t.Fatalf("rollback restored %q", got)
	}
}

func TestPrepareCanKeepHardlinkBackupsBesideGameRoot(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "games", "Quartet")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")

	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   payload,
	}}, []string{"quartet_legacy_dlc"}, nil, PrepareOptions{
		RequireHardlinkBackup:           true,
		UseSiblingFilesystemBackupStore: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	expectedRoot := siblingFilesystemBackupRoot(game, prepared.Journal.TransactionID)
	if prepared.Journal.BackupRoot != expectedRoot {
		t.Fatalf("backup root = %q, expected %q", prepared.Journal.BackupRoot, expectedRoot)
	}
	if strings.HasPrefix(filepath.Clean(prepared.Journal.BackupRoot)+string(os.PathSeparator), filepath.Clean(game)+string(os.PathSeparator)) {
		t.Fatal("sibling backup store was placed inside game root")
	}
	record := prepared.Journal.Files[0]
	if record.BackupStorageMethod != "hardlink" {
		t.Fatalf("backup storage method = %q", record.BackupStorageMethod)
	}
	backup := filepath.Join(prepared.Journal.BackupRoot, filepath.FromSlash(record.BackupPath))
	backupInfo, err := os.Stat(backup)
	if err != nil {
		t.Fatal(err)
	}
	targetInfo, err := os.Stat(target)
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(backupInfo, targetInfo) {
		t.Fatal("sibling backup is not a hardlink to the original target")
	}
	if _, err := ValidatePrepared(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := DiscardPrepared(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(expectedRoot); !os.IsNotExist(err) {
		t.Fatal("discard retained sibling backup root")
	}
	if got := read(t, target); got != "original" {
		t.Fatalf("discard changed target to %q", got)
	}
}

func TestSiblingFilesystemBackupSupportsCommitAndRollback(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "games", "Quartet")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched")

	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK",
		StagedPath:   payload,
	}}, []string{"quartet_legacy_dlc"}, nil, PrepareOptions{
		RequireHardlinkBackup:           true,
		UseSiblingFilesystemBackupStore: true,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if got := read(t, target); got != "patched" {
		t.Fatalf("commit installed %q", got)
	}
	journal, err := Rollback(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusRolledBack {
		t.Fatalf("rollback status = %q", journal.Status)
	}
	if got := read(t, target); got != "original" {
		t.Fatalf("rollback restored %q", got)
	}
}

func TestPruneCommittedStagedRemovesOnlyDesiredPayload(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	stagedSource := filepath.Join(root, "candidate.bin")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "PACK.PAK")
	if err := os.WriteFile(target, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stagedSource, []byte("desired"), 0o644); err != nil {
		t.Fatal(err)
	}
	prepared, err := Prepare(game, state, []ChangeSpec{{RelativePath: "PACK.PAK", StagedPath: stagedSource}}, []string{"translation"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	committed, err := Commit(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if committed.Status != StatusCommitted {
		t.Fatalf("unexpected status: %s", committed.Status)
	}
	stagedDir := filepath.Join(committed.TransactionRoot, "staged")
	if _, err := os.Stat(stagedDir); err != nil {
		t.Fatalf("staged payload missing before prune: %v", err)
	}
	backupPath := filepath.Join(committed.TransactionRoot, filepath.FromSlash(committed.Files[0].BackupPath))
	if _, err := os.Stat(backupPath); err != nil {
		t.Fatalf("backup missing before prune: %v", err)
	}
	if err := PruneCommittedStaged(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stagedDir); !os.IsNotExist(err) {
		t.Fatalf("committed staged payload survived prune: %v", err)
	}
	if _, err := os.Stat(backupPath); err != nil {
		t.Fatalf("rollback backup was removed by prune: %v", err)
	}
}

func TestPrepareTrustedCandidateSkipsRedundantRereadsButCommitStillChecksBytes(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "A.PAK")
	target := filepath.Join(game, "Data", "A.PAK")
	write(t, target, "original")
	write(t, payload, "patched-candidate")
	desired, err := hashFile(payload)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(payload)
	if err != nil {
		t.Fatal(err)
	}
	var events []ProgressEvent
	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK", StagedPath: payload,
		DesiredSHA256: desired, DesiredBytes: info.Size(),
	}}, []string{"translation"}, nil, PrepareOptions{Progress: func(event ProgressEvent) {
		events = append(events, event)
	}})
	if err != nil {
		t.Fatal(err)
	}
	for _, phase := range []string{"verify_candidate", "verify_staged", "verify_backup"} {
		seen := false
		for _, event := range events {
			if event.Phase == phase {
				seen = true
				if event.FileBytesTotal != 0 {
					t.Fatalf("redundant phase %s still accounts for a full payload read: %+v", phase, event)
				}
			}
		}
		if !seen {
			t.Fatalf("progress did not report skipped phase %s", phase)
		}
	}
	privateStaged := filepath.Join(prepared.Journal.TransactionRoot, filepath.FromSlash(prepared.Journal.Files[0].StagedPath))
	if err := os.WriteFile(privateStaged, []byte("tampered-candidate"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(prepared.JournalPath); err == nil {
		t.Fatal("commit accepted staged bytes changed after the trusted prepare handoff")
	}
}

func TestRollbackRestoresReadOnlyOriginalWithoutReadOnlyResync(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(game, "B1.dll")
	write(t, target, "read-only-original")
	if err := os.Chmod(target, 0o444); err != nil {
		t.Fatal(err)
	}
	write(t, payload, "patched-dll")
	prepared, err := Prepare(game, state, []ChangeSpec{{RelativePath: "B1.dll", StagedPath: payload}}, []string{"quartet_legacy_dlc"}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := Rollback(prepared.JournalPath); err != nil {
		t.Fatalf("rollback of read-only original failed: %v", err)
	}
	if got := read(t, target); got != "read-only-original" {
		t.Fatalf("rollback restored %q", got)
	}
}

func TestPrepareExpectedOriginalHashUsesExistingCurrentPass(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "Data", "A.PAK")
	payload := filepath.Join(root, "payload", "A.PAK")
	write(t, target, "installed-v1")
	write(t, payload, "installed-v2")
	expected, err := hashFile(target)
	if err != nil {
		t.Fatal(err)
	}

	var events []ProgressEvent
	prepared, err := PrepareWithOptions(game, state, []ChangeSpec{{
		RelativePath: "Data/A.PAK", StagedPath: payload, ExpectedOriginalSHA256: expected,
	}}, []string{"translation"}, nil, PrepareOptions{Progress: func(event ProgressEvent) {
		events = append(events, event)
	}})
	if err != nil {
		t.Fatal(err)
	}
	if prepared.Journal.Files[0].OriginalSHA256 != expected {
		t.Fatalf("prepared original hash=%s want=%s", prepared.Journal.Files[0].OriginalSHA256, expected)
	}
	verifyCurrentPasses := 0
	for _, event := range events {
		if event.Phase == "verify_current" && event.FileBytesTotal > 0 {
			verifyCurrentPasses++
		}
	}
	if verifyCurrentPasses == 0 {
		t.Fatal("expected-current guard did not reuse the normal verify_current pass")
	}

	write(t, target, "external-change")
	if _, err := PrepareWithOptions(game, filepath.Join(root, "state2"), []ChangeSpec{{
		RelativePath: "Data/A.PAK", StagedPath: payload, ExpectedOriginalSHA256: expected,
	}}, []string{"translation"}, nil, PrepareOptions{}); err == nil || !strings.Contains(err.Error(), "managed target changed before update") {
		t.Fatalf("externally changed managed target was not rejected: %v", err)
	}
}
