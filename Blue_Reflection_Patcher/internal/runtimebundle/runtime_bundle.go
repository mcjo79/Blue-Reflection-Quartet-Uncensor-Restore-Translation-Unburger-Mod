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

	"local/blue-reflection-patcher/internal/workspace"
)

const requiredRecordPath = "content/translation/records.v1.json"

type releaseManifest struct {
	Type          string `json:"type"`
	FormatVersion int    `json:"format_version"`
	CoreVersion   string `json:"core_version"`
}

// PruneOlderRuntimeBundles removes only release payloads that are provably older
// than a unique newest sibling payload. Invalid bundles and duplicate newest
// versions are never deleted automatically because their ordering/identity is
// ambiguous. Repository/materialized roots are left untouched.
func PruneOlderRuntimeBundles(root string) ([]string, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		return nil, nil
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	if isRegular(filepath.Join(abs, requiredRecordPath)) || isRegular(filepath.Join(abs, "workstreams", "translation", "VERSION")) {
		return nil, nil
	}
	bundles, err := filepath.Glob(filepath.Join(abs, "*.unburger"))
	if err != nil {
		return nil, err
	}
	if len(bundles) < 2 {
		return nil, nil
	}
	type candidate struct {
		path        string
		version     [3]int
		versionText string
	}
	items := make([]candidate, 0, len(bundles))
	for _, path := range bundles {
		versionText, err := runtimeBundleCoreVersion(path)
		if err != nil {
			return nil, fmt.Errorf("cannot safely choose among multiple .unburger payloads because %s is not a valid release bundle: %w", filepath.Base(path), err)
		}
		parsed, err := parseCoreVersion(versionText)
		if err != nil {
			return nil, fmt.Errorf("cannot safely order .unburger payload %s: %w", filepath.Base(path), err)
		}
		items = append(items, candidate{path: path, version: parsed, versionText: versionText})
	}
	newest := items[0].version
	for _, item := range items[1:] {
		if compareCoreVersion(item.version, newest) > 0 {
			newest = item.version
		}
	}
	newestCount := 0
	for _, item := range items {
		if compareCoreVersion(item.version, newest) == 0 {
			newestCount++
		}
	}
	if newestCount != 1 {
		return nil, fmt.Errorf("release root contains %d .unburger payloads at the newest version; refusing ambiguous automatic deletion", newestCount)
	}
	var removed []string
	for _, item := range items {
		if compareCoreVersion(item.version, newest) >= 0 {
			continue
		}
		if err := os.Remove(item.path); err != nil {
			return removed, fmt.Errorf("remove older .unburger payload %s: %w", filepath.Base(item.path), err)
		}
		_ = os.Remove(item.path + ".sha256")
		removed = append(removed, item.path)
	}
	sort.Strings(removed)
	return removed, nil
}

func runtimeBundleCoreVersion(path string) (string, error) {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return "", err
	}
	defer zr.Close()
	for _, item := range zr.File {
		if filepath.ToSlash(item.Name) != "RELEASE_MANIFEST.json" {
			continue
		}
		r, err := item.Open()
		if err != nil {
			return "", err
		}
		var manifest releaseManifest
		err = json.NewDecoder(io.LimitReader(r, 1<<20)).Decode(&manifest)
		r.Close()
		if err != nil {
			return "", err
		}
		if manifest.Type != "unburger_release_manifest" || manifest.FormatVersion < 2 || strings.TrimSpace(manifest.CoreVersion) == "" {
			return "", fmt.Errorf("unsupported runtime bundle manifest")
		}
		return strings.TrimSpace(manifest.CoreVersion), nil
	}
	return "", fmt.Errorf("runtime bundle is missing RELEASE_MANIFEST.json")
}

func parseCoreVersion(raw string) ([3]int, error) {
	var out [3]int
	parts := strings.Split(strings.TrimSpace(raw), ".")
	if len(parts) != 3 {
		return out, fmt.Errorf("unsupported core version %q", raw)
	}
	for i, part := range parts {
		if part == "" {
			return out, fmt.Errorf("unsupported core version %q", raw)
		}
		value := 0
		for _, ch := range part {
			if ch < '0' || ch > '9' {
				return out, fmt.Errorf("unsupported core version %q", raw)
			}
			value = value*10 + int(ch-'0')
		}
		out[i] = value
	}
	return out, nil
}

func compareCoreVersion(a, b [3]int) int {
	for i := range a {
		if a[i] < b[i] {
			return -1
		}
		if a[i] > b[i] {
			return 1
		}
	}
	return 0
}

// ResolveProjectRootTransient resolves a public .unburger payload into an OS
// temporary directory. The returned cleanup function must be deferred by the
// command using the payload. Repository roots require no cleanup.
func ResolveProjectRootTransient(root string) (string, func(), error) {
	noop := func() {}
	root = strings.TrimSpace(root)
	if root == "" {
		return "", noop, nil
	}
	abs, err := filepath.Abs(root)
	if err != nil {
		return "", noop, err
	}
	if isRegular(filepath.Join(abs, requiredRecordPath)) || isRegular(filepath.Join(abs, "workstreams", "translation", "VERSION")) {
		return abs, noop, nil
	}
	bundles, err := filepath.Glob(filepath.Join(abs, "*.unburger"))
	if err != nil {
		return "", noop, err
	}
	sort.Strings(bundles)
	if len(bundles) == 0 {
		return abs, noop, nil
	}
	if len(bundles) != 1 {
		return "", noop, fmt.Errorf("release root contains %d .unburger payloads; expected exactly one", len(bundles))
	}
	// One-time migration cleanup for the persistent cache used by older public
	// releases. Failure to remove it must not block the current run.
	if cacheBase, cacheErr := os.UserCacheDir(); cacheErr == nil && strings.TrimSpace(cacheBase) != "" {
		_ = os.RemoveAll(filepath.Join(cacheBase, "unburger-patcher", "runtime-bundles"))
	}
	bundleHash, err := sha256File(bundles[0])
	if err != nil {
		return "", noop, err
	}
	if err := validateOptionalSidecar(bundles[0], bundleHash); err != nil {
		return "", noop, err
	}
	stage, err := workspace.MkdirTemp("unburger-runtime-")
	if err != nil {
		return "", noop, err
	}
	cleanup := func() { _ = os.RemoveAll(stage) }
	if err := extractZip(bundles[0], stage); err != nil {
		cleanup()
		return "", noop, err
	}
	if err := validateMaterialized(stage); err != nil {
		cleanup()
		return "", noop, err
	}
	return stage, cleanup, nil
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
