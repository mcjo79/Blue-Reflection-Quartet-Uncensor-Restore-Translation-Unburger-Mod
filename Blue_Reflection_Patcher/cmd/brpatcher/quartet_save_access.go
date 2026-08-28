package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/targets"
)

const quartetSaveSubpath = "KoeiTecmo/BLUE REFLECTION Quartet/BLUE REFLECTION"

var errQuartetSaveAccessCancelled = errors.New("save access update cancelled")

type quartetSaveSelection struct {
	Root   string   `json:"root"`
	Files  []string `json:"files"`
	Origin string   `json:"origin"`
}

type quartetSaveAccessResult struct {
	Type             string                        `json:"type"`
	Status           string                        `json:"status"`
	GameRoot         string                        `json:"game_root"`
	SaveRoot         string                        `json:"save_root"`
	SaveOrigin       string                        `json:"save_origin"`
	SaveCount        int                           `json:"save_count"`
	ChangedSaveCount int                           `json:"changed_save_count"`
	Reports          []br1rebuild.SaveAccessReport `json:"reports"`
}

func saveSelectionFromDirectory(path, origin string) (quartetSaveSelection, bool, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return quartetSaveSelection{}, false, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		if os.IsNotExist(err) {
			return quartetSaveSelection{}, false, nil
		}
		return quartetSaveSelection{}, false, err
	}
	if !info.IsDir() {
		return quartetSaveSelection{}, false, nil
	}
	files, err := br1rebuild.DiscoverSaveFiles(absolute)
	if err != nil {
		return quartetSaveSelection{}, false, err
	}
	if len(files) == 0 {
		return quartetSaveSelection{}, false, nil
	}
	return quartetSaveSelection{Root: absolute, Files: files, Origin: origin}, true, nil
}

func saveSelectionFromFile(path, origin string) (quartetSaveSelection, bool, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return quartetSaveSelection{}, false, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		if os.IsNotExist(err) {
			return quartetSaveSelection{}, false, nil
		}
		return quartetSaveSelection{}, false, err
	}
	if !info.Mode().IsRegular() || !strings.HasSuffix(strings.ToLower(info.Name()), ".pcsave") {
		return quartetSaveSelection{}, false, nil
	}
	return quartetSaveSelection{Root: filepath.Dir(absolute), Files: []string{absolute}, Origin: origin}, true, nil
}

func prefixSaveSelections(prefix, origin string) ([]quartetSaveSelection, error) {
	prefix = strings.Trim(strings.TrimSpace(prefix), `"`)
	if prefix == "" {
		return nil, nil
	}
	absolute, err := filepath.Abs(prefix)
	if err != nil {
		return nil, err
	}
	info, err := os.Stat(absolute)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	if info.Mode().IsRegular() {
		if selected, ok, err := saveSelectionFromFile(absolute, origin+":file"); err != nil || ok {
			if err != nil {
				return nil, err
			}
			return []quartetSaveSelection{selected}, nil
		}
		return nil, nil
	}

	if selected, ok, err := saveSelectionFromDirectory(absolute, origin+":direct"); err != nil {
		return nil, err
	} else if ok {
		return []quartetSaveSelection{selected}, nil
	}

	patterns := []string{
		filepath.Join(absolute, "drive_c", "users", "*", "AppData", "Local", filepath.FromSlash(quartetSaveSubpath)),
		filepath.Join(absolute, "pfx", "drive_c", "users", "*", "AppData", "Local", filepath.FromSlash(quartetSaveSubpath)),
	}
	if strings.EqualFold(filepath.Base(absolute), "drive_c") {
		patterns = append(patterns, filepath.Join(absolute, "users", "*", "AppData", "Local", filepath.FromSlash(quartetSaveSubpath)))
	}
	if strings.EqualFold(filepath.Base(absolute), "pfx") {
		patterns = append(patterns, filepath.Join(absolute, "drive_c", "users", "*", "AppData", "Local", filepath.FromSlash(quartetSaveSubpath)))
	}

	var out []quartetSaveSelection
	seen := map[string]bool{}
	for _, pattern := range patterns {
		matches, globErr := filepath.Glob(pattern)
		if globErr != nil {
			return nil, globErr
		}
		for _, match := range matches {
			selected, ok, selectErr := saveSelectionFromDirectory(match, origin+":prefix")
			if selectErr != nil {
				return nil, selectErr
			}
			if !ok {
				continue
			}
			key := strings.ToLower(filepath.Clean(selected.Root))
			if seen[key] {
				continue
			}
			seen[key] = true
			out = append(out, selected)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Root < out[j].Root })
	return out, nil
}

