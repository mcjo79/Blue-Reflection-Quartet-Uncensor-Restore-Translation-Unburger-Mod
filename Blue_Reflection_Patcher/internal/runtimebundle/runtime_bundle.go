package runtimebundle

import (
	"archive/zip"
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const requiredRecordPath = "content/translation/records.v1.json"

type releaseManifest struct {
	Type          string `json:"type"`
	FormatVersion int    `json:"format_version"`
	CoreVersion   string `json:"core_version"`
}

// ResolveProjectRoot keeps normal repository roots untouched. For a public
// release directory containing one .unburger payload, it verifies and
// materializes that payload into a content-addressed user cache and returns
// the verified materialized root.
func ResolveProjectRoot(root string) (string, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return "", nil
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return "", err
	}
	if isRegular(filepath.Join(abs, requiredRecordPath)) || isRegular(filepath.Join(abs, "workstreams", "translation", "VERSION")) {
		return abs, nil
	}
	bundles, err := filepath.Glob(filepath.Join(abs, "*.unburger"))
	if err != nil {
		return "", err
	}
	sort.Strings(bundles)
	if len(bundles) == 0 {
		return abs, nil
	}
	if len(bundles) != 1 {
		return "", fmt.Errorf("release root contains %d .unburger payloads; expected exactly one", len(bundles))
	}
	return materialize(bundles[0])
}

func materialize(bundlePath string) (string, error) {
	bundleHash, err := sha256File(bundlePath)
	if err != nil {
		return "", err
	}
	if err := validateOptionalSidecar(bundlePath, bundleHash); err != nil {
		return "", err
	}
	cacheBase, err := os.UserCacheDir()
	if err != nil || strings.TrimSpace(cacheBase) == "" {
		cacheBase = os.TempDir()
	}
	cacheRoot := filepath.Join(cacheBase, "unburger-patcher", "runtime-bundles", bundleHash)
	if validateMaterialized(cacheRoot) == nil {
		return cacheRoot, nil
	}
	if err := os.MkdirAll(filepath.Dir(cacheRoot), 0o755); err != nil {
		return "", err
	}
	tmpRoot, err := os.MkdirTemp(filepath.Dir(cacheRoot), ".extract-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(tmpRoot)
	if err := extractZip(bundlePath, tmpRoot); err != nil {
		return "", err
	}
	if err := validateMaterialized(tmpRoot); err != nil {
		return "", err
	}
	_ = os.RemoveAll(cacheRoot)
	if err := os.Rename(tmpRoot, cacheRoot); err != nil {
		return "", err
	}
	return cacheRoot, nil
}

func extractZip(bundlePath, dst string) error {
	zr, err := zip.OpenReader(bundlePath)
	if err != nil {
		return fmt.Errorf("open .unburger payload: %w", err)
	}
	defer zr.Close()
	for _, item := range zr.File {
		name := filepath.FromSlash(item.Name)
		if item.Name == "" || strings.HasPrefix(item.Name, "/") || filepath.IsAbs(name) {
			return fmt.Errorf("unsafe .unburger entry: %q", item.Name)
		}
		clean := filepath.Clean(name)
		if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
			return fmt.Errorf("unsafe .unburger entry: %q", item.Name)
		}
		target := filepath.Join(dst, clean)
		if rel, err := filepath.Rel(dst, target); err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fmt.Errorf("unsafe .unburger entry: %q", item.Name)
		}
		if item.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		r, err := item.Open()
		if err != nil {
			return err
		}
		mode := item.Mode().Perm()
		if mode == 0 {
			mode = 0o644
		}
		out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
		if err != nil {
			r.Close()
			return err
		}
		_, copyErr := io.Copy(out, r)
		closeErr := out.Close()
		r.Close()
		if copyErr != nil {
			return copyErr
		}
		if closeErr != nil {
			return closeErr
		}
	}
	return nil
}

func validateMaterialized(root string) error {
	if !isRegular(filepath.Join(root, requiredRecordPath)) {
		return fmt.Errorf("runtime bundle is missing %s", requiredRecordPath)
	}
	manifestData, err := os.ReadFile(filepath.Join(root, "RELEASE_MANIFEST.json"))
	if err != nil {
		return fmt.Errorf("read runtime bundle manifest: %w", err)
	}
	var manifest releaseManifest
	if err := json.Unmarshal(manifestData, &manifest); err != nil {
		return fmt.Errorf("parse runtime bundle manifest: %w", err)
	}
	if manifest.Type != "unburger_release_manifest" || manifest.FormatVersion < 2 || strings.TrimSpace(manifest.CoreVersion) == "" {
		return fmt.Errorf("unsupported runtime bundle manifest")
	}
	expected, err := readSums(filepath.Join(root, "SHA256SUMS"))
	if err != nil {
		return err
	}
	if len(expected) == 0 {
		return fmt.Errorf("runtime bundle SHA256SUMS is empty")
	}
	for rel, want := range expected {
		clean := filepath.Clean(filepath.FromSlash(strings.TrimPrefix(rel, "./")))
		if clean == "." || clean == ".." || filepath.IsAbs(clean) || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
			return fmt.Errorf("unsafe SHA256SUMS path: %q", rel)
		}
		got, err := sha256File(filepath.Join(root, clean))
		if err != nil {
			return fmt.Errorf("verify %s: %w", rel, err)
		}
		if !strings.EqualFold(got, want) {
			return fmt.Errorf("runtime bundle checksum mismatch for %s", rel)
		}
	}
	return nil
}

func readSums(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("read runtime bundle SHA256SUMS: %w", err)
	}
	defer f.Close()
	result := make(map[string]string)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 2 || len(parts[0]) != 64 {
			return nil, fmt.Errorf("invalid runtime bundle SHA256SUMS line")
		}
		if _, err := hex.DecodeString(parts[0]); err != nil {
			return nil, fmt.Errorf("invalid runtime bundle SHA256SUMS hash")
		}
		rel := strings.TrimPrefix(strings.Join(parts[1:], " "), "*")
		result[rel] = strings.ToLower(parts[0])
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

func validateOptionalSidecar(bundlePath, actual string) error {
	data, err := os.ReadFile(bundlePath + ".sha256")
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	fields := strings.Fields(string(data))
	if len(fields) == 0 || len(fields[0]) != 64 {
		return fmt.Errorf("invalid .unburger sidecar")
	}
	if !strings.EqualFold(fields[0], actual) {
		return fmt.Errorf(".unburger sidecar checksum mismatch")
	}
	return nil
}

func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func isRegular(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}
