package main

import (
	"bytes"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

type lineChunksReader struct {
	chunks []string
	index  int
}

func (r *lineChunksReader) Read(p []byte) (int, error) {
	if r.index >= len(r.chunks) {
		return 0, io.EOF
	}
	chunk := []byte(r.chunks[r.index])
	r.index++
	n := copy(p, chunk)
	if n < len(chunk) {
		return n, nil
	}
	return n, nil
}

func isolateSaveDiscoveryHome(t *testing.T) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
}

func writeFakeSaveMarker(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("placeholder"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestPrefixSaveSelectionsAcceptsLoosePrefix(t *testing.T) {
	prefix := t.TempDir()
	saveDir := filepath.Join(prefix, "drive_c", "users", "tester", "AppData", "Local", "KoeiTecmo", "BLUE REFLECTION Quartet", "BLUE REFLECTION")
	writeFakeSaveMarker(t, filepath.Join(saveDir, "GAMEDATA01.pcsave"))

	found, err := prefixSaveSelections(prefix, "test-prefix")
	if err != nil {
		t.Fatal(err)
	}
	if len(found) != 1 {
		t.Fatalf("got %d save roots, want 1", len(found))
	}
	if found[0].Root != saveDir {
		t.Fatalf("root=%q want %q", found[0].Root, saveDir)
	}
	if len(found[0].Files) != 1 || found[0].Files[0] != filepath.Join(saveDir, "GAMEDATA01.pcsave") {
		t.Fatalf("unexpected files: %#v", found[0].Files)
	}
}

func TestPrefixSaveSelectionsAcceptsCompatdataRoot(t *testing.T) {
	compat := t.TempDir()
	saveDir := filepath.Join(compat, "pfx", "drive_c", "users", "steamuser", "AppData", "Local", "KoeiTecmo", "BLUE REFLECTION Quartet", "BLUE REFLECTION")
	writeFakeSaveMarker(t, filepath.Join(saveDir, "GAMEDATA02.pcsave"))

	found, err := prefixSaveSelections(compat, "compatdata")
	if err != nil {
		t.Fatal(err)
	}
	if len(found) != 1 || found[0].Root != saveDir {
		t.Fatalf("unexpected resolution: %#v", found)
	}
}

func TestPrefixSaveSelectionsAcceptsSingleSaveFile(t *testing.T) {
	dir := t.TempDir()
	save := filepath.Join(dir, "GAMEDATA03.pcsave")
	writeFakeSaveMarker(t, save)
	writeFakeSaveMarker(t, filepath.Join(dir, "GAMEDATA04.pcsave"))

	found, err := prefixSaveSelections(save, "single")
	if err != nil {
		t.Fatal(err)
	}
	if len(found) != 1 || len(found[0].Files) != 1 || found[0].Files[0] != save {
		t.Fatalf("single-file selection expanded unexpectedly: %#v", found)
	}
}

func TestDiscoverQuartetSaveSelectionsUsesLocalAppData(t *testing.T) {
	isolateSaveDiscoveryHome(t)
	local := t.TempDir()
	saveDir := filepath.Join(local, "KoeiTecmo", "BLUE REFLECTION Quartet", "BLUE REFLECTION")
	writeFakeSaveMarker(t, filepath.Join(saveDir, "GAMEDATA05.pcsave"))
	t.Setenv("LOCALAPPDATA", local)
	t.Setenv("WINEPREFIX", "")
	t.Setenv("STEAM_COMPAT_DATA_PATH", "")

	found, err := discoverQuartetSaveSelections(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	seen := false
	for _, candidate := range found {
		if candidate.Root == saveDir {
			seen = true
			break
		}
	}
	if !seen {
		t.Fatalf("LOCALAPPDATA save root was not discovered: %#v", found)
	}
}

func TestChooseQuartetSaveSelectionAlwaysOffersManualFallback(t *testing.T) {
	isolateSaveDiscoveryHome(t)
	local := t.TempDir()
	autoDir := filepath.Join(local, "KoeiTecmo", "BLUE REFLECTION Quartet", "BLUE REFLECTION")
	writeFakeSaveMarker(t, filepath.Join(autoDir, "GAMEDATA00.pcsave"))
	manualDir := t.TempDir()
	writeFakeSaveMarker(t, filepath.Join(manualDir, "GAMEDATA09.pcsave"))
	t.Setenv("LOCALAPPDATA", local)
	t.Setenv("WINEPREFIX", "")
	t.Setenv("STEAM_COMPAT_DATA_PATH", "")

	input := &lineChunksReader{chunks: []string{"2\n", manualDir + "\n"}}
	var output bytes.Buffer
	selected, err := chooseQuartetSaveSelection("", t.TempDir(), true, input, &output)
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Clean(selected.Root) != filepath.Clean(manualDir) || !strings.Contains(selected.Origin, "prompted") {
		t.Fatalf("manual save selection not used: %+v", selected)
	}
	if !strings.Contains(output.String(), "Enter / paste save folder / .pcsave / Wine or Proton prefix manually") {
		t.Fatalf("manual save-path fallback missing from installer UI: %q", output.String())
	}
}

func TestSteamappsFromGameRootDoesNotUseAppID(t *testing.T) {
	library := t.TempDir()
	game := filepath.Join(library, "steamapps", "common", "Any Folder Name")
	if err := os.MkdirAll(game, 0o755); err != nil {
		t.Fatal(err)
	}
	got := steamappsFromGameRoot(game)
	want := filepath.Join(library, "steamapps")
	if got != want {
		t.Fatalf("got %q want %q", got, want)
	}
}

func TestReportNeedsSaveWrite(t *testing.T) {
	if reportNeedsSaveWrite(br1rebuild.SaveAccessReport{}) {
		t.Fatal("empty report should not need a write")
	}
	if !reportNeedsSaveWrite(br1rebuild.SaveAccessReport{IslandChanged: true}) {
		t.Fatal("Island gate change should require a write")
	}
	if !reportNeedsSaveWrite(br1rebuild.SaveAccessReport{WardrobeBytesChanged: 1}) {
		t.Fatal("costume flag change should require a write")
	}
}

func TestSaveSelectionFromDirectoryIncludesAutosaveAndAllSlots(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"AUTOSAVE.pcsave", "GAMEDATA00.pcsave", "GAMEDATA01.pcsave", "GAMEDATA02.pcsave", "GAMEDATA03.pcsave"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("save"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{
		"GAMEDATA00.pcsave.unburger-before-br1-content-20260809T000000Z",
		"GAMEDATA01.pcsave.pre",
		"notes.txt",
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("backup"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	selection, ok, err := saveSelectionFromDirectory(dir, "test")
	if err != nil {
		t.Fatal(err)
	}
	if !ok {
		t.Fatal("save folder was not detected")
	}
	if got, want := len(selection.Files), 5; got != want {
		t.Fatalf("got %d current saves, want %d: %v", got, want, selection.Files)
	}
	wantNames := []string{"AUTOSAVE.pcsave", "GAMEDATA00.pcsave", "GAMEDATA01.pcsave", "GAMEDATA02.pcsave", "GAMEDATA03.pcsave"}
	for i, want := range wantNames {
		if got := filepath.Base(selection.Files[i]); got != want {
			t.Fatalf("save %d: got %q want %q", i, got, want)
		}
	}
}
