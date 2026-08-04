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
