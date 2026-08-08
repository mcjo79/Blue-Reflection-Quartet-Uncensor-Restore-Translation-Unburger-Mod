package br1rebuild

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
)

const br1SteamAppID = "658260"

var vdfPathLine = regexp.MustCompile(`(?i)^\s*"path"\s+"([^"]+)"`)
var acfInstallDirLine = regexp.MustCompile(`(?i)^\s*"installdir"\s+"([^"]+)"`)

type SourceLocator struct {
	AssetRoot string
	LooseRoot string
	SteamRoot string
	AutoSteam bool
}

type SourceLocation struct {
	Root   string `json:"root"`
	Origin string `json:"origin"`
}

func LocateSourceInstall(locator SourceLocator) (SourceLocation, error) {
	if strings.TrimSpace(locator.AssetRoot) != "" {
		return locateSourceAssetBundle(locator.AssetRoot)
	}
	if strings.TrimSpace(locator.LooseRoot) != "" {
		root, err := normalizeExistingDir(locator.LooseRoot)
		if err != nil {
			return SourceLocation{}, fmt.Errorf("source folder: %w", err)
		}
		if err := validateSourceInstall(root); err != nil {
			return SourceLocation{}, err
		}
		return SourceLocation{Root: root, Origin: "explicit_game_folder"}, nil
	}

	if strings.TrimSpace(locator.SteamRoot) != "" {
		root, origin, err := sourceFromSteamAnchor(locator.SteamRoot)
		if err != nil {
			return SourceLocation{}, err
		}
		return SourceLocation{Root: root, Origin: origin}, nil
	}

	if locator.AutoSteam {
		var failures []string
		for _, anchor := range defaultSteamAnchors() {
			root, origin, err := sourceFromSteamAnchor(anchor)
			if err == nil {
				return SourceLocation{Root: root, Origin: origin}, nil
			}
			failures = append(failures, fmt.Sprintf("%s: %v", anchor, err))
		}
		if len(failures) == 0 {
			return SourceLocation{}, fmt.Errorf("no default Steam locations are available on this platform")
		}
		return SourceLocation{}, fmt.Errorf("BLUE REFLECTION (2017) was not found in default Steam locations")
	}

	return SourceLocation{}, fmt.Errorf("no BLUE REFLECTION (2017) source was supplied; use a game folder, a Steam/library folder, Steam autodetection, or a compatible developer asset bundle")
}

func normalizeExistingDir(raw string) (string, error) {
	path := strings.Trim(strings.TrimSpace(raw), `"`)
	if path == "" {
		return "", fmt.Errorf("empty path")
	}
	if strings.HasPrefix(path, "~"+string(os.PathSeparator)) || path == "~" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		if path == "~" {
			path = home
		} else {
			path = filepath.Join(home, path[2:])
		}
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return "", err
	}
	if !st.IsDir() {
		return "", fmt.Errorf("not a directory: %s", abs)
	}
	return filepath.Clean(abs), nil
}

func sourceFromSteamAnchor(raw string) (string, string, error) {
	anchor, err := normalizeExistingDir(raw)
	if err != nil {
		return "", "", fmt.Errorf("Steam folder: %w", err)
	}
	libraries := discoverSteamLibraries(anchor)
	if len(libraries) == 0 {
		return "", "", fmt.Errorf("no steamapps library found below %s", anchor)
	}
	for _, library := range libraries {
		root, ok := installFromManifest(library, br1SteamAppID)
		if !ok {
			continue
		}
		if err := validateSourceInstall(root); err != nil {
			continue
		}
		return root, "steam_manifest", nil
	}
	return "", "", fmt.Errorf("Steam app %s is not installed in the discovered libraries", br1SteamAppID)
}

