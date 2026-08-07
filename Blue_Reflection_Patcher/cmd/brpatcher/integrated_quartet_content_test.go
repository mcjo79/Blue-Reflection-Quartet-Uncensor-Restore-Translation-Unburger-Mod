package main

import (
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func integratedSelection(modules ...string) model.SelectionResult {
	return model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID:          "blue_reflection_quartet",
		DisplayName:       "BLUE REFLECTION Quartet",
		Root:              "/game",
		SelectedModuleIDs: modules,
	}}}
}

func TestIntegratedQuartetContentRouting(t *testing.T) {
	cases := []struct {
		name    string
		modules []string
		want    bool
	}{
		{"translation", []string{quartetTranslationModule}, true},
		{"restoration", []string{quartetRestorationModule}, true},
		{"legacy", []string{quartetLegacyDLCModule}, true},
		{"translation restoration", []string{quartetTranslationModule, quartetRestorationModule}, true},
		{"all three", []string{quartetTranslationModule, quartetRestorationModule, quartetLegacyDLCModule}, true},
		{"unrelated", []string{"unrelated_module"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, got, err := selectionUsesIntegratedQuartetContent(integratedSelection(tc.modules...))
			if err != nil {
				t.Fatalf("selection error: %v", err)
			}
			if got != tc.want {
				t.Fatalf("requested=%v want=%v", got, tc.want)
			}
		})
	}
}

func TestIntegratedQuartetContentRejectsMixedUnknownModule(t *testing.T) {
	_, _, err := selectionUsesIntegratedQuartetContent(integratedSelection(quartetTranslationModule, "unknown"))
	if err != nil {
		t.Fatalf("unexpected selection error: %v", err)
	}
	// Unknown-module mixtures must fall back to the normal path rather than silently
	// routing only part of the requested selection through the integrated composer.
	_, requested, _ := selectionUsesIntegratedQuartetContent(integratedSelection(quartetTranslationModule, "unknown"))
	if requested {
		t.Fatalf("mixed unknown module must not use integrated route")
	}
}
