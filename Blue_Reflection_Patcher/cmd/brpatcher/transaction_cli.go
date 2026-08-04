package main

import (
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

type transactionSelfTestReport struct {
	Type                            string `json:"type"`
	FormatVersion                   int    `json:"format_version"`
	Status                          string `json:"status"`
	TransactionID                   string `json:"transaction_id"`
	PreparedWithoutGameEdit         bool   `json:"prepared_without_game_edit"`
	ExistingFileCommitted           bool   `json:"existing_file_committed"`
	NewFileCommitted                bool   `json:"new_file_committed"`
	OriginalFileRestored            bool   `json:"original_file_restored"`
	AddedFileRemoved                bool   `json:"added_file_removed"`
	FinalJournalStatus              string `json:"final_journal_status"`
	PersistentBaselineCreated       bool   `json:"persistent_baseline_created"`
	ActiveStateRecorded             bool   `json:"active_state_recorded"`
	ActiveStateMatchedInstalled     bool   `json:"active_state_matched_installed"`
	ActiveStateClearedAfterRollback bool   `json:"active_state_cleared_after_rollback"`
	JournalPolicy                   string `json:"journal_policy"`
	BackupPolicy                    string `json:"backup_policy"`
	ConflictPolicy                  string `json:"conflict_policy"`
	TestScope                       string `json:"test_scope"`
}

func printTransactionFoundation(out io.Writer, result model.SelectionResult) error {
	base, err := stateRoot()
	if err != nil {
		return err
	}
	fmt.Fprintln(out, "\nTransaction safety model:")
	for _, target := range result.Targets {
		state := installationStateDirectory(base, target.TargetID, target.Root)
		fmt.Fprintf(out, "  %s\n", target.DisplayName)
		fmt.Fprintf(out, "    state:   %s\n", state)
		fmt.Fprintf(out, "    baseline:%s\n", filepath.Join(state, "baselines", "<fingerprint>", "manifest.json"))
		fmt.Fprintf(out, "    active:  %s\n", filepath.Join(state, "active_state.json"))
		fmt.Fprintf(out, "    journal: %s\n", filepath.Join(state, "transactions", "<transaction-id>", "journal.json"))
		fmt.Fprintf(out, "    backup:  %s\n", filepath.Join(state, "transactions", "<transaction-id>", "backup"))
	}
	fmt.Fprintln(out, "  Policy: preserve versioned observed baseline -> classify active installed state -> stage and verify -> transaction backup -> atomic commit -> hash-guarded rollback")
	fmt.Fprintln(out, "  Interrupted transactions remain journaled for deterministic recovery.")
	return nil
}

func installationStateDirectory(base, targetID, gameRoot string) string {
	absolute, err := filepath.Abs(gameRoot)
	if err != nil {
		absolute = filepath.Clean(gameRoot)
	}
	hash := sha256.Sum256([]byte(filepath.Clean(absolute)))
	key := hex.EncodeToString(hash[:8])
	return filepath.Join(base, "unburger-patcher", "blue-reflection", "installations", targetID+"-"+key)
}

func commandTransactionSelfTest(args []string) error {
	flags := flag.NewFlagSet("transaction-self-test", flag.ContinueOnError)
	var workDir, output string
	flags.StringVar(&workDir, "work-dir", "", "parent directory for an isolated synthetic transaction")
	flags.StringVar(&output, "json", "", "write self-test report to this JSON file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if workDir == "" {
		return fmt.Errorf("--work-dir is required")
	}
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return err
	}
	testRoot, err := os.MkdirTemp(workDir, "br-transaction-self-test-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(testRoot)
	game := filepath.Join(testRoot, "game")
	state := filepath.Join(testRoot, "state")
	payload := filepath.Join(testRoot, "payload")
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		return err
	}
	if err := os.MkdirAll(payload, 0o755); err != nil {
		return err
	}
	existing := filepath.Join(game, "Data", "EXISTING.PAK")
	added := filepath.Join(game, "Data", "ADDED.PAK")
	stagedExisting := filepath.Join(payload, "EXISTING.PAK")
	stagedAdded := filepath.Join(payload, "ADDED.PAK")
	for path, value := range map[string]string{
		existing: "original", stagedExisting: "patched", stagedAdded: "added",
	} {
		if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
			return err
		}
	}
	base, err := baseline.Ensure(game, state, "synthetic_quartet", []string{"Data/EXISTING.PAK", "Data/ADDED.PAK"})
	if err != nil {
		return err
	}
	prepared, err := transaction.Prepare(game, state, []transaction.ChangeSpec{
		{RelativePath: "Data/EXISTING.PAK", StagedPath: stagedExisting, VerifiedBackupPath: base.StoredFiles["Data/EXISTING.PAK"]},
		{RelativePath: "Data/ADDED.PAK", StagedPath: stagedAdded},
	}, []string{"blue_reflection_translation", "quartet_restoration"}, map[string]string{
		"target_id": "synthetic_quartet", "purpose": "validation_only",
		"baseline_manifest_path": base.ManifestPath,
	})
	if err != nil {
		return err
	}
	originalAfterPrepare, err := os.ReadFile(existing)
	if err != nil {
		return err
	}
	_, addedAfterPrepareErr := os.Stat(added)
	preparedClean := string(originalAfterPrepare) == "original" && os.IsNotExist(addedAfterPrepareErr)
	committed, err := transaction.Commit(prepared.JournalPath)
	if err != nil {
		return err
	}
	active, err := installstate.Activate(state, "synthetic_quartet", game, base.ManifestPath, prepared.JournalPath)
	if err != nil {
		return err
	}
	activeInspection, err := installstate.Inspect(state, "synthetic_quartet", game)
	if err != nil {
		return err
	}
	committedExisting, err := os.ReadFile(existing)
	if err != nil {
		return err
	}
	committedAdded, err := os.ReadFile(added)
	if err != nil {
		return err
	}
	rolledBack, err := transaction.Rollback(prepared.JournalPath)
	if err != nil {
		return err
	}
	_, activeAfterRollback, err := installstate.ReconcileRollback(state, "synthetic_quartet", game, prepared.JournalPath)
	if err != nil {
		return err
	}
	finalExisting, err := os.ReadFile(existing)
	if err != nil {
		return err
	}
	_, finalAddedErr := os.Stat(added)
	report := transactionSelfTestReport{
		Type: "br_transaction_engine_self_test", FormatVersion: 2, Status: "ok",
		TransactionID:                   prepared.Journal.TransactionID,
		PreparedWithoutGameEdit:         preparedClean,
		ExistingFileCommitted:           string(committedExisting) == "patched" && committed.Status == transaction.StatusCommitted,
		NewFileCommitted:                string(committedAdded) == "added",
		OriginalFileRestored:            string(finalExisting) == "original",
		AddedFileRemoved:                os.IsNotExist(finalAddedErr),
		FinalJournalStatus:              rolledBack.Status,
		PersistentBaselineCreated:       base.Action == baseline.ActionCreated,
		ActiveStateRecorded:             active.TransactionID == prepared.Journal.TransactionID,
		ActiveStateMatchedInstalled:     activeInspection.Status == installstate.InspectionMatchesInstalled,
		ActiveStateClearedAfterRollback: !activeAfterRollback,
		JournalPolicy:                   "atomic JSON journal updated before and after each file transition",
		BackupPolicy:                    "verified per-file backups created before game modification",
		ConflictPolicy:                  "commit and rollback refuse hashes changed outside the transaction",
		TestScope:                       "isolated synthetic files only; no installed game was accessed",
	}
	if !report.PreparedWithoutGameEdit || !report.ExistingFileCommitted || !report.NewFileCommitted || !report.OriginalFileRestored || !report.AddedFileRemoved || !report.PersistentBaselineCreated || !report.ActiveStateRecorded || !report.ActiveStateMatchedInstalled || !report.ActiveStateClearedAfterRollback || report.FinalJournalStatus != transaction.StatusRolledBack {
		return fmt.Errorf("transaction self-test invariant failed: %+v", report)
	}
	return emit(report, output)
}
