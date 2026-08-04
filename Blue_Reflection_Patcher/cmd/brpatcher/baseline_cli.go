package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"time"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	baselineStatusReportType    = "br_installation_baseline_status_report"
	baselineStatusFormatVersion = 1
)

type baselineStatusReport struct {
	Type           string              `json:"type"`
	FormatVersion  int                 `json:"format_version"`
	GeneratedUTC   time.Time           `json:"generated_utc"`
	TargetID       string              `json:"target_id"`
	DisplayName    string              `json:"display_name"`
	GameRoot       string              `json:"game_root"`
	StateDirectory string              `json:"state_directory"`
	Inspection     baseline.Inspection `json:"inspection"`
	Policy         string              `json:"policy"`
}

func commandBaselineStatus(args []string) error {
	flags := flag.NewFlagSet("baseline-status", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	flags.Var(&roots, "game-dir", "game directory; exactly one installation must be selected")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&output, "json", "", "write baseline status report to this file")
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
		return fmt.Errorf("baseline status requires exactly one detected installation; found %d", len(detections))
	}
	base, err := stateRoot()
	if err != nil {
		return err
	}
	detection := detections[0]
	stateDirectory := installationStateDirectory(base, detection.TargetID, detection.Root)
	inspection, err := baseline.Inspect(detection.Root, stateDirectory, detection.TargetID)
	if err != nil {
		return err
	}
	report := baselineStatusReport{
		Type: baselineStatusReportType, FormatVersion: baselineStatusFormatVersion,
		GeneratedUTC: time.Now().UTC(), TargetID: detection.TargetID,
		DisplayName: detection.DisplayName, GameRoot: detection.Root,
		StateDirectory: stateDirectory, Inspection: inspection,
		Policy: "stored baselines are immutable observed pre-install states; mismatches are classified but never automatically called clean, updated, or externally modified without stronger evidence",
	}
	printHumanBaselineStatus(os.Stdout, report)
	if output != "" {
		if err := emit(report, output); err != nil {
			return err
		}
		fmt.Printf("Baseline status report: %s\n", output)
	}
	return nil
}

func printHumanBaselineStatus(out io.Writer, report baselineStatusReport) {
	inspection := report.Inspection
	fmt.Fprintf(out, "\n%s%sPersistent installation baselines%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "Target: %s\nGame:   %s\nState:  %s\n", report.DisplayName, report.GameRoot, report.StateDirectory)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, inspection.Status)
	fmt.Fprintf(out, "Stored baselines: %d\n", inspection.BaselineCount)
	if inspection.LatestBaselineID != "" {
		fmt.Fprintf(out, "Latest baseline: %s\n", inspection.LatestBaselineID)
	}
	if inspection.MatchingBaselineID != "" {
		fmt.Fprintf(out, "Current files match: %s\n", inspection.MatchingBaselineID)
	}
	for _, item := range inspection.Baselines {
		fmt.Fprintf(out, "  [%s] %s (%d path(s))\n", item.Classification, item.BaselineID, item.FileCount)
		fmt.Fprintf(out, "      %s\n", item.ManifestPath)
	}
	for _, warning := range inspection.Warnings {
		fmt.Fprintf(out, "  %sWARNING:%s %s\n", ansiYellow, ansiReset, warning)
	}
}
