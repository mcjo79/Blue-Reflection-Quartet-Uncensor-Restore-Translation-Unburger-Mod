package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestNewPublicWorkRootRemovesOnlyRegenerablePersistentPayloadsAndCleansCurrentRun(t *testing.T) {
	t.Setenv("UNBURGER_WORK_ROOT", filepath.Join(t.TempDir(), "work"))
	installations := t.TempDir()
	stateDir := filepath.Join(installations, "current")
	oldInstall := filepath.Join(installations, "old-installation-id")

	write := func(path, value string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	write(filepath.Join(stateDir, "builds", "br1-source-content", "large.bin"), "old-current-build")
	write(filepath.Join(oldInstall, "builds", "translation", "large.bin"), "old-other-build")
	write(filepath.Join(stateDir, "baselines", ".tmp-dead", "files", "large.bin"), "stale-baseline-temp")

	committed := filepath.Join(stateDir, "transactions", "committed")
	write(filepath.Join(committed, "journal.json"), `{"status":"committed"}`)
	write(filepath.Join(committed, "staged", "large.bin"), "obsolete-staged")
	write(filepath.Join(committed, "backup", "keep.bin"), "rollback-backup")

	prepared := filepath.Join(stateDir, "transactions", "prepared")
	write(filepath.Join(prepared, "journal.json"), `{"status":"prepared"}`)
	write(filepath.Join(prepared, "staged", "keep.bin"), "recovery-staged")

	root, cleanup, err := newPublicWorkRoot(stateDir, "unburger-test-")
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		filepath.Join(stateDir, "builds"),
		filepath.Join(oldInstall, "builds"),
		filepath.Join(stateDir, "baselines", ".tmp-dead"),
		filepath.Join(committed, "staged"),
	} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("regenerable persistent payload survived: %s: %v", path, err)
		}
	}
	for _, path := range []string{
		filepath.Join(committed, "backup", "keep.bin"),
		filepath.Join(prepared, "staged", "keep.bin"),
	} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("recovery data was removed: %s: %v", path, err)
		}
	}
	write(filepath.Join(root, "current.bin"), "current")
	cleanup()
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatalf("current transient workspace survived cleanup: %v", err)
	}
}

func TestNewGameScopedPublicWorkRootUsesSiblingFilesystemAndCleansStaleBuilds(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "games", "Quartet")
	stateDir := filepath.Join(root, "state", "installation")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	workParent := filepath.Join(filepath.Dir(game), ".unburger-patcher-work", filepath.Base(game))
	stale := filepath.Join(workParent, "old-run", "candidate.bin")
	if err := os.MkdirAll(filepath.Dir(stale), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(stale, []byte("stale"), 0o644); err != nil {
		t.Fatal(err)
	}

	workspaceRoot, cleanup, err := newGameScopedPublicWorkRootWithStatus(game, stateDir, "run-", nil)
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Dir(workspaceRoot) != workParent {
		t.Fatalf("workspace root = %q, expected child of %q", workspaceRoot, workParent)
	}
	if _, err := os.Stat(filepath.Join(workParent, "old-run")); !os.IsNotExist(err) {
		t.Fatalf("stale build-only workspace survived: %v", err)
	}
	candidate := filepath.Join(workspaceRoot, "candidate.bin")
	if err := os.WriteFile(candidate, []byte("candidate"), 0o644); err != nil {
		t.Fatal(err)
	}
	cleanup()
	if _, err := os.Stat(workspaceRoot); !os.IsNotExist(err) {
		t.Fatalf("current game-scoped workspace survived cleanup: %v", err)
	}
}
