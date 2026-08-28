package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/detect"
	"local/blue-reflection-patcher/internal/model"
)

var (
	steamLibraryPathLine       = regexp.MustCompile(`(?i)^\s*"path"\s+"([^"]+)"`)
	steamLegacyLibraryPathLine = regexp.MustCompile(`^\s*"[0-9]+"\s+"([^"]+)"`)
	steamDetectionAnchors      = defaultSteamDetectionAnchors
)

func defaultDetectionCandidates(explicit []string) ([]detect.RootCandidate, error) {
	if len(explicit) > 0 {
		candidates := make([]detect.RootCandidate, 0, len(explicit))
		for _, root := range explicit {
			candidates = append(candidates, detect.RootCandidate{Path: root, Source: "explicit_path"})
		}
		return candidates, nil
	}
	cwd, err := os.Getwd()
	if err != nil {
		return nil, fmt.Errorf("resolve current directory: %w", err)
	}
	candidates := []detect.RootCandidate{{Path: cwd, Source: "current_directory"}}
	if executable, err := os.Executable(); err == nil {
		if releaseRoot, ok := releaseRootCandidateFromExecutable(executable); ok {
			candidates = append(candidates, detect.RootCandidate{Path: releaseRoot, Source: "release_directory"})
		}
		candidates = append(candidates, detect.RootCandidate{
			Path: filepath.Dir(executable), Source: "executable_directory",
		})
	}
	return candidates, nil
}

func releaseRootCandidateFromExecutable(executable string) (string, bool) {
	dir := filepath.Dir(filepath.Clean(executable))
	binDir := filepath.Dir(dir)
	if !strings.EqualFold(filepath.Base(binDir), "bin") {
		return "", false
	}
	arch := strings.ToLower(filepath.Base(dir))
	if arch != "windows-amd64" && arch != "linux-amd64" {
		return "", false
	}
	root := filepath.Dir(binDir)
	if root == "" || root == "." || root == binDir {
		return "", false
	}
	return filepath.Clean(root), true
}

// detectWithFallback deliberately keeps source-asset discovery separate from
// game discovery. Steam libraries are searched only for supported game roots;
// .unburger-assets remains resolved from the patcher/release directory by the
// legacy-content source flow.
func detectWithFallback(
	specs []model.TargetSpec,
	explicit []string,
	prompt bool,
	in io.Reader,
	out io.Writer,
) ([]model.Detection, error) {
	candidates, err := defaultDetectionCandidates(explicit)
	if err != nil {
		return nil, err
	}
	items, err := detect.Detect(specs, candidates)
	if err != nil {
		return nil, err
	}
	if len(items) > 0 {
		return items, nil
	}

	// An explicit --game-dir is authoritative. If it is not a supported game,
	// do not silently switch to a different Steam installation.
	if len(explicit) == 0 {
		remembered := rememberedInstallationCandidates()
		if len(remembered) > 0 {
			items, err = detect.Detect(specs, remembered)
			if err != nil {
				return nil, err
			}
			if len(items) > 0 {
				fmt.Fprintln(out, "No supported game was detected beside the patcher; using a previously managed installation.")
				return items, nil
			}
		}

		fmt.Fprintln(out, "No supported game was detected beside the patcher. Searching default Steam libraries...")
		steamCandidates := steamGameCandidates(steamDetectionAnchors())
		if len(steamCandidates) > 0 {
			items, err = detect.Detect(specs, steamCandidates)
			if err != nil {
				return nil, err
			}
			if len(items) > 0 {
				return items, nil
			}
		}
	}

	if !prompt {
		return nil, nil
	}

	fmt.Fprintln(out, "No supported Blue Reflection installation was detected automatically.")
	fmt.Fprint(out, "Enter the game directory path (leave empty to cancel): ")
	reader := bufio.NewReader(in)
	line, err := reader.ReadString('\n')
	if err != nil && line == "" {
		return nil, fmt.Errorf("read game directory path: %w", err)
	}
	path := strings.TrimSpace(line)
	path = strings.Trim(path, `"`)
	if path == "" {
		return nil, fmt.Errorf("no game directory was provided")
	}
	items, err = detect.Detect(specs, []detect.RootCandidate{{Path: path, Source: "prompted_path"}})
	if err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return nil, fmt.Errorf("the selected directory does not match a supported Blue Reflection installation: %s", path)
	}
	return items, nil
}

