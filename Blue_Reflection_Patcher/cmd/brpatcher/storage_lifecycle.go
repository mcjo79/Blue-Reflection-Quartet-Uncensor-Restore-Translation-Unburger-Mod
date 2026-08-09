package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type storageStateRef struct {
	TransactionID        string `json:"transaction_id"`
	BaselineManifestPath string `json:"baseline_manifest_path"`
	PreviousStatePath    string `json:"previous_state_path"`
}

type storageJournalRef struct {
	TransactionID string            `json:"transaction_id"`
	Status        string            `json:"status"`
	GameRoot      string            `json:"game_root"`
	BackupRoot    string            `json:"backup_root"`
	Metadata      map[string]string `json:"metadata"`
}

type storageLifecycleReport struct {
	RemovedTrees int
}

// compactInstallationStorage keeps only payloads that can still participate in
// deterministic recovery. Large baseline/transaction bytes that are no longer
// reachable from the active state chain or an interrupted transaction are
// deleted; tiny journals and state history remain as diagnostics.
func compactInstallationStorage(stateDir string) (storageLifecycleReport, error) {
	var report storageLifecycleReport
	stateDir, err := filepath.Abs(stateDir)
	if err != nil {
		return report, err
	}
	protectedTransactions := map[string]bool{}
	protectedBaselines := map[string]bool{}
	activeExists := false

	activePath := filepath.Join(stateDir, "active_state.json")
	if _, err := os.Stat(activePath); err == nil {
		activeExists = true
		seen := map[string]bool{}
		path := activePath
		for depth := 0; depth < 1024 && strings.TrimSpace(path) != ""; depth++ {
			absolute, err := filepath.Abs(path)
			if err != nil {
				return report, err
			}
			if seen[absolute] {
				return report, fmt.Errorf("active state history contains a cycle: %s", absolute)
			}
			seen[absolute] = true
			state, err := readStorageStateRef(absolute)
			if err != nil {
				return report, err
			}
			if strings.TrimSpace(state.TransactionID) != "" {
				protectedTransactions[state.TransactionID] = true
			}
			if strings.TrimSpace(state.BaselineManifestPath) != "" {
				baselinePath, err := filepath.Abs(state.BaselineManifestPath)
				if err != nil {
					return report, err
				}
				protectedBaselines[filepath.Clean(baselinePath)] = true
			}
			path = strings.TrimSpace(state.PreviousStatePath)
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return report, fmt.Errorf("inspect active state for storage cleanup: %w", err)
	}

	transactionsRoot := filepath.Join(stateDir, "transactions")
	entries, err := os.ReadDir(transactionsRoot)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return report, fmt.Errorf("list transaction state for storage cleanup: %w", err)
	}
	journals := map[string]storageJournalRef{}
	journalRoots := map[string]string{}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		txRoot := filepath.Join(transactionsRoot, entry.Name())
		journal, readErr := readStorageJournalRef(filepath.Join(txRoot, "journal.json"))
		if readErr != nil {
			// Unknown/corrupt state is preserved fail-closed.
			continue
		}
		status := strings.TrimSpace(journal.Status)
		if status == "committed" || status == "rolled_back" || status == "discarded" {
			if err := removeTreeIfPresent(filepath.Join(txRoot, "staged"), &report); err != nil {
				return report, err
			}
		}
		id := strings.TrimSpace(journal.TransactionID)
		if id == "" || id != entry.Name() {
			continue
		}
		journals[id] = journal
		journalRoots[id] = txRoot
		switch strings.TrimSpace(journal.Status) {
		case "prepared", "committing", "rolling_back":
			protectedTransactions[id] = true
		case "committed":
			// A committed transaction without active_state may be between game-file
			// commit and state publication. Preserve it for deterministic recovery.
			if !activeExists {
				protectedTransactions[id] = true
			}
		case "rolled_back", "discarded":
			// terminal, no payload required
		default:
			protectedTransactions[id] = true
		}
		if protectedTransactions[id] {
			if path := strings.TrimSpace(journal.Metadata["baseline_manifest_path"]); path != "" {
				absolute, absErr := filepath.Abs(path)
				if absErr != nil {
					return report, absErr
				}
				protectedBaselines[filepath.Clean(absolute)] = true
			}
		}
	}

	for id, journal := range journals {
		txRoot := journalRoots[id]
		status := strings.TrimSpace(journal.Status)
		if status == "committed" {
			if err := removeTreeIfPresent(filepath.Join(txRoot, "staged"), &report); err != nil {
				return report, err
			}
		}
		if protectedTransactions[id] {
			continue
		}
		if err := removeTreeIfPresent(filepath.Join(txRoot, "staged"), &report); err != nil {
			return report, err
		}
		if err := removeTreeIfPresent(filepath.Join(txRoot, "backup"), &report); err != nil {
			return report, err
		}
		if root := strings.TrimSpace(journal.BackupRoot); root != "" && trustedTransactionBackupRoot(journal.GameRoot, id, root) {
			if err := removeTreeIfPresent(root, &report); err != nil {
				return report, err
			}
		}
	}

	baselinesRoot := filepath.Join(stateDir, "baselines")
	baselineEntries, err := os.ReadDir(baselinesRoot)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return report, fmt.Errorf("list baseline state for storage cleanup: %w", err)
	}
	removedBaseline := false
	for _, entry := range baselineEntries {
		if !entry.IsDir() {
			continue
		}
		root := filepath.Join(baselinesRoot, entry.Name())
		if strings.HasPrefix(entry.Name(), ".tmp-") {
			if err := removeTreeIfPresent(root, &report); err != nil {
				return report, err
			}
			removedBaseline = true
			continue
		}
		manifestPath, err := filepath.Abs(filepath.Join(root, "manifest.json"))
		if err != nil {
			return report, err
		}
		if protectedBaselines[filepath.Clean(manifestPath)] {
			// v2 baselines store their bytes on the game filesystem; any local
			// files/ directory is therefore an obsolete pre-v2 duplicate.
			var header struct {
				FormatVersion int    `json:"format_version"`
				StorageRoot   string `json:"storage_root"`
			}
			if data, readErr := os.ReadFile(manifestPath); readErr == nil && json.Unmarshal(data, &header) == nil && header.FormatVersion >= 2 && strings.TrimSpace(header.StorageRoot) != "" {
				if err := removeTreeIfPresent(filepath.Join(root, "files"), &report); err != nil {
					return report, err
				}
			}
			continue
		}
		if err := removeTreeIfPresent(root, &report); err != nil {
			return report, err
		}
		removedBaseline = true
	}
	if removedBaseline {
		_ = os.Remove(filepath.Join(baselinesRoot, "index.json"))
	}
	if err := os.RemoveAll(filepath.Join(stateDir, "builds")); err != nil {
		return report, fmt.Errorf("remove obsolete persistent build workspace: %w", err)
	}
	return report, nil
}

