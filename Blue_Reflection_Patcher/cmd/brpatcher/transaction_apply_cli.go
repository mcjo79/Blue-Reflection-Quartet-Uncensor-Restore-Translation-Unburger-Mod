package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

const (
	transactionCommitReportType      = "br_transaction_commit_report"
	transactionCommitFormatVersion   = 1
	transactionRollbackReportType    = "br_transaction_rollback_report"
	transactionRollbackFormatVersion = 1
)

type transactionCommitReport struct {
	Type                        string    `json:"type"`
	FormatVersion               int       `json:"format_version"`
	Status                      string    `json:"status"`
	GeneratedUTC                time.Time `json:"generated_utc"`
	TransactionID               string    `json:"transaction_id"`
	JournalPath                 string    `json:"journal_path"`
	TargetID                    string    `json:"target_id"`
	GameRoot                    string    `json:"game_root"`
	StateDirectory              string    `json:"state_directory"`
	SelectedModules             []string  `json:"selected_modules"`
	FileCount                   int       `json:"file_count"`
	BaselineID                  string    `json:"baseline_id"`
	BaselineManifestPath        string    `json:"baseline_manifest_path"`
	PreviousActiveTransactionID string    `json:"previous_active_transaction_id,omitempty"`
	ActiveStatePath             string    `json:"active_state_path"`
	GameFilesModified           bool      `json:"game_files_modified"`
	AtomicPerFile               bool      `json:"atomic_per_file"`
	RecoveryPolicy              string    `json:"recovery_policy"`
}

type transactionRollbackReport struct {
	Type                string    `json:"type"`
	FormatVersion       int       `json:"format_version"`
	Status              string    `json:"status"`
	GeneratedUTC        time.Time `json:"generated_utc"`
	TransactionID       string    `json:"transaction_id"`
	JournalPath         string    `json:"journal_path"`
	TargetID            string    `json:"target_id"`
	GameRoot            string    `json:"game_root"`
	StateDirectory      string    `json:"state_directory"`
	SelectedModules     []string  `json:"selected_modules"`
	FileCount           int       `json:"file_count"`
	ActiveAfterRollback bool      `json:"active_after_rollback"`
	ActiveTransactionID string    `json:"active_transaction_id,omitempty"`
	GameFilesModified   bool      `json:"game_files_modified"`
	RecoveryMode        string    `json:"recovery_mode"`
	RecoveryPolicy      string    `json:"recovery_policy"`
}

type transactionCommandContext struct {
	Journal              transaction.Journal
	JournalPath          string
	StateDirectory       string
	TargetID             string
	BaselineManifestPath string
	ExpectedPreviousID   string
}

func commandTransactionCommit(args []string) error {
	flags := flag.NewFlagSet("transaction-commit", flag.ContinueOnError)
	var journalPath, output string
	var confirmed bool
	flags.StringVar(&journalPath, "journal", "", "prepared transaction journal")
	flags.StringVar(&output, "json", "", "write commit report to this JSON file")
	flags.BoolVar(&confirmed, "yes", false, "confirm modification of the selected game files")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(journalPath) == "" {
		return fmt.Errorf("--journal is required")
	}
	if !confirmed {
		return fmt.Errorf("transaction-commit modifies game files; inspect the journal and pass --yes to confirm")
	}
	progress := newTransactionProgressRenderer(os.Stdout)
	report, err := commitPreparedTransactionWithProgress(journalPath, progress.Callback)
	progress.Finish()
	if err != nil {
		return err
	}
	printHumanTransactionCommit(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Transaction commit report: %s\n", output)
	}
	return nil
}

func commandTransactionRollback(args []string) error {
	flags := flag.NewFlagSet("transaction-rollback", flag.ContinueOnError)
	var journalPath, output string
	var confirmed bool
	flags.StringVar(&journalPath, "journal", "", "committed or interrupted transaction journal")
	flags.StringVar(&output, "json", "", "write rollback report to this JSON file")
	flags.BoolVar(&confirmed, "yes", false, "confirm modification of the selected game files")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(journalPath) == "" {
		return fmt.Errorf("--journal is required")
	}
	if !confirmed {
		return fmt.Errorf("transaction-rollback modifies game files; inspect the journal and pass --yes to confirm")
	}
	progress := newTransactionProgressRenderer(os.Stdout)
	report, err := rollbackInstalledTransactionWithProgress(journalPath, progress.Callback)
	progress.Finish()
	if err != nil {
		return err
	}
	printHumanTransactionRollback(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Transaction rollback report: %s\n", output)
	}
	return nil
}

