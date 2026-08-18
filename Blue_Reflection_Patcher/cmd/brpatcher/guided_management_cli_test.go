package main

import (
	"bytes"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/installstate"
)

func TestGuidedManagementLineSelection(t *testing.T) {
	state := guidedManagementState{
		Detection:  model.Detection{TargetID: "blue_reflection_original", DisplayName: "BLUE REFLECTION", Root: filepath.Join(t.TempDir(), "game")},
		Inspection: installstate.Inspection{Active: true, Status: installstate.InspectionMatchesInstalled, SelectedModules: []string{"blue_reflection_translation"}},
	}
	for input, expected := range map[string]guidedManagementAction{
		"1\n": guidedManagementContinue,
		"2\n": guidedManagementRemove,
		"3\n": guidedManagementCancel,
		"\n":  guidedManagementCancel,
	} {
		var out bytes.Buffer
		action, err := chooseGuidedInstallationManagementLine(state, strings.NewReader(input), &out)
		if err != nil {
			t.Fatalf("input %q: %v", input, err)
		}
		if action != expected {
			t.Fatalf("input %q: got %s want %s", input, action, expected)
		}
	}
}

func TestQuartetStartupOffersReusableDLCAssetBuilderWithoutManagedInstall(t *testing.T) {
	state := guidedManagementState{
		Detection:  model.Detection{TargetID: "blue_reflection_quartet", DisplayName: "BLUE REFLECTION Quartet", Root: filepath.Join(t.TempDir(), "game")},
		Inspection: installstate.Inspection{Active: false},
	}
	entries := guidedManagementEntries(state)
	if len(entries) != 3 {
		t.Fatalf("Quartet unmanaged startup entries=%d, want 3: %+v", len(entries), entries)
	}
	if entries[0].action != guidedManagementContinue || entries[1].action != guidedManagementCreateDLCAssets || entries[2].action != guidedManagementCancel {
		t.Fatalf("unexpected Quartet unmanaged startup actions: %+v", entries)
	}
	var out bytes.Buffer
	action, err := chooseGuidedInstallationManagementLine(state, strings.NewReader("2\n"), &out)
	if err != nil {
		t.Fatal(err)
	}
	if action != guidedManagementCreateDLCAssets {
		t.Fatalf("choice 2 got %s, want %s", action, guidedManagementCreateDLCAssets)
	}
}

func TestQuartetManagedStartupKeepsInstallFirstAndAddsBundleBeforeRemove(t *testing.T) {
	state := guidedManagementState{
		Detection:  model.Detection{TargetID: "blue_reflection_quartet", DisplayName: "BLUE REFLECTION Quartet", Root: filepath.Join(t.TempDir(), "game")},
		Inspection: installstate.Inspection{Active: true, SelectedModules: []string{"quartet_restoration"}},
	}
	entries := guidedManagementEntries(state)
	want := []guidedManagementAction{guidedManagementContinue, guidedManagementCreateDLCAssets, guidedManagementRemove, guidedManagementCancel}
	if len(entries) != len(want) {
		t.Fatalf("Quartet managed startup entries=%d, want %d", len(entries), len(want))
	}
	for i := range want {
		if entries[i].action != want[i] {
			t.Fatalf("entry %d action=%s want=%s", i, entries[i].action, want[i])
		}
	}
}
