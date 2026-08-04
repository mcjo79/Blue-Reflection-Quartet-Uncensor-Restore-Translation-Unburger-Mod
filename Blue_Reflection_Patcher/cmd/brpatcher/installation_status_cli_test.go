package main

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
)

func TestOverallInstallationStatus(t *testing.T) {
	cases := []struct {
		active  installstate.Inspection
		base    baseline.Inspection
		status  string
		allowed bool
	}{
		{active: installstate.Inspection{Status: installstate.InspectionMatchesInstalled, Active: true}, status: installstate.InspectionMatchesInstalled, allowed: true},
		{active: installstate.Inspection{Status: installstate.InspectionPartiallyDisplaced, Active: true}, status: installstate.InspectionPartiallyDisplaced, allowed: false},
		{active: installstate.Inspection{Status: installstate.InspectionNotActive}, base: baseline.Inspection{Status: "not_captured"}, status: "untracked", allowed: true},
		{active: installstate.Inspection{Status: installstate.InspectionNotActive}, base: baseline.Inspection{Status: "matches_known_baseline"}, status: "inactive_matches_known_baseline", allowed: true},
	}
	for _, item := range cases {
		status, allowed := overallInstallationStatus(item.active, item.base)
		if status != item.status || allowed != item.allowed {
			t.Fatalf("unexpected status: got %s/%v want %s/%v", status, allowed, item.status, item.allowed)
		}
	}
}

func TestBuildManagedFileStatusClassifiesActiveAndExternalFiles(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(filepath.Join(game, "DATA"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "DATA", "PACK01.PAK"), []byte("current"), 0o644); err != nil {
		t.Fatal(err)
	}
	items, err := buildManagedFileStatus(game, installstate.Inspection{Files: []installstate.FileComparison{{
		RelativePath: "DATA/PACK01.PAK", CurrentState: "file", CurrentSHA256: "current",
		InstalledSHA256: "current", BaselineSHA256: "base", MatchesInstalled: true,
	}}}, baseline.Inspection{})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Classification != "active_mod_payload" || items[0].ResolvedPath == "" {
		t.Fatalf("unexpected managed status: %+v", items)
	}
}
