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
	"local/blue-reflection-patcher/internal/plan/transaction"
)

type transactionSelfTestReport struct {
	Type                    string `json:"type"`
	FormatVersion           int    `json:"format_version"`
	Status                  string `json:"status"`
	TransactionID           string `json:"transaction_id"`
	PreparedWithoutGameEdit bool   `json:"prepared_without_game_edit"`
	ExistingFileCommitted   bool   `json:"existing_file_committed"`
	NewFileCommitted        bool   `json:"new_file_committed"`
	OriginalFileRestored    bool   `json:"original_file_restored"`
	AddedFileRemoved        bool   `json:"added_file_removed"`
	FinalJournalStatus      string `json:"final_journal_status"`
	JournalPolicy           string `json:"journal_policy"`
	BackupPolicy            string `json:"backup_policy"`
	ConflictPolicy          string `json:"conflict_policy"`
	TestScope               string `json:"test_scope"`
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
		fmt.Fprintf(out, "    journal: %s\n", filepath.Join(state, "transactions", "<transaction-id>", "journal.json"))
		fmt.Fprintf(out, "    backup:  %s\n", filepath.Join(state, "transactions", "<transaction-id>", "backup"))
	}
	fmt.Fprintln(out, "  Policy: stage and verify -> backup originals -> atomic commit -> hash-guarded rollback")
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
	prepared, err := transaction.Prepare(game, state, []transaction.ChangeSpec{
		{RelativePath: "Data/EXISTING.PAK", StagedPath: stagedExisting},
		{RelativePath: "Data/ADDED.PAK", StagedPath: stagedAdded},
	}, []string{"blue_reflection_translation", "quartet_restoration"}, map[string]string{
		"target_id": "synthetic_quartet", "purpose": "validation_only",
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
	finalExisting, err := os.ReadFile(existing)
	if err != nil {
		return err
	}
	_, finalAddedErr := os.Stat(added)
	report := transactionSelfTestReport{
		Type: "br_transaction_engine_self_test", FormatVersion: 1, Status: "ok",
		TransactionID:           prepared.Journal.TransactionID,
		PreparedWithoutGameEdit: preparedClean,
		ExistingFileCommitted:   string(committedExisting) == "patched" && committed.Status == transaction.StatusCommitted,
		NewFileCommitted:        string(committedAdded) == "added",
		OriginalFileRestored:    string(finalExisting) == "original",
		AddedFileRemoved:        os.IsNotExist(finalAddedErr),
		FinalJournalStatus:      rolledBack.Status,
		JournalPolicy:           "atomic JSON journal updated before and after each file transition",
		BackupPolicy:            "verified per-file backups created before game modification",
		ConflictPolicy:          "commit and rollback refuse hashes changed outside the transaction",
		TestScope:               "isolated synthetic files only; no installed game was accessed",
	}
	if !report.PreparedWithoutGameEdit || !report.ExistingFileCommitted || !report.NewFileCommitted || !report.OriginalFileRestored || !report.AddedFileRemoved || report.FinalJournalStatus != transaction.StatusRolledBack {
		return fmt.Errorf("transaction self-test invariant failed: %+v", report)
	}
	return emit(report, output)
}
