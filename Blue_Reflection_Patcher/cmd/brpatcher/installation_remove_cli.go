package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	installationRemoveReportType    = "br_installation_remove_report"
	installationRemoveFormatVersion = 1
)

type installationRemoveStep struct {
	TransactionID string `json:"transaction_id"`
	JournalPath   string `json:"journal_path"`
	FileCount     int    `json:"file_count"`
}

type installationRemoveReport struct {
	Type                    string                   `json:"type"`
	FormatVersion           int                      `json:"format_version"`
	Status                  string                   `json:"status"`
	GeneratedUTC            time.Time                `json:"generated_utc"`
	TargetID                string                   `json:"target_id"`
	DisplayName             string                   `json:"display_name"`
	GameRoot                string                   `json:"game_root"`
	StateDirectory          string                   `json:"state_directory"`
	InitialTransactionID    string                   `json:"initial_transaction_id,omitempty"`
	RollbackSteps           []installationRemoveStep `json:"rollback_steps"`
	RollbackCount           int                      `json:"rollback_count"`
	BaselineRestored        bool                     `json:"baseline_restored"`
	StaleStateRecordCleared bool                     `json:"stale_state_record_cleared"`
	GameFilesModified       bool                     `json:"game_files_modified"`
	Policy                  string                   `json:"policy"`
}

func commandInstallationRemove(args []string) error {
	flags := flag.NewFlagSet("installation-remove", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	var confirmed bool
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&output, "json", "", "write removal report to this JSON file")
	flags.BoolVar(&confirmed, "yes", false, "confirm removal of all patcher-installed modules")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if !confirmed {
		return fmt.Errorf("installation-remove may modify game files; pass --yes to confirm")
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	detections, err := detectWithFallback(specs, roots, false, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	if len(detections) != 1 {
		return fmt.Errorf("installation-remove requires exactly one detected installation; found %d", len(detections))
	}
	report, err := removeManagedInstallation(detections[0].TargetID, detections[0].DisplayName, detections[0].Root)
	if err != nil {
		return err
	}
	printHumanInstallationRemove(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Installation removal report: %s\n", output)
	}
	return nil
}

func removeManagedInstallation(targetID, displayName, gameRoot string) (installationRemoveReport, error) {
	base, err := stateRoot()
	if err != nil {
		return installationRemoveReport{}, err
	}
	stateDirectory := installationStateDirectory(base, targetID, gameRoot)
	return removeManagedInstallationFromState(targetID, displayName, gameRoot, stateDirectory)
}

func removeManagedInstallationFromState(targetID, displayName, gameRoot, stateDirectory string) (installationRemoveReport, error) {
	report := installationRemoveReport{
		Type: installationRemoveReportType, FormatVersion: installationRemoveFormatVersion,
		Status: "not_installed", GeneratedUTC: time.Now().UTC(), TargetID: targetID,
		DisplayName: displayName, GameRoot: gameRoot, StateDirectory: stateDirectory,
		RollbackSteps: []installationRemoveStep{},
		Policy:        "remove only patcher-recorded active states, require exact installed hashes for every rollback, stop on external changes, and finish at the preserved baseline",
	}
	seen := map[string]bool{}
	for depth := 0; depth < 1024; depth++ {
		active, exists, err := installstate.Load(stateDirectory, targetID, gameRoot)
		if err != nil {
			return report, err
		}
		if !exists {
			report.BaselineRestored = true
			if len(report.RollbackSteps) > 0 || report.StaleStateRecordCleared {
				report.Status = "removed"
			}
			report.RollbackCount = len(report.RollbackSteps)
			return report, nil
		}
		if report.InitialTransactionID == "" {
			report.InitialTransactionID = active.TransactionID
		}
		if seen[active.TransactionID] {
			return report, fmt.Errorf("active installation history contains a transaction cycle at %s", active.TransactionID)
		}
		seen[active.TransactionID] = true

		inspection, err := installstate.Inspect(stateDirectory, targetID, gameRoot)
		if err != nil {
			return report, err
		}
		switch inspection.Status {
		case installstate.InspectionMatchesInstalled:
			rolledBack, err := rollbackInstalledTransaction(active.JournalPath)
			if err != nil {
				return report, fmt.Errorf("remove active transaction %s: %w", active.TransactionID, err)
			}
			report.RollbackSteps = append(report.RollbackSteps, installationRemoveStep{
				TransactionID: rolledBack.TransactionID,
				JournalPath:   rolledBack.JournalPath,
				FileCount:     rolledBack.FileCount,
			})
			report.GameFilesModified = report.GameFilesModified || rolledBack.GameFilesModified
		case installstate.InspectionDisplacedToBaseline:
			if err := installstate.ClearDisplacedActiveState(stateDirectory, targetID, gameRoot); err != nil {
				return report, err
			}
			report.StaleStateRecordCleared = true
		default:
			return report, fmt.Errorf("refusing complete removal because active installation status is %s; restore exact patcher-installed files or the preserved baseline before retrying", inspection.Status)
		}
	}
	return report, fmt.Errorf("active installation rollback history exceeds the safety limit")
}

func printHumanInstallationRemove(out io.Writer, report installationRemoveReport) {
	fmt.Fprintf(out, "\n%s%sManaged installation removal%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Target: %s\nGame:   %s\n", report.DisplayName, report.GameRoot)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	if report.InitialTransactionID != "" {
		fmt.Fprintf(out, "Initial active transaction: %s\n", report.InitialTransactionID)
	}
	fmt.Fprintf(out, "Rolled back transactions: %d\n", report.RollbackCount)
	if report.StaleStateRecordCleared {
		fmt.Fprintln(out, "Cleared stale active-state metadata after verifying that managed files already matched the preserved baseline.")
	}
	if report.Status == "not_installed" {
		fmt.Fprintln(out, "Active patcher installation: none")
	} else {
		fmt.Fprintln(out, "Active patcher installation: none (persistent baseline restored)")
	}
	fmt.Fprintf(out, "%sEvery rollback was hash-guarded; unknown or externally changed files are never overwritten.%s\n", ansiDim, ansiReset)
}

func parseGuidedManagementChoice(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}
