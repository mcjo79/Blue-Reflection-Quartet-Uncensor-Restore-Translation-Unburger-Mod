package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"local/blue-reflection-patcher/internal/model"
)

func writeDetectionMarker(t *testing.T, game, relative string) {
	t.Helper()
	marker := filepath.Join(game, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(marker), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(marker, []byte("pak"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func withSteamDetectionAnchors(t *testing.T, fn func() []string) {
	t.Helper()
	old := steamDetectionAnchors
	steamDetectionAnchors = fn
	t.Cleanup(func() { steamDetectionAnchors = old })
}

func chdirForTest(t *testing.T, path string) {
	t.Helper()
	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(path); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(old) })
}

func TestPromptedPathFallback(t *testing.T) {
	game := t.TempDir()
	writeDetectionMarker(t, game, "Data/PACK02.PAK")

	empty := t.TempDir()
	chdirForTest(t, empty)
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	withSteamDetectionAnchors(t, func() []string { return nil })

	specs := []model.TargetSpec{{
		TargetID: "second_light", DisplayName: "Second Light",
		RequiredFiles: []string{"Data/PACK02.PAK"},
	}}
	var output bytes.Buffer
	items, err := detectWithFallback(specs, nil, true, strings.NewReader(game+"\n"), &output)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Source != "prompted_path" {
		t.Fatalf("unexpected detections: %+v", items)
	}
	if !strings.Contains(output.String(), "Searching default Steam libraries") || !strings.Contains(output.String(), "Enter the game directory path") {
		t.Fatalf("fallback progress/prompt was not written: %q", output.String())
	}
}

func TestAutomaticSteamLibraryDetectionUsesLibraryFoldersVDF(t *testing.T) {
	primary := filepath.Join(t.TempDir(), "Steam")
	extra := filepath.Join(t.TempDir(), "SteamLibrary")
	if err := os.MkdirAll(filepath.Join(primary, "steamapps"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(extra, "steamapps", "common"), 0o755); err != nil {
		t.Fatal(err)
	}
	vdf := fmt.Sprintf("\"libraryfolders\"\n{\n  \"1\"\n  {\n    \"path\" \"%s\"\n  }\n}\n", filepath.ToSlash(extra))
	if err := os.WriteFile(filepath.Join(primary, "steamapps", "libraryfolders.vdf"), []byte(vdf), 0o644); err != nil {
		t.Fatal(err)
	}
	game := filepath.Join(extra, "steamapps", "common", "Arbitrary Folder Name")
	writeDetectionMarker(t, game, "Data/PACK02.PAK")

	chdirForTest(t, t.TempDir())
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	withSteamDetectionAnchors(t, func() []string { return []string{primary} })

	specs := []model.TargetSpec{{TargetID: "sl", DisplayName: "Second Light", RequiredFiles: []string{"Data/PACK02.PAK"}}}
	var output bytes.Buffer
	items, err := detectWithFallback(specs, nil, false, strings.NewReader(""), &output)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("expected one Steam detection, got %+v", items)
	}
	if items[0].Source != "steam_library" || filepath.Clean(items[0].Root) != filepath.Clean(game) {
		t.Fatalf("unexpected Steam detection: %+v", items[0])
	}
	if !strings.Contains(output.String(), "Searching default Steam libraries") {
		t.Fatalf("Steam discovery message missing: %q", output.String())
	}
}

func TestCurrentDirectoryWinsBeforeManagedStateAndSteam(t *testing.T) {
	localGame := t.TempDir()
	writeDetectionMarker(t, localGame, "Data/PACK02.PAK")
	chdirForTest(t, localGame)

	stateRoot := t.TempDir()
	t.Setenv("XDG_STATE_HOME", stateRoot)
	rememberedGame := t.TempDir()
	writeDetectionMarker(t, rememberedGame, "Data/PACK02.PAK")
	stateDir := filepath.Join(stateRoot, "unburger-patcher", "blue-reflection", "installations", "sl-test")
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		t.Fatal(err)
	}
	stateJSON := fmt.Sprintf(`{"status":"active","target_id":"sl","game_root":%q}`, rememberedGame)
	if err := os.WriteFile(filepath.Join(stateDir, "active_state.json"), []byte(stateJSON), 0o644); err != nil {
		t.Fatal(err)
	}

	steamRoot := filepath.Join(t.TempDir(), "Steam")
	steamGame := filepath.Join(steamRoot, "steamapps", "common", "Another Game")
	writeDetectionMarker(t, steamGame, "Data/PACK02.PAK")
	withSteamDetectionAnchors(t, func() []string { return []string{steamRoot} })

	specs := []model.TargetSpec{{TargetID: "sl", DisplayName: "Second Light", RequiredFiles: []string{"Data/PACK02.PAK"}}}
	items, err := detectWithFallback(specs, nil, false, strings.NewReader(""), &bytes.Buffer{})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Source != "current_directory" || filepath.Clean(items[0].Root) != filepath.Clean(localGame) {
		t.Fatalf("current directory did not win: %+v", items)
	}
}

func TestRememberedManagedInstallationWinsBeforeSteam(t *testing.T) {
	chdirForTest(t, t.TempDir())
	stateRoot := t.TempDir()
	t.Setenv("XDG_STATE_HOME", stateRoot)

	rememberedGame := t.TempDir()
	writeDetectionMarker(t, rememberedGame, "Data/PACK02.PAK")
	stateDir := filepath.Join(stateRoot, "unburger-patcher", "blue-reflection", "installations", "sl-test")
	if err := os.MkdirAll(stateDir, 0o755); err != nil {
		t.Fatal(err)
	}
	stateJSON := fmt.Sprintf(`{"status":"active","target_id":"sl","game_root":%q}`, rememberedGame)
	if err := os.WriteFile(filepath.Join(stateDir, "active_state.json"), []byte(stateJSON), 0o644); err != nil {
		t.Fatal(err)
	}

	steamRoot := filepath.Join(t.TempDir(), "Steam")
	steamGame := filepath.Join(steamRoot, "steamapps", "common", "Another Game")
	writeDetectionMarker(t, steamGame, "Data/PACK02.PAK")
	withSteamDetectionAnchors(t, func() []string { return []string{steamRoot} })

	specs := []model.TargetSpec{{TargetID: "sl", DisplayName: "Second Light", RequiredFiles: []string{"Data/PACK02.PAK"}}}
	var output bytes.Buffer
	items, err := detectWithFallback(specs, nil, false, strings.NewReader(""), &output)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Source != "managed_state" || filepath.Clean(items[0].Root) != filepath.Clean(rememberedGame) {
		t.Fatalf("remembered managed installation did not win: %+v", items)
	}
	if !strings.Contains(output.String(), "previously managed installation") {
		t.Fatalf("managed-state message missing: %q", output.String())
	}
}

func TestSteamLibraryIndexAcceptsLegacyFormat(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "libraryfolders.vdf")
	first := filepath.Join(root, "one")
	second := filepath.Join(root, "two")
	content := fmt.Sprintf("\"LibraryFolders\"\n{\n  \"1\" \"%s\"\n  \"2\"\n  {\n    \"path\" \"%s\"\n  }\n}\n", filepath.ToSlash(first), filepath.ToSlash(second))
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	got := parseSteamLibraryIndex(path)
	if len(got) != 2 || filepath.Clean(got[0]) != filepath.Clean(first) || filepath.Clean(got[1]) != filepath.Clean(second) {
		t.Fatalf("unexpected library index parse: %#v", got)
	}
}