func loadTransactionCommandContext(journalPath string) (transactionCommandContext, error) {
	absolute, err := filepath.Abs(journalPath)
	if err != nil {
		return transactionCommandContext{}, fmt.Errorf("resolve journal: %w", err)
	}
	journal, err := transaction.Load(absolute)
	if err != nil {
		return transactionCommandContext{}, err
	}
	transactionRoot := filepath.Clean(journal.TransactionRoot)
	if filepath.Base(transactionRoot) != journal.TransactionID || filepath.Base(filepath.Dir(transactionRoot)) != "transactions" {
		return transactionCommandContext{}, fmt.Errorf("transaction journal is outside the expected installation state layout")
	}
	stateDirectory := filepath.Dir(filepath.Dir(transactionRoot))
	targetID := strings.TrimSpace(journal.Metadata["target_id"])
	baselineManifestPath := strings.TrimSpace(journal.Metadata["baseline_manifest_path"])
	if targetID == "" || baselineManifestPath == "" {
		return transactionCommandContext{}, fmt.Errorf("transaction journal lacks target or persistent baseline metadata")
	}
	return transactionCommandContext{
		Journal: journal, JournalPath: absolute, StateDirectory: stateDirectory,
		TargetID: targetID, BaselineManifestPath: baselineManifestPath,
		ExpectedPreviousID: strings.TrimSpace(journal.Metadata["active_transaction_id"]),
	}, nil
}

func commitPreparedTransaction(journalPath string) (transactionCommitReport, error) {
	return commitPreparedTransactionWithProgress(journalPath, nil)
}

func commitPreparedTransactionWithProgress(journalPath string, progress transaction.ProgressFunc) (transactionCommitReport, error) {
	context, err := loadTransactionCommandContext(journalPath)
	if err != nil {
		return transactionCommitReport{}, err
	}
	journal := context.Journal
	switch journal.Status {
	case transaction.StatusPrepared, transaction.StatusCommitting, transaction.StatusCommitted:
	default:
		return transactionCommitReport{}, fmt.Errorf("cannot commit transaction in status %s", journal.Status)
	}
	active, activeExists, err := installstate.Load(context.StateDirectory, context.TargetID, journal.GameRoot)
	if err != nil {
		return transactionCommitReport{}, fmt.Errorf("read active installation state: %w", err)
	}
	if activeExists && active.TransactionID == journal.TransactionID {
		inspection, inspectErr := installstate.Inspect(context.StateDirectory, context.TargetID, journal.GameRoot)
		if inspectErr != nil {
			return transactionCommitReport{}, inspectErr
		}
		if journal.Status != transaction.StatusCommitted || inspection.Status != installstate.InspectionMatchesInstalled {
			return transactionCommitReport{}, fmt.Errorf("active installation state references this transaction but files or journal are inconsistent: journal=%s installation=%s", journal.Status, inspection.Status)
		}
		return makeTransactionCommitReport(context, active, "already_installed"), nil
	}
	if context.ExpectedPreviousID == "" {
		if activeExists {
			return transactionCommitReport{}, fmt.Errorf("transaction was prepared without an active predecessor, but installation now has active transaction %s", active.TransactionID)
		}
	} else {
		if !activeExists || active.TransactionID != context.ExpectedPreviousID {
			return transactionCommitReport{}, fmt.Errorf("active installation changed after prepare: expected transaction %s", context.ExpectedPreviousID)
		}
		if journal.Status == transaction.StatusPrepared {
			inspection, inspectErr := installstate.Inspect(context.StateDirectory, context.TargetID, journal.GameRoot)
			if inspectErr != nil {
				return transactionCommitReport{}, inspectErr
			}
			expectedInspection := strings.TrimSpace(journal.Metadata["active_state_status"])
			safeInspection := inspection.Status == installstate.InspectionMatchesInstalled || inspection.Status == installstate.InspectionDisplacedToBaseline
			if !safeInspection || (expectedInspection != "" && inspection.Status != expectedInspection) {
				return transactionCommitReport{}, fmt.Errorf("active installation no longer matches the state used during prepare: expected=%s current=%s", expectedInspection, inspection.Status)
			}
		}
	}
	committed, err := transaction.CommitWithProgress(context.JournalPath, progress)
	if err != nil {
		return transactionCommitReport{}, fmt.Errorf("commit interrupted or blocked: %w; the journal was retained and the same transaction may be resumed or rolled back", err)
	}
	if committed.Status != transaction.StatusCommitted {
		return transactionCommitReport{}, fmt.Errorf("transaction did not reach committed status: %s", committed.Status)
	}
	activated, err := installstate.Activate(context.StateDirectory, context.TargetID, committed.GameRoot, context.BaselineManifestPath, context.JournalPath)
	if err != nil {
		return transactionCommitReport{}, fmt.Errorf("game files were committed but active-state publication failed: %w; rerun transaction-commit with the same journal or roll it back", err)
	}
	inspection, err := installstate.Inspect(context.StateDirectory, context.TargetID, committed.GameRoot)
	if err != nil {
		return transactionCommitReport{}, err
	}
	if inspection.Status != installstate.InspectionMatchesInstalled || inspection.TransactionID != committed.TransactionID {
		return transactionCommitReport{}, fmt.Errorf("installed files do not match the published active state: %s", inspection.Status)
	}
	return makeTransactionCommitReport(context, activated, "installed"), nil
}

