package gamepath

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Resolve returns a safe game-root path for a relative artifact path.
// Existing components are matched case-insensitively so Windows-authored
// layouts remain usable on case-sensitive Linux filesystems. Ambiguous
// case-folded matches are rejected. Missing suffixes are returned using the
// requested spelling, which keeps add operations possible without weakening
// traversal or symlink checks.
func Resolve(root, relative string) (string, bool, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return "", false, fmt.Errorf("resolve game root: %w", err)
	}
	clean := filepath.Clean(filepath.FromSlash(relative))
	if filepath.IsAbs(clean) || clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", false, fmt.Errorf("unsafe game-relative path: %q", relative)
	}

	info, err := os.Lstat(absolute)
	if err != nil {
		return "", false, fmt.Errorf("inspect game root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", false, fmt.Errorf("game root is not a real directory: %s", absolute)
	}

	current := absolute
	parts := strings.Split(clean, string(filepath.Separator))
	for index, part := range parts {
		entries, readErr := os.ReadDir(current)
		if errors.Is(readErr, os.ErrNotExist) {
			return filepath.Join(current, filepath.Join(parts[index:]...)), false, nil
		}
		if readErr != nil {
			return "", false, fmt.Errorf("read game path component %s: %w", current, readErr)
		}

		matches := make([]string, 0, 1)
		for _, entry := range entries {
			if strings.EqualFold(entry.Name(), part) {
				matches = append(matches, entry.Name())
			}
		}
		if len(matches) > 1 {
			return "", false, fmt.Errorf("ambiguous case-insensitive game path under %s: %s", current, part)
		}
		if len(matches) == 0 {
			return filepath.Join(current, filepath.Join(parts[index:]...)), false, nil
		}

		current = filepath.Join(current, matches[0])
		componentInfo, statErr := os.Lstat(current)
		if statErr != nil {
			return "", false, fmt.Errorf("inspect game path component %s: %w", current, statErr)
		}
		if componentInfo.Mode()&os.ModeSymlink != 0 {
			return "", false, fmt.Errorf("game path component is a symlink: %s", current)
		}
		if index < len(parts)-1 && !componentInfo.IsDir() {
			return "", false, fmt.Errorf("game path parent is not a directory: %s", current)
		}
	}
	return current, true, nil
}