func TestChooseDetectedInstallationLineMode(t *testing.T) {
	items := []model.Detection{
		{TargetID: "a", DisplayName: "Game A", Root: "/a", Source: "steam_library"},
		{TargetID: "b", DisplayName: "Game B", Root: "/b", Source: "steam_library"},
	}
	var output bytes.Buffer
	chosen, err := chooseDetectedInstallation(items, strings.NewReader("2\n"), &output)
	if err != nil {
		t.Fatal(err)
	}
	if chosen.TargetID != "b" {
		t.Fatalf("wrong selection: %+v", chosen)
	}
	if !strings.Contains(output.String(), "Multiple supported installations") {
		t.Fatalf("selection prompt missing: %q", output.String())
	}
}

func TestLegacyAssetAutodiscoveryDoesNotUseCurrentDirectory(t *testing.T) {
	unrelated := t.TempDir()
	chdirForTest(t, unrelated)
	releaseRoot := t.TempDir()
	projectRoot := t.TempDir()
	roots := nearbyLegacyAssetSearchRoots(releaseRoot, projectRoot)
	if len(roots) < 2 {
		t.Fatalf("expected release/project roots, got %#v", roots)
	}
	if filepath.Clean(roots[0]) != filepath.Clean(releaseRoot) {
		t.Fatalf("release root must have first priority: %#v", roots)
	}
	for _, root := range roots {
		if filepath.Clean(root) == filepath.Clean(unrelated) {
			t.Fatalf("current directory leaked into automatic .unburger-assets search: %#v", roots)
		}
	}
}