func readStorageStateRef(path string) (storageStateRef, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return storageStateRef{}, err
	}
	var state storageStateRef
	if err := json.Unmarshal(data, &state); err != nil {
		return storageStateRef{}, fmt.Errorf("decode state reference %s: %w", path, err)
	}
	return state, nil
}

func readStorageJournalRef(path string) (storageJournalRef, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return storageJournalRef{}, err
	}
	var journal storageJournalRef
	if err := json.Unmarshal(data, &journal); err != nil {
		return storageJournalRef{}, err
	}
	return journal, nil
}

func removeTreeIfPresent(path string, report *storageLifecycleReport) error {
	if strings.TrimSpace(path) == "" {
		return nil
	}
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		return nil
	} else if err != nil {
		return err
	}
	if err := os.RemoveAll(path); err != nil {
		return err
	}
	report.RemovedTrees++
	return nil
}

func trustedTransactionBackupRoot(gameRoot, transactionID, candidate string) bool {
	if strings.TrimSpace(gameRoot) == "" || strings.TrimSpace(transactionID) == "" || strings.TrimSpace(candidate) == "" {
		return false
	}
	gameAbs, err := filepath.Abs(gameRoot)
	if err != nil {
		return false
	}
	candidateAbs, err := filepath.Abs(candidate)
	if err != nil {
		return false
	}
	expected := []string{
		filepath.Join(gameAbs, ".unburger-patcher", "transaction-backups", transactionID),
		filepath.Join(filepath.Dir(gameAbs), ".unburger-patcher-transaction-backups", filepath.Base(gameAbs), transactionID),
	}
	for _, path := range expected {
		absolute, err := filepath.Abs(path)
		if err == nil && filepath.Clean(absolute) == filepath.Clean(candidateAbs) {
			return true
		}
	}
	return false
}