func steamappsFromGameRoot(gameRoot string) string {
	absolute, err := filepath.Abs(gameRoot)
	if err != nil {
		return ""
	}
	current := filepath.Clean(absolute)
	for {
		if strings.EqualFold(filepath.Base(current), "common") && strings.EqualFold(filepath.Base(filepath.Dir(current)), "steamapps") {
			return filepath.Dir(current)
		}
		parent := filepath.Dir(current)
		if parent == current {
			return ""
		}
		current = parent
	}
}

func appendUniqueSaveSelection(dst []quartetSaveSelection, seen map[string]bool, candidate quartetSaveSelection) []quartetSaveSelection {
	key := strings.ToLower(filepath.Clean(candidate.Root))
	if seen[key] {
		return dst
	}
	seen[key] = true
	candidate.Files = append([]string(nil), candidate.Files...)
	sort.Strings(candidate.Files)
	return append(dst, candidate)
}

func scanSteamCompatSaves(steamapps, origin string) ([]quartetSaveSelection, error) {
	if strings.TrimSpace(steamapps) == "" {
		return nil, nil
	}
	pattern := filepath.Join(steamapps, "compatdata", "*", "pfx", "drive_c", "users", "*", "AppData", "Local", filepath.FromSlash(quartetSaveSubpath))
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}
	var out []quartetSaveSelection
	for _, match := range matches {
		selected, ok, err := saveSelectionFromDirectory(match, origin)
		if err != nil {
			return nil, err
		}
		if ok {
			out = append(out, selected)
		}
	}
	return out, nil
}

func discoverQuartetSaveSelections(gameRoot string) ([]quartetSaveSelection, error) {
	seen := map[string]bool{}
	var out []quartetSaveSelection

	if local := strings.TrimSpace(os.Getenv("LOCALAPPDATA")); local != "" {
		if selected, ok, err := saveSelectionFromDirectory(filepath.Join(local, filepath.FromSlash(quartetSaveSubpath)), "local-app-data"); err != nil {
			return nil, err
		} else if ok {
			out = appendUniqueSaveSelection(out, seen, selected)
		}
	}

	for _, envName := range []string{"WINEPREFIX", "STEAM_COMPAT_DATA_PATH"} {
		if value := strings.TrimSpace(os.Getenv(envName)); value != "" {
			found, err := prefixSaveSelections(value, strings.ToLower(envName))
			if err != nil {
				return nil, err
			}
			for _, selected := range found {
				out = appendUniqueSaveSelection(out, seen, selected)
			}
		}
	}

	steamRoots := []struct {
		Path   string
		Origin string
	}{}
	if inferred := steamappsFromGameRoot(gameRoot); inferred != "" {
		steamRoots = append(steamRoots, struct {
			Path   string
			Origin string
		}{inferred, "game-steam-library"})
	}
	if home, err := os.UserHomeDir(); err == nil {
		for _, path := range []string{
			filepath.Join(home, ".local", "share", "Steam", "steamapps"),
			filepath.Join(home, ".steam", "steam", "steamapps"),
			filepath.Join(home, ".steam", "root", "steamapps"),
			filepath.Join(home, ".var", "app", "com.valvesoftware.Steam", "data", "Steam", "steamapps"),
			filepath.Join(home, "snap", "steam", "common", ".local", "share", "Steam", "steamapps"),
		} {
			steamRoots = append(steamRoots, struct {
				Path   string
				Origin string
			}{path, "steam-compatdata"})
		}
	}
	seenSteam := map[string]bool{}
	for _, root := range steamRoots {
		absolute, err := filepath.Abs(root.Path)
		if err != nil {
			continue
		}
		key := strings.ToLower(filepath.Clean(absolute))
		if seenSteam[key] {
			continue
		}
		seenSteam[key] = true
		if info, statErr := os.Stat(absolute); statErr != nil || !info.IsDir() {
			continue
		}
		found, err := scanSteamCompatSaves(absolute, root.Origin)
		if err != nil {
			return nil, err
		}
		for _, selected := range found {
			out = appendUniqueSaveSelection(out, seen, selected)
		}
	}

	sort.Slice(out, func(i, j int) bool { return out[i].Root < out[j].Root })
	return out, nil
}

