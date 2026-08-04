package main

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func syntheticLocalBuildSelection(game string) model.SelectionResult {
	return model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID:          "blue_reflection_original",
		DisplayName:       "BLUE REFLECTION (2017)",
		Root:              game,
		SelectedModuleIDs: []string{"blue_reflection_translation"},
	}}}
}

func makeLocalBuildProject(t *testing.T, root string) {
	t.Helper()
	for _, relative := range []string{
		"workstreams/core/VERSION",
		"workstreams/core/local_translation_workflow.py",
		"Blue_Reflection_Patcher/go.mod",
	} {
		mustWriteTestFile(t, filepath.Join(root, relative), []byte("test\n"))
	}
}

func TestResolveLocalTranslationProjectRootDoesNotRequireRepackReport(t *testing.T) {
	root := t.TempDir()
	makeLocalBuildProject(t, root)
	workflow := filepath.Join(root, filepath.FromSlash(localTranslationWorkflowRelative))
	mustWriteTestFile(t, workflow, []byte("#!/bin/sh\nexit 0\n"))
	if err := os.Chmod(workflow, 0o755); err != nil {
		t.Fatal(err)
	}
	resolved, err := resolveLocalTranslationProjectRoot(filepath.Join(root, "Blue_Reflection_Patcher", "cmd"))
	if err != nil {
		t.Fatal(err)
	}
	if resolved != root {
		t.Fatalf("resolved %q, want %q", resolved, root)
	}
}

func TestRunLocalTranslationPreviewBuildUsesPreviewOnlyAndValidatesReport(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell fixture is Unix-only")
	}
	root := t.TempDir()
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	makeLocalBuildProject(t, root)
	workflow := filepath.Join(root, filepath.FromSlash(localTranslationWorkflowRelative))
	script := `#!/bin/sh
set -eu
report=""
game=""
modules=""
preview="no"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --json) report="$2"; shift 2 ;;
    --game-dir) game="$2"; shift 2 ;;
    --modules) modules="$2"; shift 2 ;;
    --preview-only) preview="yes"; shift ;;
    *) exit 91 ;;
  esac
done
[ "$preview" = yes ]
[ "$modules" = blue_reflection_translation ]
mkdir -p "$(dirname "$report")"
printf '{"type":"br_local_translation_workflow_report","status":"ready_preview_only","target_id":"blue_reflection_original","game_root":"%s","game_files_modified":false}\n' "$game" > "$report"
printf 'fixture build ok\n'
`
	mustWriteTestFile(t, workflow, []byte(script))
	if err := os.Chmod(workflow, 0o755); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	report, err := runLocalTranslationPreviewBuild(root, syntheticLocalBuildSelection(game), &output)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasSuffix(filepath.ToSlash(report), "/.local/reports/core/BR_LOCAL_TRANSLATION_GUIDED_BUILD_REPORT.json") {
		t.Fatalf("unexpected report path: %s", report)
	}
	if !strings.Contains(output.String(), "fixture build ok") {
		t.Fatalf("workflow output not forwarded: %s", output.String())
	}
}

func TestLocalTranslationBuildSelectionRejectsDLC(t *testing.T) {
	selection := syntheticLocalBuildSelection(t.TempDir())
	selection.Targets[0].SelectedModuleIDs = append(selection.Targets[0].SelectedModuleIDs, "quartet_legacy_dlc")
	if selectionSupportsLocalTranslationBuild(selection) {
		t.Fatal("local Translation builder accepted unsupported DLC selection")
	}
}

func TestChooseLocalTranslationBuildLine(t *testing.T) {
	for input, expected := range map[string]bool{
		"1\n": true,
		"y\n": true,
		"2\n": false,
		"\n":  false,
	} {
		var output bytes.Buffer
		got, err := chooseLocalTranslationBuildLine(strings.NewReader(input), &output)
		if err != nil {
			t.Fatalf("input %q: %v", input, err)
		}
		if got != expected {
			t.Fatalf("input %q: got %v want %v", input, got, expected)
		}
	}
}
