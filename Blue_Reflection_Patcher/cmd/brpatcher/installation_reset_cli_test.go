package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func resetWrite(t *testing.T, path, value string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
		t.Fatal(err)
	}
}

func prepareActiveResetFixture(t *testing.T) (string, string, string) {
	t.Helper()
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	resetWrite(t, target, "original")
	resetWrite(t, payload, "installed-mod")
	base, err := baseline.Ensure(game, state, "blue_reflection_original", []string{"DATA/PACK01.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{
		RelativePath: "DATA/PACK01.PAK", StagedPath: payload,
	}}, []string{"blue_reflection_translation"}, map[string]string{"target_id": "blue_reflection_original"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transaction.Commit(prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	if _, err := installstate.Activate(state, "blue_reflection_original", game, base.ManifestPath, prepared.JournalPath); err != nil {
		t.Fatal(err)
	}
	return game, state, target
}

func TestAdoptCurrentInstallationArchivesStateAndLeavesGameUntouched(t *testing.T) {
	game, state, target := prepareActiveResetFixture(t)
	resetWrite(t, target, "manual-current")
	resetWrite(t, filepath.Join(game, "DATA", "PACK00_02.PAK_"), "old-analytical")

	report, err := adoptCurrentInstallationState("blue_reflection_original", "Blue Reflection", game, state)
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "manual-current" || report.GameFilesModified {
		t.Fatalf("adoption modified game file: %q report=%+v", data, report)
	}
	if _, err := os.Stat(report.ArchivedPreviousState); err != nil {
		t.Fatalf("previous state archive is missing: %v", err)
	}
	if _, exists, err := installstate.Load(state, "blue_reflection_original", game); err != nil || exists {
		t.Fatalf("active state was not retired: exists=%v err=%v", exists, err)
	}
	inspection, err := baseline.Inspect(game, state, "blue_reflection_original")
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != "matches_known_baseline" || inspection.BaselineCount != 1 {
		t.Fatalf("adopted baseline is not current: %+v", inspection)
	}
	latest := inspection.Baselines[0]
	if latest.Classification != baseline.ClassificationManualAdoptCurrent || latest.SourceClassification != baseline.SourceCurrentInstallation {
		t.Fatalf("adoption provenance is missing: %+v", latest)
	}
	if len(report.AdoptedPaths) != 1 || report.AdoptedPaths[0] != "DATA/PACK01.PAK" {
		t.Fatalf("unexpected adopted paths: %+v", report.AdoptedPaths)
	}
	if len(report.IgnoredAnalyticalArchives) != 1 || !strings.HasSuffix(strings.ToLower(report.IgnoredAnalyticalArchives[0].RelativePath), ".pak_") {
		t.Fatalf("analytical archive was not reported as ignored: %+v", report.IgnoredAnalyticalArchives)
	}
	if _, err := os.Stat(report.ReportPath); err != nil {
		t.Fatalf("adoption report was not persisted: %v", err)
	}
}

func TestAdoptCurrentInstallationRejectsStillActiveMod(t *testing.T) {
	game, state, _ := prepareActiveResetFixture(t)
	if _, err := adoptCurrentInstallationState("blue_reflection_original", "Blue Reflection", game, state); err == nil || !strings.Contains(err.Error(), "still match") {
		t.Fatalf("active mod was not rejected: %v", err)
	}
}

func TestAdoptCurrentInstallationRejectsPreparedTransaction(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	resetWrite(t, target, "first")
	if _, err := baseline.Ensure(game, state, "blue_reflection_original", []string{"DATA/PACK01.PAK"}); err != nil {
		t.Fatal(err)
	}
	resetWrite(t, target, "external-current")
	resetWrite(t, payload, "pending")
	if _, err := transaction.Prepare(game, state, []transaction.ChangeSpec{{RelativePath: "DATA/PACK01.PAK", StagedPath: payload}}, nil, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := adoptCurrentInstallationState("blue_reflection_original", "Blue Reflection", game, state); err == nil || !strings.Contains(err.Error(), "non-terminal transaction") {
		t.Fatalf("prepared transaction was not rejected: %v", err)
	}
}
