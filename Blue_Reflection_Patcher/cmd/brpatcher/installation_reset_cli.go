package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/archivepolicy"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	installationResetReportType    = "br_installation_state_adoption_report"
	installationResetFormatVersion = 1
)

type installationResetReport struct {
	Type                      string                            `json:"type"`
	FormatVersion             int                               `json:"format_version"`
	Status                    string                            `json:"status"`
	GeneratedUTC              time.Time                         `json:"generated_utc"`
	AdoptionID                string                            `json:"adoption_id"`
	TargetID                  string                            `json:"target_id"`
	DisplayName               string                            `json:"display_name"`
	GameRoot                  string                            `json:"game_root"`
	StateDirectory            string                            `json:"state_directory"`
	ArchivedPreviousState     string                            `json:"archived_previous_state"`
	PreviousActiveStateStatus string                            `json:"previous_active_state_status"`
	PreviousBaselineStatus    string                            `json:"previous_baseline_status"`
	AdoptedPaths              []string                          `json:"adopted_paths"`
	BaselineAction            string                            `json:"baseline_action"`
	BaselineID                string                            `json:"baseline_id"`
	BaselineFingerprint       string                            `json:"baseline_fingerprint"`
	BaselineManifestPath      string                            `json:"baseline_manifest_path"`
	CaptureMethod             string                            `json:"capture_method"`
	SourceClassification      string                            `json:"source_classification"`
	ActiveStateCleared        bool                              `json:"active_state_cleared"`
	PreviousStateArchived     bool                              `json:"previous_state_archived"`
	GameFilesModified         bool                              `json:"game_files_modified"`
	IgnoredAnalyticalArchives []archivepolicy.AnalyticalArchive `json:"ignored_analytical_archives"`
	ReportPath                string                            `json:"report_path"`
	Policy                    string                            `json:"policy"`
}