func rememberedInstallationCandidates() []detect.RootCandidate {
	base, err := stateRoot()
	if err != nil {
		return nil
	}
	root := filepath.Join(base, "unburger-patcher", "blue-reflection", "installations")
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil
	}
	type rememberedState struct {
		Status   string `json:"status"`
		TargetID string `json:"target_id"`
		GameRoot string `json:"game_root"`
	}
	type journalState struct {
		Status     string            `json:"status"`
		GameRoot   string            `json:"game_root"`
		UpdatedUTC time.Time         `json:"updated_utc"`
		Metadata   map[string]string `json:"metadata"`
	}
	type candidate struct {
		root     string
		source   string
		priority int
		updated  time.Time
	}
	var candidates []candidate
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		installationDir := filepath.Join(root, entry.Name())
		activeAdded := false
		if data, readErr := os.ReadFile(filepath.Join(installationDir, "active_state.json")); readErr == nil {
			var state rememberedState
			if json.Unmarshal(data, &state) == nil && state.Status == "active" && strings.TrimSpace(state.GameRoot) != "" {
				path := filepath.Clean(state.GameRoot)
				if info, statErr := os.Stat(path); statErr == nil && info.IsDir() {
					candidates = append(candidates, candidate{root: path, source: "managed_state", priority: 0})
					activeAdded = true
				}
			}
		}
		if activeAdded {
			continue
		}

		// A rolled-back/discarded journal is useful installation history even
		// though no active_state.json exists. This is exactly the state of a clean
		// installation after rollback. Orphan committed journals are deliberately
		// NOT remembered: selecting one implicitly is unsafe and was the cause of
		// the old Linux /Gry root winning over the newer VM root.
		transactionsDir := filepath.Join(installationDir, "transactions")
		txEntries, readErr := os.ReadDir(transactionsDir)
		if readErr != nil {
			continue
		}
		var newest *journalState
		for _, tx := range txEntries {
			if !tx.IsDir() {
				continue
			}
			data, readErr := os.ReadFile(filepath.Join(transactionsDir, tx.Name(), "journal.json"))
			if readErr != nil {
				continue
			}
			var journal journalState
			if json.Unmarshal(data, &journal) != nil {
				continue
			}
			if journal.Status != "rolled_back" && journal.Status != "discarded" {
				continue
			}
			if strings.TrimSpace(journal.GameRoot) == "" {
				continue
			}
			copyJournal := journal
			if newest == nil || copyJournal.UpdatedUTC.After(newest.UpdatedUTC) {
				newest = &copyJournal
			}
		}
		if newest != nil {
			path := filepath.Clean(newest.GameRoot)
			if info, statErr := os.Stat(path); statErr == nil && info.IsDir() {
				candidates = append(candidates, candidate{root: path, source: "managed_history", priority: 1, updated: newest.UpdatedUTC})
			}
		}
	}

	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].priority != candidates[j].priority {
			return candidates[i].priority < candidates[j].priority
		}
		if !candidates[i].updated.Equal(candidates[j].updated) {
			return candidates[i].updated.After(candidates[j].updated)
		}
		return candidates[i].root < candidates[j].root
	})
	seen := map[string]bool{}
	result := make([]detect.RootCandidate, 0, len(candidates))
	for _, item := range candidates {
		key := detectionPathKey(item.root)
		if seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, detect.RootCandidate{Path: item.root, Source: item.source})
	}
	return result
}

func defaultSteamDetectionAnchors() []string {
	seen := map[string]bool{}
	var result []string
	add := func(path string) {
		path = strings.TrimSpace(path)
		if path == "" {
			return
		}
		path = filepath.Clean(path)
		key := detectionPathKey(path)
		if seen[key] {
			return
		}
		if info, err := os.Stat(path); err != nil || !info.IsDir() {
			return
		}
		seen[key] = true
		result = append(result, path)
	}
	add(os.Getenv("STEAM_PATH"))
	add(os.Getenv("STEAM_COMPAT_CLIENT_INSTALL_PATH"))
	home, _ := os.UserHomeDir()
	switch runtime.GOOS {
	case "windows":
		if p := os.Getenv("ProgramFiles(x86)"); p != "" {
			add(filepath.Join(p, "Steam"))
		}
		if p := os.Getenv("ProgramFiles"); p != "" {
			add(filepath.Join(p, "Steam"))
		}
	case "linux":
		add(filepath.Join(home, ".local", "share", "Steam"))
		add(filepath.Join(home, ".steam", "steam"))
		add(filepath.Join(home, ".steam", "root"))
		add(filepath.Join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"))
	}
	return result
}

func steamGameCandidates(anchors []string) []detect.RootCandidate {
	libraries := discoverSteamLibraryRoots(anchors)
	seen := map[string]bool{}
	var result []detect.RootCandidate
	for _, library := range libraries {
		common := filepath.Join(library, "steamapps", "common")
		entries, err := os.ReadDir(common)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			if !entry.IsDir() {
				continue
			}
			path := filepath.Join(common, entry.Name())
			key := detectionPathKey(path)
			if seen[key] {
				continue
			}
			seen[key] = true
			result = append(result, detect.RootCandidate{Path: path, Source: "steam_library"})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Path < result[j].Path })
	return result
}

