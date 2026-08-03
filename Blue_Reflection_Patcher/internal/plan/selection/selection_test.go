package selection

import (
	"reflect"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/catalog"
)

func detection(target string) []model.Detection {
	return []model.Detection{{TargetID: target, DisplayName: target, Root: "/game", Source: "current_directory"}}
}

func TestDefaultsByTarget(t *testing.T) {
	modules, err := catalog.Load()
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		target, selected string
		available        int
	}{
		{"blue_reflection_original", "blue_reflection_translation", 1},
		{"blue_reflection_quartet", "blue_reflection_translation,quartet_restoration", 3},
		{"second_light_original", "second_light_translation", 1},
	}
	for _, tc := range cases {
		result, err := Build(detection(tc.target), modules, nil, nil, "defaults")
		if err != nil {
			t.Fatal(err)
		}
		got := result.Targets[0]
		expected := strings.Split(tc.selected, ",")
		if len(got.AvailableModules) != tc.available || !reflect.DeepEqual(got.SelectedModuleIDs, expected) {
			t.Fatalf("unexpected selection for %s: %+v", tc.target, got)
		}
	}
}

func TestExplicitQuartetSelection(t *testing.T) {
	modules, _ := catalog.Load()
	result, err := Build(detection("blue_reflection_quartet"), modules,
		[]string{"blue_reflection_translation", "quartet_restoration"}, nil, "explicit")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Targets[0].SelectedModuleIDs) != 2 {
		t.Fatalf("unexpected selection: %+v", result)
	}
}

func TestUnsupportedSelectionFails(t *testing.T) {
	modules, _ := catalog.Load()
	_, err := Build(detection("blue_reflection_original"), modules,
		[]string{"quartet_restoration"}, nil, "explicit")
	if err == nil {
		t.Fatal("expected unsupported-module error")
	}
}