func discoverSteamLibraries(anchor string) []string {
	candidates := []string{anchor}
	if filepath.Base(strings.ToLower(anchor)) == "steamapps" {
		candidates = append(candidates, filepath.Dir(anchor))
	}
	if st, err := os.Stat(filepath.Join(anchor, "steamapps")); err == nil && st.IsDir() {
		candidates = append(candidates, anchor)
	}
	if st, err := os.Stat(filepath.Join(anchor, "Steam", "steamapps")); err == nil && st.IsDir() {
		candidates = append(candidates, filepath.Join(anchor, "Steam"))
	}

	seen := map[string]bool{}
	var libraries []string
	add := func(root string) {
		root = filepath.Clean(root)
		if seen[root] {
			return
		}
		if st, err := os.Stat(filepath.Join(root, "steamapps")); err == nil && st.IsDir() {
			seen[root] = true
			libraries = append(libraries, root)
		}
	}
	for _, c := range candidates {
		add(c)
	}

	// Expand only through Valve's library index; the game folder itself is
	// resolved later from its app manifest rather than guessed from a name.
	initial := append([]string(nil), libraries...)
	for _, root := range initial {
		for _, extra := range parseLibraryIndex(filepath.Join(root, "steamapps", "libraryfolders.vdf")) {
			add(extra)
		}
	}
	sort.Strings(libraries)
	return libraries
}

func parseLibraryIndex(path string) []string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	var out []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		m := vdfPathLine.FindStringSubmatch(scanner.Text())
		if m == nil {
			continue
		}
		p := strings.ReplaceAll(m[1], `\\`, `\`)
		if p != "" {
			out = append(out, filepath.Clean(p))
		}
	}
	return out
}

func installFromManifest(library, appID string) (string, bool) {
	path := filepath.Join(library, "steamapps", "appmanifest_"+appID+".acf")
	f, err := os.Open(path)
	if err != nil {
		return "", false
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		m := acfInstallDirLine.FindStringSubmatch(scanner.Text())
		if m == nil {
			continue
		}
		dir := strings.TrimSpace(m[1])
		if dir == "" {
			return "", false
		}
		return filepath.Join(library, "steamapps", "common", filepath.FromSlash(dir)), true
	}
	return "", false
}

func defaultSteamAnchors() []string {
	var out []string
	add := func(p string) {
		if p == "" {
			return
		}
		if st, err := os.Stat(p); err == nil && st.IsDir() {
			out = append(out, p)
		}
	}
	if env := strings.TrimSpace(os.Getenv("STEAM_PATH")); env != "" {
		add(env)
	}
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
	seen := map[string]bool{}
	result := make([]string, 0, len(out))
	for _, p := range out {
		p = filepath.Clean(p)
		if !seen[p] {
			seen[p] = true
			result = append(result, p)
		}
	}
	return result
}

func sourceDataDirectory(root string) (string, error) {
	for _, name := range []string{"DATA", "Data", "data"} {
		candidate := filepath.Join(root, name)
		if st, err := os.Stat(candidate); err == nil && st.IsDir() {
			return candidate, nil
		}
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}
	for _, entry := range entries {
		if entry.IsDir() && strings.EqualFold(entry.Name(), "data") {
			return filepath.Join(root, entry.Name()), nil
		}
	}
	return "", fmt.Errorf("data directory not found")
}

func validateSourceInstall(root string) error {
	dataRoot, err := sourceDataDirectory(root)
	if err != nil {
		return fmt.Errorf("selected source is not a supported BLUE REFLECTION (2017) install: %w", err)
	}
	required := []struct {
		label string
		path  string
	}{
		{"BLUE_REFLECTION.exe", casePath(root, "BLUE_REFLECTION.exe")},
		{filepath.ToSlash(filepath.Join(filepath.Base(dataRoot), "PACK00_02.PAK")), casePath(dataRoot, "PACK00_02.PAK")},
		{filepath.ToSlash(filepath.Join(filepath.Base(dataRoot), "PACK00_03.PAK")), casePath(dataRoot, "PACK00_03.PAK")},
		{filepath.ToSlash(filepath.Join(filepath.Base(dataRoot), "PACK01.PAK")), casePath(dataRoot, "PACK01.PAK")},
	}
	for _, item := range required {
		if st, statErr := os.Stat(item.path); statErr != nil || st.IsDir() {
			return fmt.Errorf("selected source is not a supported BLUE REFLECTION (2017) install: missing %s", item.label)
		}
	}
	return nil
}