func discoverSteamLibraryRoots(anchors []string) []string {
	seen := map[string]bool{}
	var libraries []string
	queue := append([]string(nil), anchors...)
	addLibrary := func(path string) bool {
		path = filepath.Clean(path)
		if filepath.Base(strings.ToLower(path)) == "steamapps" {
			path = filepath.Dir(path)
		}
		if info, err := os.Stat(filepath.Join(path, "steamapps")); err != nil || !info.IsDir() {
			// Some callers may point at a parent containing Steam/steamapps.
			steamChild := filepath.Join(path, "Steam")
			if childInfo, childErr := os.Stat(filepath.Join(steamChild, "steamapps")); childErr != nil || !childInfo.IsDir() {
				return false
			}
			path = steamChild
		}
		key := detectionPathKey(path)
		if seen[key] {
			return false
		}
		seen[key] = true
		libraries = append(libraries, path)
		return true
	}

	for len(queue) > 0 {
		anchor := queue[0]
		queue = queue[1:]
		if !addLibrary(anchor) {
			continue
		}
		library := libraries[len(libraries)-1]
		for _, extra := range parseSteamLibraryIndex(filepath.Join(library, "steamapps", "libraryfolders.vdf")) {
			if detectionPathKey(extra) != detectionPathKey(library) {
				queue = append(queue, extra)
			}
		}
	}
	sort.Strings(libraries)
	return libraries
}

