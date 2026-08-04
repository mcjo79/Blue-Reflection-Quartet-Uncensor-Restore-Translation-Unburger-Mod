package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/archivepolicy"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/gamepath"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	installationStatusReportType    = "br_installation_status_report"
	installationStatusFormatVersion = 2
)

type installationManagedFileStatus struct {
	RelativePath    string `json:"relative_path"`
	ResolvedPath    string `json:"resolved_path"`
	CurrentState    string `json:"current_state"`
	CurrentSHA256   string `json:"current_sha256,omitempty"`
	BaselineSHA256  string `json:"baseline_sha256,omitempty"`
	InstalledSHA256 string `json:"installed_sha256,omitempty"`
	Classification  string `json:"classification"`
}

type installationStatusReport struct {
	Type                      string                            `json:"type"`
	FormatVersion             int                               `json:"format_version"`
	GeneratedUTC              time.Time                         `json:"generated_utc"`
	Status                    string                            `json:"status"`
	TargetID                  string                            `json:"target_id"`
	DisplayName               string                            `json:"display_name"`
	GameRoot                  string                            `json:"game_root"`
	StateDirectory            string                            `json:"state_directory"`
	ActiveState               installstate.Inspection           `json:"active_state"`
	Baseline                  baseline.Inspection               `json:"baseline"`
	ManagedFiles              []installationManagedFileStatus   `json:"managed_files"`
	IgnoredAnalyticalArchives []archivepolicy.AnalyticalArchive `json:"ignored_analytical_archives"`
	AutomaticPrepare          bool                              `json:"automatic_prepare_allowed"`
	Policy                    string                            `json:"policy"`
}

func commandInstallationStatus(args []string) error {
	flags := flag.NewFlagSet("installation-status", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&output, "json", "", "write installation status report to this file")
	if err := flags.Parse(args); err != nil {
		return err
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
		return fmt.Errorf("installation status requires exactly one detected installation; found %d", len(detections))
	}
	base, err := stateRoot()
	if err != nil {
		return err
	}
	detection := detections[0]
	stateDirectory := installationStateDirectory(base, detection.TargetID, detection.Root)
	active, err := installstate.Inspect(stateDirectory, detection.TargetID, detection.Root)
	if err != nil {
		return err
	}
	baselines, err := baseline.Inspect(detection.Root, stateDirectory, detection.TargetID)
	if err != nil {
		return err
	}
	managed, err := buildManagedFileStatus(detection.Root, active, baselines)
	if err != nil {
		return err
	}
	analytical, err := archivepolicy.FindAnalyticalArchives(detection.Root)
	if err != nil {
		return err
	}
	status, allowed := overallInstallationStatus(active, baselines)
	report := installationStatusReport{
		Type: installationStatusReportType, FormatVersion: installationStatusFormatVersion,
		GeneratedUTC: time.Now().UTC(), Status: status,
		TargetID: detection.TargetID, DisplayName: detection.DisplayName,
		GameRoot: detection.Root, StateDirectory: stateDirectory,
		ActiveState: active, Baseline: baselines, ManagedFiles: managed,
		IgnoredAnalyticalArchives: analytical, AutomaticPrepare: allowed,
		Policy: "distinguish patcher-installed state, preserved baseline, manual adoption provenance, partial displacement, unknown changes and ignored .PAK_ audit siblings without calling an unknown hash a game update or a clean file",
	}
	printHumanInstallationStatus(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Installation status report: %s\n", output)
	}
	return nil
}

func buildManagedFileStatus(gameRoot string, active installstate.Inspection, base baseline.Inspection) ([]installationManagedFileStatus, error) {
	byKey := map[string]installationManagedFileStatus{}
	for _, item := range base.Files {
		resolved, _, err := gamepath.Resolve(gameRoot, item.RelativePath)
		if err != nil {
			return nil, err
		}
		classification := "external_or_unclassified"
		switch {
		case item.Matches:
			classification = "managed_baseline"
		case item.Current == "missing":
			classification = "missing"
		}
		byKey[strings.ToLower(filepath.ToSlash(item.RelativePath))] = installationManagedFileStatus{
			RelativePath: filepath.ToSlash(item.RelativePath), ResolvedPath: resolved,
			CurrentState: item.Current, CurrentSHA256: item.CurrentHash,
			BaselineSHA256: item.ExpectedHash, Classification: classification,
		}
	}
	for _, item := range active.Files {
		resolved, _, err := gamepath.Resolve(gameRoot, item.RelativePath)
		if err != nil {
			return nil, err
		}
		classification := "external_or_unclassified"
		switch {
		case item.MatchesInstalled:
			classification = "active_mod_payload"
		case item.MatchesBaseline:
			classification = "managed_baseline"
		case item.CurrentState == "missing":
			classification = "missing"
		}
		byKey[strings.ToLower(filepath.ToSlash(item.RelativePath))] = installationManagedFileStatus{
			RelativePath: filepath.ToSlash(item.RelativePath), ResolvedPath: resolved,
			CurrentState: item.CurrentState, CurrentSHA256: item.CurrentSHA256,
			BaselineSHA256: item.BaselineSHA256, InstalledSHA256: item.InstalledSHA256,
			Classification: classification,
		}
	}
	result := make([]installationManagedFileStatus, 0, len(byKey))
	for _, item := range byKey {
		result = append(result, item)
	}
	sort.Slice(result, func(i, j int) bool {
		return strings.ToLower(result[i].RelativePath) < strings.ToLower(result[j].RelativePath)
	})
	return result, nil
}

