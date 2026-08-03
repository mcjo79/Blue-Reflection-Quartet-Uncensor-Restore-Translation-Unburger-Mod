package transaction

import (
	"os"
	"path/filepath"
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
	journal, err := Commit(prepared.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != StatusCommitted || read(t, filepath.Join(game, "Data", "A.PAK")) != "patched-a" || read(t, filepath.Join(game, "Data", "B.PAK")) != "new-b" {
		t.Fatalf("commit result is invalid: %+v", journal)
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
