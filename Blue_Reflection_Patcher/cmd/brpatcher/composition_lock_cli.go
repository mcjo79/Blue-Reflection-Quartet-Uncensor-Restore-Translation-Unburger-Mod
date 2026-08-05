package main

import (
	"errors"
	"flag"
	"os"
	"path/filepath"
	"time"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

type quartetCompositionLockStatusReport struct {
	Type          string                     `json:"type"`
	FormatVersion int                        `json:"format_version"`
	GeneratedUTC  time.Time                  `json:"generated_utc"`
	ProjectRoot   string                     `json:"project_root"`
	LockPath      string                     `json:"lock_path"`
	Status        string                     `json:"status"`
	Reclaimable   bool                       `json:"reclaimable"`
	Reason        string                     `json:"reason,omitempty"`
	Owner         *compositionBuildLockOwner `json:"owner,omitempty"`
}

func commandQuartetCompositionLockStatus(args []string) error {
	flags := flag.NewFlagSet("quartet-composition-lock-status", flag.ContinueOnError)
	var projectRoot, output string
	flags.StringVar(&projectRoot, "project-root", "", "project root containing the Quartet composition workspace")
	flags.StringVar(&output, "json", "", "also write the lock status report to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	resolved, err := payloadpreview.ResolveProjectRoot(projectRoot)
	if err != nil {
		return err
	}
	resolved, err = filepath.Abs(resolved)
	if err != nil {
		return err
	}
	report, err := buildQuartetCompositionLockStatusReport(resolved, time.Now())
	if err != nil {
		return err
	}
	return emit(report, output)
}

func buildQuartetCompositionLockStatusReport(projectRoot string, now time.Time) (quartetCompositionLockStatusReport, error) {
	lockPath, err := secureJoin(projectRoot, quartetCompositionLockRelative)
	if err != nil {
		return quartetCompositionLockStatusReport{}, err
	}
	report := quartetCompositionLockStatusReport{
		Type:          "br_quartet_composition_lock_status",
		FormatVersion: 1,
		GeneratedUTC:  now.UTC(),
		ProjectRoot:   projectRoot,
		LockPath:      filepath.ToSlash(quartetCompositionLockRelative),
		Status:        "unlocked",
	}
	if _, err := os.Lstat(lockPath); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return report, nil
		}
		return report, err
	}
	inspection, err := inspectCompositionBuildLock(lockPath, now)
	if err != nil {
		return quartetCompositionLockStatusReport{}, err
	}
	report.Status = inspection.State
	report.Reclaimable = inspection.Reclaim
	report.Reason = inspection.Reason
	owner, _, ownerErr := readCompositionBuildLockOwner(lockPath)
	if ownerErr == nil {
		report.Owner = &owner
	} else if !errors.Is(ownerErr, os.ErrNotExist) {
		return quartetCompositionLockStatusReport{}, ownerErr
	}
	return report, nil
}