func overallInstallationStatus(active installstate.Inspection, base baseline.Inspection) (string, bool) {
	if active.Active {
		switch active.Status {
		case installstate.InspectionMatchesInstalled:
			return active.Status, true
		case installstate.InspectionDisplacedToBaseline:
			return active.Status, true
		default:
			return active.Status, false
		}
	}
	switch base.Status {
	case "not_captured":
		return "untracked", true
	case "matches_known_baseline":
		return "inactive_matches_known_baseline", true
	case "mixed_changes", "changed_unclassified", "missing_or_changed":
		return "inactive_" + base.Status, true
	default:
		return "inactive_" + base.Status, false
	}
}

func printHumanInstallationStatus(out io.Writer, report installationStatusReport) {
	fmt.Fprintf(out, "\n%s%sInstallation state%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Target: %s\nGame:   %s\nState:  %s\n", report.DisplayName, report.GameRoot, report.StateDirectory)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	fmt.Fprintf(out, "Automatic prepare: %t\n", report.AutomaticPrepare)
	if report.ActiveState.Active {
		fmt.Fprintf(out, "Active transaction: %s\n", report.ActiveState.TransactionID)
		fmt.Fprintf(out, "Active modules: %v\n", report.ActiveState.SelectedModules)
		fmt.Fprintf(out, "Original baseline: %s\n", report.ActiveState.BaselineID)
		if report.ActiveState.PreviousStatePath != "" {
			fmt.Fprintf(out, "Previous managed state: %s\n", report.ActiveState.PreviousStatePath)
		}
	} else {
		fmt.Fprintln(out, "Active patcher installation: none")
	}
	fmt.Fprintf(out, "Stored baselines: %d\n", report.Baseline.BaselineCount)
	if len(report.Baseline.Baselines) != 0 {
		latest := report.Baseline.Baselines[len(report.Baseline.Baselines)-1]
		captureMethod := latest.CaptureMethod
		if captureMethod == "" {
			captureMethod = "legacy_observed_baseline"
		}
		sourceClassification := latest.SourceClassification
		if sourceClassification == "" {
			sourceClassification = latest.Classification
		}
		fmt.Fprintf(out, "Latest baseline provenance: %s / %s\n", captureMethod, sourceClassification)
	}
	for _, item := range report.ManagedFiles {
		fmt.Fprintf(out, "  %s: %s", item.RelativePath, item.Classification)
		if item.CurrentSHA256 != "" {
			fmt.Fprintf(out, " (sha256=%s)", item.CurrentSHA256)
		}
		fmt.Fprintln(out)
	}
	if len(report.IgnoredAnalyticalArchives) != 0 {
		fmt.Fprintf(out, "Ignored analytical archives (*.PAK_): %d\n", len(report.IgnoredAnalyticalArchives))
		for _, item := range report.IgnoredAnalyticalArchives {
			fmt.Fprintf(out, "  %s -> %s (production exists: %t)\n", item.RelativePath, item.ProductionRelativePath, item.ProductionExists)
		}
	}
	for _, warning := range report.ActiveState.Warnings {
		fmt.Fprintf(out, "  %sWARNING:%s %s\n", ansiYellow, ansiReset, warning)
	}
	if !(report.ActiveState.Active && report.ActiveState.Status == installstate.InspectionMatchesInstalled) {
		for _, warning := range report.Baseline.Warnings {
			fmt.Fprintf(out, "  %sBASELINE:%s %s\n", ansiYellow, ansiReset, warning)
		}
	}
}
