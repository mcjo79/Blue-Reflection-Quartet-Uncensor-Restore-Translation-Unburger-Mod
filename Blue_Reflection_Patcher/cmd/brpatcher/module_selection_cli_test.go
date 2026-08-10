package main

import (
	"bufio"
	"bytes"
	"reflect"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/catalog"
)

func TestInteractiveQuartetSelection(t *testing.T) {
	modules, _ := catalog.Load()
	detections := []model.Detection{{TargetID: "blue_reflection_quartet", DisplayName: "Quartet", Root: "/game", Source: "current_directory"}}
	var output bytes.Buffer
	result, err := chooseModules(modules, detections, nil, false, true, strings.NewReader("1,2\n"), &output)
	if err != nil {
		t.Fatal(err)
	}
	if result.Mode != "interactive" || len(result.Targets[0].SelectedModuleIDs) != 2 {
		t.Fatalf("unexpected result: %+v", result)
	}
	got := result.Targets[0].SelectedModuleIDs
	if got[0] != "blue_reflection_translation" || got[1] != "quartet_restoration" {
		t.Fatalf("unexpected module IDs: %+v", got)
	}
	if !strings.Contains(output.String(), "Available modules for Quartet") {
		t.Fatalf("missing prompt output: %s", output.String())
	}
}

func TestExplicitNone(t *testing.T) {
	values, set := parseModuleList("none")
	if !set || values == nil || len(values) != 0 {
		t.Fatalf("unexpected parse: %#v %v", values, set)
	}
}

func TestMenuArrowKeysAndEnter(t *testing.T) {
	cases := []struct {
		raw  string
		want menuKey
	}{
		{"\x1b[A", keyUp},
		{"\x1b[B", keyDown},
		{"\r", keyEnter},
		{" ", keyToggle},
		{"q", keyCancel},
	}
	for _, tc := range cases {
		got, err := readMenuKey(bufio.NewReader(strings.NewReader(tc.raw)))
		if err != nil {
			t.Fatal(err)
		}
		if got != tc.want {
			t.Fatalf("key %q: expected %v, got %v", tc.raw, tc.want, got)
		}
	}
}

func TestQuartetDefaultsEnableTranslationRestorationAndDLC(t *testing.T) {
	modules, _ := catalog.Load()
	detections := []model.Detection{{TargetID: "blue_reflection_quartet", DisplayName: "Quartet", Root: "/game"}}
	result, err := chooseModules(modules, detections, nil, false, false, strings.NewReader(""), &bytes.Buffer{})
	if err != nil {
		t.Fatal(err)
	}
	got := result.Targets[0].SelectedModuleIDs
	want := []string{"blue_reflection_translation", "quartet_legacy_dlc", "quartet_movie_restoration", "quartet_restoration"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected Quartet defaults: %+v", got)
	}
}

func TestMovieRestorationToggleMaintainsUNCENSORDependency(t *testing.T) {
	modules, err := catalog.Load()
	if err != nil {
		t.Fatal(err)
	}
	var available []model.BundleModule
	for _, module := range modules {
		if contains(module.SupportedTargets, "blue_reflection_quartet") {
			available = append(available, module)
		}
	}
	selected := map[string]bool{}
	toggleModuleSelection(available, selected, quartetMovieRestorationModule)
	if !selected[quartetMovieRestorationModule] || !selected[quartetRestorationModule] {
		t.Fatalf("movie restoration did not enable UNCENSOR dependency: %+v", selected)
	}
	toggleModuleSelection(available, selected, quartetRestorationModule)
	if selected[quartetRestorationModule] || selected[quartetMovieRestorationModule] {
		t.Fatalf("disabling UNCENSOR left its movie add-on selected: %+v", selected)
	}
}