func makeTransactionCommitReport(context transactionCommandContext, active installstate.State, status string) transactionCommitReport {
	return transactionCommitReport{
		Type: transactionCommitReportType, FormatVersion: transactionCommitFormatVersion,
		Status: status, GeneratedUTC: time.Now().UTC(), TransactionID: context.Journal.TransactionID,
		JournalPath: context.JournalPath, TargetID: context.TargetID, GameRoot: context.Journal.GameRoot,
		StateDirectory: context.StateDirectory, SelectedModules: append([]string(nil), context.Journal.SelectedModules...),
		FileCount: len(context.Journal.Files), BaselineID: active.BaselineID,
		BaselineManifestPath: active.BaselineManifestPath, PreviousActiveTransactionID: context.ExpectedPreviousID,
		ActiveStatePath: installstate.ActivePath(context.StateDirectory), GameFilesModified: status == "installed",
		AtomicPerFile:  true,
		RecoveryPolicy: "journal each transition, accept only original or already-installed hashes, resume interrupted commits, and retain verified backups for rollback",
	}
}

func rollbackInstalledTransaction(journalPath string) (transactionRollbackReport, error) {
	return rollbackInstalledTransactionWithProgress(journalPath, nil)
}

func rollbackInstalledTransactionWithProgress(journalPath string, progress transaction.ProgressFunc) (transactionRollbackReport, error) {
	context, err := loadTransactionCommandContext(journalPath)
	if err != nil {
		return transactionRollbackReport{}, err
	}
	journal := context.Journal
	if journal.Status == transaction.StatusPrepared {
		return transactionRollbackReport{}, fmt.Errorf("prepared transaction has not modified the game; use transaction-discard instead")
	}
	switch journal.Status {
	case transaction.StatusCommitting, transaction.StatusCommitted, transaction.StatusRollingBack, transaction.StatusRolledBack:
	default:
		return transactionRollbackReport{}, fmt.Errorf("cannot roll back transaction in status %s", journal.Status)
	}
	active, activeExists, err := installstate.Load(context.StateDirectory, context.TargetID, journal.GameRoot)
	if err != nil {
		return transactionRollbackReport{}, err
	}
	recoveryMode := ""
	reconcileCurrent := false
	switch {
	case activeExists && active.TransactionID == journal.TransactionID:
		recoveryMode = "active_transaction"
		reconcileCurrent = true
	case context.ExpectedPreviousID != "" && activeExists && active.TransactionID == context.ExpectedPreviousID:
		recoveryMode = "interrupted_update_before_activation"
	case context.ExpectedPreviousID == "" && !activeExists:
		recoveryMode = "interrupted_first_install_before_activation"
	default:
		current := "none"
		if activeExists {
			current = active.TransactionID
		}
		return transactionRollbackReport{}, fmt.Errorf("active installation relationship does not permit rollback: journal=%s expected_previous=%s active=%s", journal.TransactionID, context.ExpectedPreviousID, current)
	}
	rolledBack, err := transaction.RollbackWithProgress(context.JournalPath, progress)
	if err != nil {
		return transactionRollbackReport{}, fmt.Errorf("rollback interrupted or blocked: %w; the journal was retained and rollback may be resumed", err)
	}
	var restored installstate.State
	var activeAfter bool
	if reconcileCurrent {
		restored, activeAfter, err = installstate.ReconcileRollback(context.StateDirectory, context.TargetID, journal.GameRoot, context.JournalPath)
		if err != nil {
			return transactionRollbackReport{}, fmt.Errorf("files were rolled back but active-state reconciliation failed: %w", err)
		}
	} else if activeExists {
		inspection, inspectErr := installstate.Inspect(context.StateDirectory, context.TargetID, journal.GameRoot)
		if inspectErr != nil {
			return transactionRollbackReport{}, inspectErr
		}
		if inspection.Status != installstate.InspectionMatchesInstalled || inspection.TransactionID != active.TransactionID {
			return transactionRollbackReport{}, fmt.Errorf("rollback did not restore the previous active installation state: %s", inspection.Status)
		}
		restored, activeAfter = active, true
	}
	if rolledBack.Status != transaction.StatusRolledBack {
		return transactionRollbackReport{}, fmt.Errorf("transaction did not reach rolled_back status: %s", rolledBack.Status)
	}
	report := transactionRollbackReport{
		Type: transactionRollbackReportType, FormatVersion: transactionRollbackFormatVersion,
		Status: "rolled_back", GeneratedUTC: time.Now().UTC(), TransactionID: rolledBack.TransactionID,
		JournalPath: context.JournalPath, TargetID: context.TargetID, GameRoot: rolledBack.GameRoot,
		StateDirectory: context.StateDirectory, SelectedModules: append([]string(nil), rolledBack.SelectedModules...),
		FileCount: len(rolledBack.Files), ActiveAfterRollback: activeAfter,
		GameFilesModified: true, RecoveryMode: recoveryMode,
		RecoveryPolicy: "restore only while current hashes match the transaction-installed state; restore the previous active state or persistent baseline and refuse external changes",
	}
	if activeAfter {
		report.ActiveTransactionID = restored.TransactionID
	}
	return report, nil
}

