package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFieldProfileTargetSpecRegistered(t *testing.T) {
	spec, ok := localProfileTargets["Data/PACK10_03.PAK"]
	if !ok {
		t.Fatal("PACK10_03 field target is not registered")
	}
	if spec.Kind != "field" {
		t.Fatalf("field target kind=%q", spec.Kind)
	}
	if spec.StatePath != ".local/state/core_unified_patcher/quartet_field_profile.json" {
		t.Fatalf("field state path=%q", spec.StatePath)
	}
	if spec.ReportType != fieldProfileReportType {
		t.Fatalf("field report type=%q", spec.ReportType)
	}
}

func TestFieldProfileMutualExclusionChecksAllOtherTargets(t *testing.T) {
	projectRoot := t.TempDir()
	activeSpec := localProfileTargets["Data/PACK11.PAK"]
	statePath := filepath.Join(projectRoot, filepath.FromSlash(activeSpec.StatePath))
	if err := os.MkdirAll(filepath.Dir(statePath), 0o700); err != nil {
		t.Fatal(err)
	}
	state := `{
  "type": "br_core_quartet_local_profile_state",
  "format_version": 2,
  "status": "active",
  "profile_id": "synthetic_event_profile",
  "target_relative_path": "Data/PACK11.PAK"
}`
	if err := os.WriteFile(statePath, []byte(state), 0o600); err != nil {
		t.Fatal(err)
	}
	err := rejectOtherTargetTransaction(projectRoot, localProfileTargets["Data/PACK10_03.PAK"])
	if err == nil || !strings.Contains(err.Error(), "transaction is already open") {
		t.Fatalf("field activation was not blocked by event transaction: %v", err)
	}
}