func commandInstallationResetState(args []string) error {
	flags := flag.NewFlagSet("installation-reset-state", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	var adoptCurrent, confirmed bool
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.BoolVar(&adoptCurrent, "adopt-current", false, "archive previous patcher state and adopt the current managed game files as a new baseline")
	flags.BoolVar(&confirmed, "yes", false, "confirm state retirement and baseline adoption; game files are not modified")
	flags.StringVar(&output, "json", "", "write adoption report to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if !adoptCurrent {
		return fmt.Errorf("--adopt-current is required")
	}
	if !confirmed {
		return fmt.Errorf("--yes is required to archive previous state and adopt the current installation")
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
		return fmt.Errorf("installation state adoption requires exactly one detected installation; found %d", len(detections))
	}
	base, err := stateRoot()
	if err != nil {
		return err
	}
	detection := detections[0]
	stateDirectory := installationStateDirectory(base, detection.TargetID, detection.Root)
	report, err := adoptCurrentInstallationState(detection.TargetID, detection.DisplayName, detection.Root, stateDirectory)
	if err != nil {
		return err
	}
	printHumanInstallationReset(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Installation adoption report: %s\n", output)
	}
	return nil
}

func adoptCurrentInstallationState(targetID, displayName, gameRoot, stateDirectory string) (installationResetReport, error) {
	activeInspection, err := installstate.Inspect(stateDirectory, targetID, gameRoot)
	if err != nil {
		return installationResetReport{}, err
	}
	baselineInspection, err := baseline.Inspect(gameRoot, stateDirectory, targetID)
	if err != nil {
		return installationResetReport{}, err
	}
	if err := validateAdoptionState(activeInspection, baselineInspection); err != nil {
		return installationResetReport{}, err
	}
	if err := rejectBlockingTransactions(stateDirectory, activeInspection.Active); err != nil {
		return installationResetReport{}, err
	}
	paths, err := collectAdoptionPaths(stateDirectory, targetID, gameRoot, activeInspection, baselineInspection)
	if err != nil {
		return installationResetReport{}, err
	}
	analytical, err := archivepolicy.FindAnalyticalArchives(gameRoot)
	if err != nil {
		return installationResetReport{}, err
	}
	adoptionID, err := transaction.NewID(time.Now())
	if err != nil {
		return installationResetReport{}, err
	}
	stateDirectory, err = filepath.Abs(stateDirectory)
	if err != nil {
		return installationResetReport{}, err
	}
	info, err := os.Lstat(stateDirectory)
	if err != nil {
		return installationResetReport{}, fmt.Errorf("inspect existing installation state: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return installationResetReport{}, fmt.Errorf("installation state is not a real directory: %s", stateDirectory)
	}
	archivePath := stateDirectory + ".manual-reset-" + adoptionID
	if _, err := os.Lstat(archivePath); err == nil {
		return installationResetReport{}, fmt.Errorf("state archive already exists: %s", archivePath)
	} else if !errors.Is(err, os.ErrNotExist) {
		return installationResetReport{}, err
	}
	if err := os.Rename(stateDirectory, archivePath); err != nil {
		return installationResetReport{}, fmt.Errorf("archive previous installation state: %w", err)
	}
	if err := syncDirectory(filepath.Dir(stateDirectory)); err != nil {
		_ = os.Rename(archivePath, stateDirectory)
		return installationResetReport{}, err
	}
	restorePrevious := true
	defer func() {
		if restorePrevious {
			_ = os.RemoveAll(stateDirectory)
			_ = os.Rename(archivePath, stateDirectory)
		}
	}()
	if err := os.MkdirAll(stateDirectory, 0o700); err != nil {
		return installationResetReport{}, err
	}
	adopted, err := baseline.AdoptCurrent(gameRoot, stateDirectory, targetID, paths, baseline.AdoptionProvenance{
		AdoptionID: adoptionID, PreviousStateArchive: archivePath,
	})
	if err != nil {
		return installationResetReport{}, err
	}
	reportPath := filepath.Join(stateDirectory, "adoptions", adoptionID+".json")
	report := installationResetReport{
		Type: installationResetReportType, FormatVersion: installationResetFormatVersion,
		Status: "adopted_current", GeneratedUTC: time.Now().UTC(), AdoptionID: adoptionID,
		TargetID: targetID, DisplayName: displayName, GameRoot: filepath.Clean(gameRoot),
		StateDirectory: stateDirectory, ArchivedPreviousState: archivePath,
		PreviousActiveStateStatus: activeInspection.Status, PreviousBaselineStatus: baselineInspection.Status,
		AdoptedPaths: paths, BaselineAction: adopted.Action, BaselineID: adopted.Manifest.BaselineID,
		BaselineFingerprint: adopted.Manifest.Fingerprint, BaselineManifestPath: adopted.ManifestPath,
		CaptureMethod: "manual_adopt_current", SourceClassification: baseline.SourceCurrentInstallation,
		ActiveStateCleared: true, PreviousStateArchived: true, GameFilesModified: false,
		IgnoredAnalyticalArchives: analytical, ReportPath: reportPath,
		Policy: "archive the complete previous patcher state, reject active installed or partial states and non-terminal transactions, adopt only exact current managed paths, never claim official cleanliness, and never modify game files",
	}
	if err := atomicAdoptionJSON(reportPath, report, 0o600); err != nil {
		return installationResetReport{}, err
	}
	if err := syncDirectory(filepath.Dir(stateDirectory)); err != nil {
		return installationResetReport{}, err
	}
	restorePrevious = false
	return report, nil
}

func validateAdoptionState(active installstate.Inspection, base baseline.Inspection) error {
	if active.Active {
		switch active.Status {
		case installstate.InspectionDisplacedToBaseline, installstate.InspectionChangedUnclassified:
			return nil
		case installstate.InspectionMatchesInstalled:
			return fmt.Errorf("current files still match the active patcher installation; use installation-remove or rollback instead of adopting the mod as a baseline")
		case installstate.InspectionPartiallyDisplaced:
			return fmt.Errorf("partially displaced active state cannot be adopted; resolve or roll back the mixed installation first")
		case installstate.InspectionMissingOrChanged:
			return fmt.Errorf("active state has missing managed files and cannot be adopted safely")
		default:
			return fmt.Errorf("active installation state cannot be adopted in status %s", active.Status)
		}
	}
	switch base.Status {
	case "not_captured":
		return fmt.Errorf("no existing patcher state or baseline is available to reset")
	case "matches_known_baseline":
		return fmt.Errorf("current files already match a known inactive baseline; no state reset is needed")
	case "missing_or_changed":
		return fmt.Errorf("inactive baseline has missing managed files and cannot be adopted safely")
	case "mixed_changes", "changed_unclassified":
		return nil
	default:
		return fmt.Errorf("inactive baseline cannot be adopted in status %s", base.Status)
	}
}

func collectAdoptionPaths(stateDirectory, targetID, gameRoot string, active installstate.Inspection, base baseline.Inspection) ([]string, error) {
	byKey := map[string]string{}
	if active.Active {
		state, exists, err := installstate.Load(stateDirectory, targetID, gameRoot)
		if err != nil {
			return nil, err
		}
		if !exists {
			return nil, fmt.Errorf("active installation state disappeared during adoption planning")
		}
		for _, file := range state.Files {
			byKey[strings.ToLower(filepath.ToSlash(file.RelativePath))] = filepath.ToSlash(file.RelativePath)
		}
	}
	if len(base.Baselines) != 0 {
		latest := base.Baselines[len(base.Baselines)-1]
		manifest, _, err := baseline.LoadAndVerify(latest.ManifestPath)
		if err != nil {
			return nil, err
		}
		for _, file := range manifest.Files {
			byKey[strings.ToLower(filepath.ToSlash(file.RelativePath))] = filepath.ToSlash(file.RelativePath)
		}
	}
	paths := make([]string, 0, len(byKey))
	for _, path := range byKey {
		if err := archivepolicy.RejectAnalyticalArchivePath(path, "adoption"); err != nil {
			return nil, err
		}
		paths = append(paths, path)
	}
	sort.Slice(paths, func(i, j int) bool { return strings.ToLower(paths[i]) < strings.ToLower(paths[j]) })
	if len(paths) == 0 {
		return nil, fmt.Errorf("no managed paths are available for adoption")
	}
	return paths, nil
}

func atomicAdoptionJSON(path string, value any, mode fs.FileMode) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".tmp-adoption-")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	ok := false
	defer func() {
		_ = temp.Close()
		if !ok {
			_ = os.Remove(tempPath)
		}
	}()
	if err := temp.Chmod(mode); err != nil {
		return err
	}
	if _, err := temp.Write(data); err != nil {
		return err
	}
	if err := temp.Sync(); err != nil {
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempPath, path); err != nil {
		return err
	}
	ok = true
	return syncDirectory(filepath.Dir(path))
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	if err := directory.Sync(); err != nil {
		if runtime.GOOS == "windows" || errors.Is(err, os.ErrInvalid) {
			return nil
		}
		return err
	}
	return nil
}

func printHumanInstallationReset(out io.Writer, report installationResetReport) {
	fmt.Fprintf(out, "\n%s%sInstallation state adopted%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Target: %s\nGame:   %s\n", report.DisplayName, report.GameRoot)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	fmt.Fprintf(out, "Previous state archive: %s\n", report.ArchivedPreviousState)
	fmt.Fprintf(out, "New baseline: %s\n", report.BaselineID)
	fmt.Fprintf(out, "Baseline manifest: %s\n", report.BaselineManifestPath)
	fmt.Fprintf(out, "Adopted managed paths: %d\n", len(report.AdoptedPaths))
	fmt.Fprintf(out, "Ignored analytical archives: %d\n", len(report.IgnoredAnalyticalArchives))
	fmt.Fprintln(out, "Game files modified: false")
	fmt.Fprintln(out, "The adopted baseline is classified as current_installation; no official or clean-source claim was made.")
}
