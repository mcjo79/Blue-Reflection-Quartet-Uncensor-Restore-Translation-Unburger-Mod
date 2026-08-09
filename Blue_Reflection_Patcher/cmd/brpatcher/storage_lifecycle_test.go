package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestCompactInstallationStoragePrunesTerminalPayloadsAndUnreferencedBaselines(t *testing.T) {
	root := t.TempDir()
	state := filepath.Join(root, "state")
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	id := "20260809T120000Z-deadbeef0001"
	txRoot := filepath.Join(state, "transactions", id)
	external := filepath.Join(filepath.Dir(game), ".unburger-patcher-transaction-backups", filepath.Base(game), id)
	writeStorageFixture(t, filepath.Join(txRoot, "staged", "large.bin"), "staged")
	writeStorageFixture(t, filepath.Join(txRoot, "backup", "large.bin"), "legacy-backup")
	writeStorageFixture(t, filepath.Join(external, "backup", "Data", "PACK.PAK"), "external-backup")
	journal := storageJournalRef{TransactionID: id, Status: "rolled_back", GameRoot: game, BackupRoot: external, Metadata: map[string]string{}}
	writeStorageJSON(t, filepath.Join(txRoot, "journal.json"), journal)
	orphanBaseline := filepath.Join(state, "baselines", "orphan", "files", "Data", "PACK.PAK")
	writeStorageFixture(t, orphanBaseline, "old-appdata-baseline")

	report, err := compactInstallationStorage(state)
	if err != nil {
		t.Fatal(err)
	}
	if report.RemovedTrees == 0 {
		t.Fatal("storage cleanup reported no removals")
	}
	for _, path := range []string{
		filepath.Join(txRoot, "staged"), filepath.Join(txRoot, "backup"), external,
		filepath.Join(state, "baselines", "orphan"),
	} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("obsolete payload survived: %s: %v", path, err)
		}
	}
	if _, err := os.Stat(filepath.Join(txRoot, "journal.json")); err != nil {
		t.Fatalf("tiny diagnostic journal should remain: %v", err)
	}
}

func TestCompactInstallationStoragePreservesActiveRollbackChain(t *testing.T) {
	root := t.TempDir()
	state := filepath.Join(root, "state")
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	activeID := "20260809T120000Z-active000001"
	oldID := "20260809T120000Z-old000000001"
	activeBaseline := filepath.Join(state, "baselines", "active", "manifest.json")
	orphanBaseline := filepath.Join(state, "baselines", "orphan", "manifest.json")
	activeBackup := filepath.Join(filepath.Dir(game), ".unburger-patcher-transaction-backups", filepath.Base(game), activeID)
	oldBackup := filepath.Join(filepath.Dir(game), ".unburger-patcher-transaction-backups", filepath.Base(game), oldID)

	writeStorageJSON(t, filepath.Join(state, "active_state.json"), storageStateRef{TransactionID: activeID, BaselineManifestPath: activeBaseline})
	writeStorageJSON(t, activeBaseline, map[string]any{"format_version": 2, "storage_root": activeBackup})
	writeStorageFixture(t, filepath.Join(filepath.Dir(activeBaseline), "files", "obsolete-local-copy.bin"), "duplicate")
	writeStorageJSON(t, orphanBaseline, map[string]any{"format_version": 1})
	writeStorageFixture(t, filepath.Join(filepath.Dir(orphanBaseline), "files", "large.bin"), "orphan")

	activeTx := filepath.Join(state, "transactions", activeID)
	writeStorageJSON(t, filepath.Join(activeTx, "journal.json"), storageJournalRef{TransactionID: activeID, Status: "committed", GameRoot: game, BackupRoot: activeBackup, Metadata: map[string]string{"baseline_manifest_path": activeBaseline}})
	writeStorageFixture(t, filepath.Join(activeTx, "staged", "large.bin"), "obsolete-staged")
	writeStorageFixture(t, filepath.Join(activeBackup, "backup", "Data", "PACK.PAK"), "keep-active-rollback")

	oldTx := filepath.Join(state, "transactions", oldID)
	writeStorageJSON(t, filepath.Join(oldTx, "journal.json"), storageJournalRef{TransactionID: oldID, Status: "committed", GameRoot: game, BackupRoot: oldBackup, Metadata: map[string]string{"baseline_manifest_path": orphanBaseline}})
	writeStorageFixture(t, filepath.Join(oldTx, "staged", "large.bin"), "obsolete-staged")
	writeStorageFixture(t, filepath.Join(oldBackup, "backup", "Data", "PACK.PAK"), "obsolete-backup")

	if _, err := compactInstallationStorage(state); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(activeBackup); err != nil {
		t.Fatalf("active rollback data was removed: %v", err)
	}
	if _, err := os.Stat(activeBaseline); err != nil {
		t.Fatalf("active baseline manifest was removed: %v", err)
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(activeBaseline), "files")); !os.IsNotExist(err) {
		t.Fatalf("obsolete local duplicate beside v2 baseline survived: %v", err)
	}
	for _, path := range []string{filepath.Join(activeTx, "staged"), oldBackup, filepath.Dir(orphanBaseline)} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("superseded payload survived: %s: %v", path, err)
		}
	}
}

func writeStorageFixture(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
		t.Fatal(err)
	}
}

func writeStorageJSON(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	writeStorageFixture(t, path, string(data))
}
