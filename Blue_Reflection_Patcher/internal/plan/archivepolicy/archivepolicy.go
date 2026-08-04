package archivepolicy

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const analyticalArchiveSuffix = ".pak_"

// AnalyticalArchive describes a preserved read-only sibling such as PACK00_02.PAK_.
// These files are intentionally visible to audits but are never valid production
// transaction or baseline targets.
type AnalyticalArchive struct {
	RelativePath           string `json:"relative_path"`
	Bytes                  int64  `json:"bytes"`
	Classification         string `json:"classification"`
	ProductionRelativePath string `json:"production_relative_path"`
	ProductionExists       bool   `json:"production_exists"`
}

func IsAnalyticalArchivePath(path string) bool {
	base := strings.ToLower(filepath.Base(filepath.FromSlash(strings.TrimSpace(path))))
	return strings.HasSuffix(base, analyticalArchiveSuffix)
}

func RejectAnalyticalArchivePath(path, context string) error {
	if IsAnalyticalArchivePath(path) {
		return fmt.Errorf("%s must not target preserved analytical archive %q; files ending in .PAK_ are read-only audit inputs", context, path)
	}
	return nil
}

// FindAnalyticalArchives scans the game tree without following symlinks and
// reports files ending exactly in .PAK_. It does not hash them, so status remains
// practical even when a preserved archive is several gigabytes large.
func FindAnalyticalArchives(gameRoot string) ([]AnalyticalArchive, error) {
	absolute, err := filepath.Abs(gameRoot)
	if err != nil {
		return nil, fmt.Errorf("resolve game root: %w", err)
	}
	rootInfo, err := os.Lstat(absolute)
	if err != nil {
		return nil, fmt.Errorf("inspect game root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return nil, fmt.Errorf("game root is not a real directory: %s", absolute)
	}

	var result []AnalyticalArchive
	err = filepath.WalkDir(absolute, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == absolute {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if entry.IsDir() || !info.Mode().IsRegular() || !IsAnalyticalArchivePath(entry.Name()) {
			return nil
		}
		relative, err := filepath.Rel(absolute, path)
		if err != nil {
			return err
		}
		productionPath := strings.TrimSuffix(path, "_")
		productionExists := false
		if productionInfo, statErr := os.Lstat(productionPath); statErr == nil {
			productionExists = productionInfo.Mode()&os.ModeSymlink == 0 && productionInfo.Mode().IsRegular()
		} else if !os.IsNotExist(statErr) {
			return statErr
		}
		// Analytical archives may be kept under DATA/legacy while their
		// production counterparts remain directly under DATA. Prefer the
		// same-directory sibling, but resolve this documented layout when the
		// local sibling is absent.
		if !productionExists && strings.EqualFold(filepath.Base(filepath.Dir(path)), "legacy") {
			parentCandidate := filepath.Join(filepath.Dir(filepath.Dir(path)), strings.TrimSuffix(filepath.Base(path), "_"))
			if productionInfo, statErr := os.Lstat(parentCandidate); statErr == nil {
				if productionInfo.Mode()&os.ModeSymlink == 0 && productionInfo.Mode().IsRegular() {
					productionPath = parentCandidate
					productionExists = true
				}
			} else if !os.IsNotExist(statErr) {
				return statErr
			}
		}
		productionRelative, err := filepath.Rel(absolute, productionPath)
		if err != nil {
			return err
		}
		result = append(result, AnalyticalArchive{
			RelativePath:           filepath.ToSlash(relative),
			Bytes:                  info.Size(),
			Classification:         "ignored_analytical_archive",
			ProductionRelativePath: filepath.ToSlash(productionRelative),
			ProductionExists:       productionExists,
		})
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("scan analytical archives: %w", err)
	}
	sort.Slice(result, func(i, j int) bool {
		return strings.ToLower(result[i].RelativePath) < strings.ToLower(result[j].RelativePath)
	})
	return result, nil
}
