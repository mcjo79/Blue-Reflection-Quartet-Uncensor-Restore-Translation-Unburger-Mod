package detect

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

var (
	quotedPair = regexp.MustCompile(`"([^"]+)"\s+"([^"]*)"`)
	oldLibrary = regexp.MustCompile(`^\s*"[0-9]+"\s+"([^"]+)"`)
)

func Detect(specs []model.TargetSpec, manualRoots []string) ([]model.Detection, error) {
	found := map[string]model.Detection{}

	for _, raw := range manualRoots {
		root, err := filepath.Abs(expandHome(raw))
		if err != nil {
			return nil, fmt.Errorf("resolve manual root %q: %w", raw, err)
		}
		for _, spec := range specs {
			if markersPresent(root, spec.Markers) {
				key := spec.TargetID + "\x00" + filepath.Clean(root)
				found[key] = model.Detection{
					TargetID: spec.TargetID, DisplayName: spec.DisplayName,
					Root: root, Source: "manual_root", Confidence: "markers_only",
					SteamAppID: spec.SteamAppID,
				}
			}
		}
	}

	for _, steamRoot := range steamRoots() {
		libraries := steamLibraries(steamRoot)
		for _, library := range libraries {
			for _, spec := range specs {
				manifest := filepath.Join(library, "steamapps", fmt.Sprintf("appmanifest_%d.acf", spec.SteamAppID))
				installDir, buildID, ok := parseAppManifest(manifest)
				if !ok {
					continue
				}
				root := filepath.Join(library, "steamapps", "common", installDir)
				if !markersPresent(root, spec.Markers) {
					continue
				}
				abs, err := filepath.Abs(root)
				if err != nil {
					continue
				}
				key := spec.TargetID + "\x00" + filepath.Clean(abs)
				found[key] = model.Detection{
					TargetID: spec.TargetID, DisplayName: spec.DisplayName,
					Root: abs, Source: "steam_manifest", Confidence: "steam_manifest_and_markers",
					SteamAppID: spec.SteamAppID, BuildID: buildID,
				}
			}
		}
	}

	result := make([]model.Detection, 0, len(found))
	for _, item := range found {
		result = append(result, item)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].TargetID != result[j].TargetID {
			return result[i].TargetID < result[j].TargetID
		}
		return result[i].Root < result[j].Root
	})
	return result, nil
}

func markersPresent(root string, markers []string) bool {
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return false
	}
	for _, marker := range markers {
		if info, err := os.Stat(filepath.Join(root, filepath.FromSlash(marker))); err != nil || info.IsDir() {
			return false
		}
	}
	return true
}

func steamRoots() []string {
	var candidates []string
	if env := os.Getenv("STEAM_DIR"); env != "" {
		candidates = append(candidates, env)
	}
	home, _ := os.UserHomeDir()
	if runtime.GOOS == "windows" {
		if path := steamRootFromRegistry(); path != "" {
			candidates = append(candidates, path)
		}
		for _, envName := range []string{"ProgramFiles(x86)", "ProgramFiles"} {
			if base := os.Getenv(envName); base != "" {
				candidates = append(candidates, filepath.Join(base, "Steam"))
			}
		}
	} else {
		candidates = append(candidates,
			filepath.Join(home, ".steam", "steam"),
			filepath.Join(home, ".local", "share", "Steam"),
			filepath.Join(home, ".var", "app", "com.valvesoftware.Steam", "data", "Steam"),
		)
	}
	return existingUniqueDirs(candidates)
}

func steamRootFromRegistry() string {
	cmd := exec.Command("reg.exe", "query", `HKCU\Software\Valve\Steam`, "/v", "SteamPath")
	output, err := cmd.Output()
	if err != nil {
		return ""
	}
	fields := strings.Fields(string(output))
	for index, field := range fields {
		if strings.EqualFold(field, "SteamPath") && index+2 < len(fields) {
			return strings.Join(fields[index+2:], " ")
		}
	}
	return ""
}

func steamLibraries(root string) []string {
	libraries := []string{root}
	path := filepath.Join(root, "steamapps", "libraryfolders.vdf")
	file, err := os.Open(path)
	if err != nil {
		return existingUniqueDirs(libraries)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if matches := quotedPair.FindStringSubmatch(line); len(matches) == 3 && strings.EqualFold(matches[1], "path") {
			libraries = append(libraries, decodeVDFPath(matches[2]))
			continue
		}
		if matches := oldLibrary.FindStringSubmatch(line); len(matches) == 2 {
			libraries = append(libraries, decodeVDFPath(matches[1]))
		}
	}
	return existingUniqueDirs(libraries)
}

func parseAppManifest(path string) (installDir, buildID string, ok bool) {
	file, err := os.Open(path)
	if err != nil {
		return "", "", false
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		matches := quotedPair.FindStringSubmatch(scanner.Text())
		if len(matches) != 3 {
			continue
		}
		switch strings.ToLower(matches[1]) {
		case "installdir":
			installDir = matches[2]
		case "buildid":
			buildID = matches[2]
		}
	}
	return installDir, buildID, installDir != ""
}

func decodeVDFPath(path string) string {
	path = strings.ReplaceAll(path, `\\`, `\`)
	return expandHome(path)
}

func expandHome(path string) string {
	if path == "~" || strings.HasPrefix(path, "~/") || strings.HasPrefix(path, `~\`) {
		home, _ := os.UserHomeDir()
		if path == "~" {
			return home
		}
		return filepath.Join(home, path[2:])
	}
	return path
}

func existingUniqueDirs(paths []string) []string {
	seen := map[string]bool{}
	var result []string
	for _, path := range paths {
		if path == "" {
			continue
		}
		abs, err := filepath.Abs(expandHome(path))
		if err != nil {
			continue
		}
		abs = filepath.Clean(abs)
		if seen[abs] {
			continue
		}
		if info, err := os.Stat(abs); err != nil || !info.IsDir() {
			continue
		}
		seen[abs] = true
		result = append(result, abs)
	}
	sort.Strings(result)
	return result
}