func printHumanTransactionCommit(out io.Writer, report transactionCommitReport) {
	fmt.Fprintf(out, "\n%s%sTransaction installed%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	fmt.Fprintf(out, "Transaction: %s\nGame:        %s\n", report.TransactionID, report.GameRoot)
	fmt.Fprintf(out, "Modules:     %v\nFiles:       %d\n", report.SelectedModules, report.FileCount)
	fmt.Fprintf(out, "Active state: %s\n", report.ActiveStatePath)
	if report.PreviousActiveTransactionID != "" {
		fmt.Fprintf(out, "Updated from: %s\n", report.PreviousActiveTransactionID)
	}
	if report.Status == "already_installed" {
		fmt.Fprintf(out, "%sThe transaction was already committed and matches the active installation state; no file was rewritten.%s\n", ansiDim, ansiReset)
	} else {
		fmt.Fprintf(out, "%sGame files were atomically replaced per file, verified by SHA-256 and recorded for rollback.%s\n", ansiDim, ansiReset)
	}
}

func printHumanTransactionRollback(out io.Writer, report transactionRollbackReport) {
	fmt.Fprintf(out, "\n%s%sTransaction rolled back%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Transaction: %s\nGame:        %s\nFiles:       %d\n", report.TransactionID, report.GameRoot, report.FileCount)
	if report.ActiveAfterRollback {
		fmt.Fprintf(out, "Restored active transaction: %s\n", report.ActiveTransactionID)
	} else {
		fmt.Fprintln(out, "Active patcher installation: none (persistent baseline restored)")
	}
	fmt.Fprintf(out, "%sRollback accepted only transaction-owned hashes and retained the journal as audit history.%s\n", ansiDim, ansiReset)
}
