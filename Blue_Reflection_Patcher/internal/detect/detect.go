package detect

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

type RootCandidate struct {
	Path   string
	Source string
}

// Detect identifies installations only from their directory structure and
// required game files. Store metadata, executable hashes, directory names and
// whole-archive hashes are deliberately not part of identification.
func Detect(specs []model.TargetSpec, candidates []RootCandidate) ([]model.Detection, error) {
	ordered, err := normalizeCandidates(candidates)
	if err != nil {
		return nil, err
	}
	found := make([]model.Detection, 0, len(ordered))
	for _, candidate := range ordered {
		matches := make([]model.Detection, 0, 1)
		for _, spec := range specs {
			matched, ok := requiredFilesPresent(candidate.Path, spec.RequiredFiles)
			if !ok {
				continue
			}
			matches = append(matches, model.Detection{
				TargetID:     spec.TargetID,
				DisplayName:  spec.DisplayName,
				Root:         candidate.Path,
				Source:       candidate.Source,
				Confidence:   "structural_files",
				MatchedFiles: matched,
			})
		}
		if len(matches) > 1 {
			ids := make([]string, 0, len(matches))
			for _, item := range matches {
				ids = append(ids, item.TargetID)
			}
			sort.Strings(ids)
			return nil, fmt.Errorf("ambiguous game directory %s matches multiple targets: %s", candidate.Path, strings.Join(ids, ", "))
		}
		if len(matches) == 1 {
			found = append(found, matches[0])
		}
	}
	sort.SliceStable(found, func(i, j int) bool {
		if found[i].Root != found[j].Root {
			return found[i].Root < found[j].Root
		}
		return found[i].TargetID < found[j].TargetID
	})
	return found, nil
}

func normalizeCandidates(candidates []RootCandidate) ([]RootCandidate, error) {
	seen := map[string]bool{}
	result := make([]RootCandidate, 0, len(candidates))
	for _, candidate := range candidates {
		if strings.TrimSpace(candidate.Path) == "" {
			continue
		}
		root, err := normalizeRoot(candidate.Path)
		if err != nil {
			return nil, fmt.Errorf("resolve game directory %q: %w", candidate.Path, err)
		}
		key := filepath.Clean(root)
		if resolved, err := filepath.EvalSymlinks(key); err == nil {
			key = filepath.Clean(resolved)
		}
		if seen[key] {
			continue
		}
		seen[key] = true
		source := strings.TrimSpace(candidate.Source)
		if source == "" {
			source = "explicit_path"
		}
		result = append(result, RootCandidate{Path: root, Source: source})
	}
	return result, nil
}

func normalizeRoot(raw string) (string, error) {
	expanded := expandHome(strings.TrimSpace(raw))
	abs, err := filepath.Abs(expanded)
	if err != nil {
		return "", err
	}
	info, err := os.Stat(abs)
	if err != nil {
		return "", err
	}
	if !info.IsDir() {
		abs = filepath.Dir(abs)
		info, err = os.Stat(abs)
		if err != nil {
			return "", err
		}
	}
	if !info.IsDir() {
		return "", fmt.Errorf("not a directory: %s", abs)
	}
	return filepath.Clean(abs), nil
}

func requiredFilesPresent(root string, required []string) ([]string, bool) {
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return nil, false
	}
	matched := make([]string, 0, len(required))
	for _, relative := range required {
		actual, ok := findCaseInsensitive(root, relative)
		if !ok {
			return nil, false
		}
		fileInfo, err := os.Stat(actual)
		if err != nil || fileInfo.IsDir() {
			return nil, false
		}
		rel, err := filepath.Rel(root, actual)
		if err != nil {
			return nil, false
		}
		matched = append(matched, filepath.ToSlash(rel))
	}
	return matched, true
}

// findCaseInsensitive resolves every path component by exact match first and
// case-insensitive directory lookup second. This keeps detection portable when
// a Windows installation is copied to a case-sensitive filesystem.
func findCaseInsensitive(root, relative string) (string, bool) {
	current := root
	for _, component := range strings.FieldsFunc(filepath.ToSlash(relative), func(r rune) bool { return r == '/' }) {
		if component == "" || component == "." || component == ".." {
			return "", false
		}
		exact := filepath.Join(current, filepath.FromSlash(component))
		if _, err := os.Lstat(exact); err == nil {
			current = exact
			continue
		}
		entries, err := os.ReadDir(current)
		if err != nil {
			return "", false
		}
		matched := ""
		for _, entry := range entries {
			if strings.EqualFold(entry.Name(), component) {
				if matched != "" && matched != entry.Name() {
					return "", false
				}
				matched = entry.Name()
			}
		}
		if matched == "" {
			return "", false
		}
		current = filepath.Join(current, matched)
	}
	return current, true
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