func chooseQuartetSaveSelection(explicit, gameRoot string, prompt bool, in io.Reader, out io.Writer) (quartetSaveSelection, error) {
	if value := strings.Trim(strings.TrimSpace(explicit), `"`); value != "" {
		found, err := prefixSaveSelections(value, "explicit")
		if err != nil {
			return quartetSaveSelection{}, err
		}
		if len(found) == 1 {
			return found[0], nil
		}
		if len(found) == 0 {
			return quartetSaveSelection{}, fmt.Errorf("save path does not contain Quartet .pcsave files and is not a recognizable Wine/Proton prefix: %s", value)
		}
		if !prompt {
			return quartetSaveSelection{}, fmt.Errorf("save path resolves to %d candidate save folders; pass the desired save folder directly", len(found))
		}
		choices := make([]string, 0, len(found)+1)
		for _, selected := range found {
			choices = append(choices, fmt.Sprintf("%s (%d save(s))", selected.Root, len(selected.Files)))
		}
		choices = append(choices, "Cancel")
		index, err := chooseSimpleMenu("Select BLUE REFLECTION Quartet save folder", choices, in, out)
		if err != nil {
			return quartetSaveSelection{}, err
		}
		if index == len(found) {
			return quartetSaveSelection{}, errQuartetSaveAccessCancelled
		}
		return found[index], nil
	}

	found, err := discoverQuartetSaveSelections(gameRoot)
	if err != nil {
		return quartetSaveSelection{}, err
	}
	if !prompt {
		if len(found) == 1 {
			fmt.Fprintf(out, "Detected Quartet save folder: %s (%d save(s))\n", found[0].Root, len(found[0].Files))
			return found[0], nil
		}
		if len(found) == 0 {
			return quartetSaveSelection{}, fmt.Errorf("no Quartet saves detected automatically; pass --save-path with the save folder, one .pcsave file, or a Wine/Proton prefix containing drive_c")
		}
		return quartetSaveSelection{}, fmt.Errorf("detected %d Quartet save folders; pass --save-path with the desired folder or prefix", len(found))
	}

	choices := make([]string, 0, len(found)+2)
	for _, selected := range found {
		choices = append(choices, fmt.Sprintf("%s (%d save(s), %s)", selected.Root, len(selected.Files), selected.Origin))
	}
	choices = append(choices, "Enter / paste save folder / .pcsave / Wine or Proton prefix manually")
	choices = append(choices, "Cancel")
	index, chooseErr := chooseSimpleMenu("BLUE REFLECTION Quartet saves", choices, in, out)
	if chooseErr != nil {
		return quartetSaveSelection{}, chooseErr
	}
	if index < len(found) {
		return found[index], nil
	}
	if index == len(found)+1 {
		return quartetSaveSelection{}, errQuartetSaveAccessCancelled
	}
	return promptQuartetSaveSelection(in, out)
}

func promptQuartetSaveSelection(in io.Reader, out io.Writer) (quartetSaveSelection, error) {
	fmt.Fprintln(out, "Paste any one of:")
	fmt.Fprintln(out, "  - the folder containing Quartet .pcsave files")
	fmt.Fprintln(out, "  - a Wine/Proton prefix folder containing drive_c")
	fmt.Fprintln(out, "  - one specific .pcsave file if you only want to update that save")
	value, err := readPathPrompt(in, out, "Save folder / prefix / .pcsave: ")
	if err != nil {
		return quartetSaveSelection{}, err
	}
	resolved, err := prefixSaveSelections(value, "prompted")
	if err != nil {
		return quartetSaveSelection{}, err
	}
	if len(resolved) == 0 {
		return quartetSaveSelection{}, fmt.Errorf("no Quartet .pcsave files found from %s", value)
	}
	if len(resolved) == 1 {
		return resolved[0], nil
	}
	choices := make([]string, 0, len(resolved)+1)
	for _, selected := range resolved {
		choices = append(choices, fmt.Sprintf("%s (%d save(s))", selected.Root, len(selected.Files)))
	}
	choices = append(choices, "Cancel")
	index, err := chooseSimpleMenu("Select save folder inside prefix", choices, in, out)
	if err != nil {
		return quartetSaveSelection{}, err
	}
	if index == len(resolved) {
		return quartetSaveSelection{}, errQuartetSaveAccessCancelled
	}
	return resolved[index], nil
}

