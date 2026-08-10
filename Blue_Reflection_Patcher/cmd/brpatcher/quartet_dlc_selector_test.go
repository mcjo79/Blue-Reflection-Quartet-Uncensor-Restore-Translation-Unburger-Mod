package main

import (
	"bytes"
	"reflect"
	"strings"
	"testing"
)

func TestQuartetDLCDefaultsEnableBothSourceGames(t *testing.T) {
	got := selectedQuartetDLCFamilies(defaultQuartetDLCSelection())
	want := []quartetDLCFamily{quartetDLCBlueReflection, quartetDLCSecondLight}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("defaults = %v, want %v", got, want)
	}
}

func TestQuartetDLCMenuRendersBothSourceGamesAndContinue(t *testing.T) {
	var out bytes.Buffer
	renderQuartetDLCMenu(&out, defaultQuartetDLCSelection(), len(quartetDLCChoices))
	text := out.String()
	for _, want := range []string{"BLUE REFLECTION", "BLUE REFLECTION: Second Light", "[ Continue ]"} {
		if !strings.Contains(text, want) {
			t.Fatalf("menu missing %q:\n%s", want, text)
		}
	}
	if !strings.Contains(text, "› ") {
		t.Fatalf("menu does not render the initial Continue cursor:\n%s", text)
	}
}

func TestQuartetDLCSelectionCanDisableOneFamily(t *testing.T) {
	selected := defaultQuartetDLCSelection()
	selected[quartetDLCBlueReflection] = false
	got := selectedQuartetDLCFamilies(selected)
	want := []quartetDLCFamily{quartetDLCSecondLight}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("selection = %v, want %v", got, want)
	}
}