func parseSteamLibraryIndex(path string) []string {
	file, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer file.Close()
	seen := map[string]bool{}
	var result []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		match := steamLibraryPathLine.FindStringSubmatch(line)
		if match == nil {
			match = steamLegacyLibraryPathLine.FindStringSubmatch(line)
		}
		if match == nil {
			continue
		}
		value := strings.TrimSpace(match[1])
		value = strings.ReplaceAll(value, `\\`, `\`)
		if value == "" {
			continue
		}
		value = filepath.Clean(value)
		key := detectionPathKey(value)
		if seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, value)
	}
	return result
}

func detectionPathKey(path string) string {
	path = filepath.Clean(path)
	if runtime.GOOS == "windows" {
		return strings.ToLower(path)
	}
	return path
}

func chooseDetectedInstallation(specs []model.TargetSpec, items []model.Detection, in io.Reader, out io.Writer) (model.Detection, error) {
	if len(items) == 0 {
		return model.Detection{}, fmt.Errorf("no detected installation to choose")
	}
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		index, err := chooseDetectedInstallationTUI(items, terminalIn, terminalOut)
		if err != nil {
			return model.Detection{}, err
		}
		if index < len(items) {
			return items[index], nil
		}
		if index == len(items)+1 {
			return model.Detection{}, fmt.Errorf("installation selection cancelled")
		}
		return promptForSupportedGameDirectory(specs, in, out)
	}

	fmt.Fprintln(out, "\nSupported installations detected:")
	for index, item := range items {
		fmt.Fprintf(out, "  %d) %s\n     %s\n", index+1, item.DisplayName, item.Root)
	}
	manualIndex := len(items) + 1
	cancelIndex := len(items) + 2
	fmt.Fprintf(out, "  %d) Enter / paste game folder manually\n", manualIndex)
	fmt.Fprintf(out, "  %d) Cancel\n", cancelIndex)
	fmt.Fprintf(out, "Choose 1-%d: ", cancelIndex)
	reader := bufio.NewReader(in)
	line, err := reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return model.Detection{}, err
	}
	var selected int
	if _, err := fmt.Sscanf(strings.TrimSpace(line), "%d", &selected); err != nil || selected < 1 || selected > cancelIndex {
		return model.Detection{}, fmt.Errorf("invalid installation selection")
	}
	if selected <= len(items) {
		return items[selected-1], nil
	}
	if selected == cancelIndex {
		return model.Detection{}, fmt.Errorf("installation selection cancelled")
	}
	fmt.Fprint(out, "Game folder: ")
	line, err = reader.ReadString('\n')
	if err != nil && err != io.EOF {
		return model.Detection{}, err
	}
	return detectPromptedGameDirectory(specs, line)
}

func promptForSupportedGameDirectory(specs []model.TargetSpec, in io.Reader, out io.Writer) (model.Detection, error) {
	value, err := readPathPrompt(in, out, "Game folder: ")
	if err != nil {
		return model.Detection{}, err
	}
	return detectPromptedGameDirectory(specs, value)
}

func detectPromptedGameDirectory(specs []model.TargetSpec, value string) (model.Detection, error) {
	path := strings.Trim(strings.TrimSpace(value), `"`)
	if path == "" {
		return model.Detection{}, fmt.Errorf("game directory path is empty")
	}
	items, err := detect.Detect(specs, []detect.RootCandidate{{Path: path, Source: "prompted_path"}})
	if err != nil {
		return model.Detection{}, err
	}
	if len(items) == 0 {
		return model.Detection{}, fmt.Errorf("the selected directory does not match a supported Blue Reflection installation: %s", path)
	}
	if len(items) != 1 {
		return model.Detection{}, fmt.Errorf("the selected directory resolves to %d supported installations; select one game folder directly", len(items))
	}
	return items[0], nil
}

func chooseDetectedInstallationTUI(items []model.Detection, in *os.File, out *os.File) (int, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return 0, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)
	reader := bufio.NewReader(in)
	cursor := 0
	cancelIndex := len(items) + 1
	fmt.Fprint(out, ansiHideCur)
	for {
		fmt.Fprint(out, ansiClear)
		renderTUIFrameTop(out, "GAME SELECTION")
		renderTUIFrameRow(out, "%sChoose the installation to manage.%s", ansiBold, ansiReset)
		renderTUIFrameRow(out, "%sControls%s  ↑/↓ choose · Enter selects · Q cancels", ansiGray, ansiReset)
		renderTUIFrameBlank(out)
		for index, item := range items {
			pointer := "  "
			style := ""
			if cursor == index {
				pointer = "› "
				style = ansiYellow + ansiBold
			}
			renderTUIFrameRow(out, "%s%s%s%s%s%s", style, pointer, ansiReset, ansiBold, item.DisplayName, ansiReset)
			renderTUIFrameRow(out, "    %s%s%s", ansiDim, item.Root, ansiReset)
			renderTUIFrameRow(out, "    %ssource: %s%s", ansiGray, item.Source, ansiReset)
			renderTUIFrameBlank(out)
		}
		for index, label := range []string{"Enter / paste game folder manually", "Cancel"} {
			choiceIndex := len(items) + index
			pointer := "  "
			style := ""
			if cursor == choiceIndex {
				pointer = "› "
				style = ansiYellow + ansiBold
			}
			renderTUIFrameRow(out, "%s%s%s%s%s%s", style, pointer, ansiReset, ansiBold, label, ansiReset)
		}
		renderTUIFrameBottom(out)
		key, err := readMenuKey(reader)
		if err != nil {
			return 0, err
		}
		switch key {
		case keyUp:
			cursor = (cursor + cancelIndex) % (cancelIndex + 1)
		case keyDown:
			cursor = (cursor + 1) % (cancelIndex + 1)
		case keyEnter, keyToggle:
			fmt.Fprint(out, ansiClear)
			return cursor, nil
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return cancelIndex, nil
		}
	}
}

func stdinIsInteractive() bool {
	info, err := os.Stdin.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

func printHumanDetections(out io.Writer, items []model.Detection) {
	for index, item := range items {
		if index > 0 {
			fmt.Fprintln(out)
		}
		fmt.Fprintf(out, "Detected: %s\n", item.DisplayName)
		fmt.Fprintf(out, "Game directory: %s\n", item.Root)
		fmt.Fprintf(out, "Detection source: %s\n", item.Source)
		fmt.Fprintln(out, "Identification: structural game files (store-independent)")
	}
}