func TestRememberedManagedHistorySkipsOrphanCommittedAndKeepsRolledBack(t *testing.T) {
	stateHome := t.TempDir()
	t.Setenv("XDG_STATE_HOME", stateHome)

	historicalGame := t.TempDir()
	vmGame := t.TempDir()
	base := filepath.Join(stateHome, "unburger-patcher", "blue-reflection", "installations")

	writeJournal := func(installation, txID, status, game string, updated time.Time) {
		t.Helper()
		dir := filepath.Join(base, installation, "transactions", txID)
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		payload := map[string]any{
			"status":      status,
			"game_root":   game,
			"updated_utc": updated.UTC(),
			"metadata":    map[string]string{"target_id": "blue_reflection_quartet"},
		}
		data, err := json.Marshal(payload)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "journal.json"), data, 0o644); err != nil {
			t.Fatal(err)
		}
	}

	writeJournal("historical", "old-commit", "committed", historicalGame, time.Date(2026, 8, 8, 15, 11, 7, 0, time.UTC))
	writeJournal("vm", "new-rollback", "rolled_back", vmGame, time.Date(2026, 8, 9, 14, 53, 41, 0, time.UTC))

	items := rememberedInstallationCandidates()
	if len(items) != 1 {
		t.Fatalf("remembered candidates = %+v, expected only rolled-back history", items)
	}
	if items[0].Source != "managed_history" || filepath.Clean(items[0].Path) != filepath.Clean(vmGame) {
		t.Fatalf("wrong managed-history candidate: %+v", items[0])
	}
}

func TestRememberedActiveStateOutranksManagedHistory(t *testing.T) {
	stateHome := t.TempDir()
	t.Setenv("XDG_STATE_HOME", stateHome)
	activeGame := t.TempDir()
	historyGame := t.TempDir()
	base := filepath.Join(stateHome, "unburger-patcher", "blue-reflection", "installations")

	activeDir := filepath.Join(base, "active")
	if err := os.MkdirAll(activeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	activeJSON := fmt.Sprintf(`{"status":"active","target_id":"blue_reflection_quartet","game_root":%q}`, activeGame)
	if err := os.WriteFile(filepath.Join(activeDir, "active_state.json"), []byte(activeJSON), 0o644); err != nil {
		t.Fatal(err)
	}

	txDir := filepath.Join(base, "history", "transactions", "rolled")
	if err := os.MkdirAll(txDir, 0o755); err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(map[string]any{
		"status":      "rolled_back",
		"game_root":   historyGame,
		"updated_utc": time.Now().UTC().Add(time.Hour),
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(txDir, "journal.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}

	items := rememberedInstallationCandidates()
	if len(items) != 2 {
		t.Fatalf("remembered candidates = %+v", items)
	}
	if items[0].Source != "managed_state" || filepath.Clean(items[0].Path) != filepath.Clean(activeGame) {
		t.Fatalf("active state did not have first priority: %+v", items)
	}
	if items[1].Source != "managed_history" || filepath.Clean(items[1].Path) != filepath.Clean(historyGame) {
		t.Fatalf("history candidate missing/incorrect: %+v", items)
	}
}