func previewQuartetSaveAccess(selection quartetSaveSelection, dllPath string, includeDressRoom bool) ([]br1rebuild.SaveAccessReport, error) {
	reports := make([]br1rebuild.SaveAccessReport, 0, len(selection.Files))
	for _, path := range selection.Files {
		report, err := br1rebuild.UpdateSaveAccessState(path, dllPath, includeDressRoom, false)
		if err != nil {
			return nil, fmt.Errorf("validate save %s: %w", filepath.Base(path), err)
		}
		if report.RosterCount != 122 {
			return nil, fmt.Errorf("installed B1.dll exposes %d costume records; expected 122 before save access can be updated", report.RosterCount)
		}
		reports = append(reports, report)
	}
	return reports, nil
}

func reportNeedsSaveWrite(report br1rebuild.SaveAccessReport) bool {
	return report.WardrobeBytesChanged > 0 || report.IslandChanged || report.DressRoomChanged
}

func applyQuartetSaveAccess(selection quartetSaveSelection, dllPath string, includeDressRoom bool, out io.Writer) (quartetSaveAccessResult, error) {
	preview, err := previewQuartetSaveAccess(selection, dllPath, includeDressRoom)
	if err != nil {
		return quartetSaveAccessResult{}, err
	}
	result := quartetSaveAccessResult{
		Type: "quartet_save_access_update", Status: "already_current", GameRoot: filepath.Dir(dllPath),
		SaveRoot: selection.Root, SaveOrigin: selection.Origin, SaveCount: len(selection.Files),
	}
	for i, report := range preview {
		// Once a save-access batch needs any change, snapshot and verify every
		// discovered current save in the selected folder. This makes the batch
		// explicit and recoverable for AUTOSAVE plus every GAMEDATA slot instead
		// of leaving "already current" siblings without a matching safety copy.
		applied, applyErr := br1rebuild.UpdateSaveAccessState(selection.Files[i], dllPath, includeDressRoom, true)
		if applyErr != nil {
			return result, fmt.Errorf("update save %s: %w", filepath.Base(selection.Files[i]), applyErr)
		}
		result.Reports = append(result.Reports, applied)
		if reportNeedsSaveWrite(report) {
			result.ChangedSaveCount++
			fmt.Fprintf(out, "Save: %s  updated  costume flags=%d  island=%v  backup=%s\n", filepath.Base(selection.Files[i]), applied.WardrobeBytesChanged, applied.IslandChanged, applied.Backup)
		} else {
			fmt.Fprintf(out, "Save: %s  already current; verified snapshot=%s\n", filepath.Base(selection.Files[i]), applied.Backup)
		}
	}
	if result.ChangedSaveCount > 0 {
		result.Status = "updated"
	}
	return result, nil
}

func confirmQuartetSaveAccess(reports []br1rebuild.SaveAccessReport, selection quartetSaveSelection, includeDressRoom bool, in io.Reader, out io.Writer) (bool, error) {
	changes := 0
	costumeFlags := 0
	islandChanges := 0
	dressRoomChanges := 0
	for _, report := range reports {
		if reportNeedsSaveWrite(report) {
			changes++
		}
		costumeFlags += report.WardrobeBytesChanged
		if report.IslandChanged {
			islandChanges++
		}
		if report.DressRoomChanged {
			dressRoomChanges++
		}
	}
	fmt.Fprintf(out, "\nSave access preview\nFolder: %s\nSaves: %d; saves needing changes: %d\nCostume flag bytes to enable: %d; Island gates to enable: %d\n", selection.Root, len(reports), changes, costumeFlags, islandChanges)
	if includeDressRoom {
		fmt.Fprintf(out, "Converted-save Dressing Room fixes: %d\n", dressRoomChanges)
	}
	if changes == 0 {
		fmt.Fprintln(out, "All selected saves are already current.")
		return false, nil
	}
	fmt.Fprintln(out, "Each changed save receives a timestamped backup beside the original before any write.")
	fmt.Fprint(out, "Update these saves [y/N]: ")
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return false, err
	}
	value := strings.ToLower(strings.TrimSpace(line))
	return value == "y" || value == "yes", nil
}

func commandQuartetSaveAccess(args []string) error {
	flags := flag.NewFlagSet("save-access", flag.ContinueOnError)
	var gameRoot, savePath, output string
	var confirmed, includeDressRoom bool
	flags.StringVar(&gameRoot, "game-dir", "", "BLUE REFLECTION Quartet game folder; auto-detected when omitted")
	flags.StringVar(&savePath, "save-path", "", "save folder, one .pcsave file, or Wine/Proton prefix containing drive_c")
	flags.BoolVar(&confirmed, "yes", false, "apply after validation without an additional confirmation prompt")
	flags.BoolVar(&includeDressRoom, "converted-save-dressroom", false, "also repair the Dressing Room gate for a save converted from BLUE REFLECTION (2017)")
	flags.StringVar(&output, "json", "", "write the save access result to JSON")
	if err := flags.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}

	prompt := stdinIsInteractive()
	if strings.TrimSpace(gameRoot) == "" {
		specs, err := targets.Load()
		if err != nil {
			return err
		}
		items, err := detectWithFallback(specs, nil, prompt, os.Stdin, os.Stdout)
		if err != nil {
			return err
		}
		var quartetRoots []string
		for _, item := range items {
			if item.TargetID == "blue_reflection_quartet" {
				quartetRoots = append(quartetRoots, item.Root)
			}
		}
		if len(quartetRoots) != 1 {
			return fmt.Errorf("save-access needs exactly one BLUE REFLECTION Quartet installation; detected %d; pass --game-dir PATH", len(quartetRoots))
		}
		gameRoot = quartetRoots[0]
	}
	absoluteGame, err := filepath.Abs(strings.Trim(strings.TrimSpace(gameRoot), `"`))
	if err != nil {
		return err
	}
	dllPath := filepath.Join(absoluteGame, "B1.dll")
	if info, err := os.Stat(dllPath); err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("Quartet B1.dll not found under game directory: %s", dllPath)
	}

	selection, err := chooseQuartetSaveSelection(savePath, absoluteGame, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	preview, err := previewQuartetSaveAccess(selection, dllPath, includeDressRoom)
	if err != nil {
		return err
	}
	needsWrite := false
	for _, report := range preview {
		if reportNeedsSaveWrite(report) {
			needsWrite = true
			break
		}
	}
	if !needsWrite {
		result := quartetSaveAccessResult{Type: "quartet_save_access_update", Status: "already_current", GameRoot: absoluteGame, SaveRoot: selection.Root, SaveOrigin: selection.Origin, SaveCount: len(selection.Files), Reports: preview}
		fmt.Fprintf(os.Stdout, "All %d selected save(s) already have the restored costume and Tropical Island access flags.\n", len(selection.Files))
		if output != "" {
			return emit(result, output)
		}
		return nil
	}
	if !confirmed {
		if !prompt {
			return fmt.Errorf("save files need changes; rerun with --yes after reviewing the target save path")
		}
		ok, confirmErr := confirmQuartetSaveAccess(preview, selection, includeDressRoom, os.Stdin, os.Stdout)
		if confirmErr != nil {
			return confirmErr
		}
		if !ok {
			fmt.Fprintln(os.Stdout, "No save files were modified.")
			return nil
		}
	}
	result, err := applyQuartetSaveAccess(selection, dllPath, includeDressRoom, os.Stdout)
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stdout, "Updated %d/%d save(s). Run save-access again after creating a new playthrough/save.\n", result.ChangedSaveCount, result.SaveCount)
	if output != "" {
		return emit(result, output)
	}
	return nil
}
