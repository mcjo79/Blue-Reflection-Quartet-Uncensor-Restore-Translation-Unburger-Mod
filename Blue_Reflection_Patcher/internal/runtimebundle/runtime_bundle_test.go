package runtimebundle

import (
	"archive/tar"
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestResolveProjectRootMaterializesUnburgerZip(t *testing.T) {
	root := t.TempDir()
	files := map[string][]byte{
		"RELEASE_MANIFEST.json":               []byte("{\"type\":\"unburger_release_manifest\",\"format_version\":2,\"core_version\":\"test\"}\n"),
		"content/translation/records.v1.json": []byte("{}\n"),
	}
	var sums string
	for name, data := range files {
		h := sha256.Sum256(data)
		sums += fmt.Sprintf("%s  ./%s\n", hex.EncodeToString(h[:]), name)
	}
	files["SHA256SUMS"] = []byte(sums)
	bundle := filepath.Join(root, "UNBURGER_test.unburger")
	writeZip(t, bundle, files)
	resolved, cleanup, err := ResolveProjectRootTransient(root)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if resolved == root {
		t.Fatal("expected a materialized temporary root")
	}
	if _, err := os.Stat(filepath.Join(resolved, requiredRecordPath)); err != nil {
		t.Fatal(err)
	}
}

func TestResolveProjectRootRejectsTraversal(t *testing.T) {
	root := t.TempDir()
	bundle := filepath.Join(root, "UNBURGER_bad.unburger")
	f, err := os.Create(bundle)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	w, err := zw.Create("../escape")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = w.Write([]byte("x"))
	_ = zw.Close()
	_ = f.Close()
	if _, cleanup, err := ResolveProjectRootTransient(root); err == nil {
		cleanup()
		t.Fatal("expected unsafe entry rejection")
	}
}

func writeZip(t *testing.T, path string, files map[string][]byte) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	zw := zip.NewWriter(f)
	for name, data := range files {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestResolveProjectRootTransientCleansMaterializedPayload(t *testing.T) {
	root := t.TempDir()
	files := map[string][]byte{
		"RELEASE_MANIFEST.json":               []byte("{\"type\":\"unburger_release_manifest\",\"format_version\":2,\"core_version\":\"test\"}\n"),
		"content/translation/records.v1.json": []byte("{}\n"),
	}
	var sums string
	for name, data := range files {
		h := sha256.Sum256(data)
		sums += fmt.Sprintf("%s  ./%s\n", hex.EncodeToString(h[:]), name)
	}
	files["SHA256SUMS"] = []byte(sums)
	writeZip(t, filepath.Join(root, "UNBURGER_test.unburger"), files)
	resolved, cleanup, err := ResolveProjectRootTransient(root)
	if err != nil {
		t.Fatal(err)
	}
	if resolved == root {
		t.Fatal("expected transient materialization")
	}
	if _, err := os.Stat(filepath.Join(resolved, requiredRecordPath)); err != nil {
		t.Fatal(err)
	}
	cleanup()
	if _, err := os.Stat(resolved); !os.IsNotExist(err) {
		t.Fatalf("transient runtime root survived cleanup: %v", err)
	}
}

func TestPruneOlderRuntimeBundlesKeepsUniqueNewest(t *testing.T) {
	root := t.TempDir()
	writeRuntimeBundleForVersion(t, filepath.Join(root, "UNBURGER_0.0.96.unburger"), "0.0.96")
	oldSidecar := filepath.Join(root, "UNBURGER_0.0.96.unburger.sha256")
	if err := os.WriteFile(oldSidecar, []byte("unused\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	newest := filepath.Join(root, "UNBURGER_0.0.98.unburger")
	writeRuntimeBundleForVersion(t, newest, "0.0.98")

	removed, err := PruneOlderRuntimeBundles(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(removed) != 1 || filepath.Clean(removed[0]) != filepath.Clean(filepath.Join(root, "UNBURGER_0.0.96.unburger")) {
		t.Fatalf("unexpected removed set: %#v", removed)
	}
	if _, err := os.Stat(filepath.Join(root, "UNBURGER_0.0.96.unburger")); !os.IsNotExist(err) {
		t.Fatalf("older payload survived: %v", err)
	}
	if _, err := os.Stat(oldSidecar); !os.IsNotExist(err) {
		t.Fatalf("older payload sidecar survived: %v", err)
	}
	if _, err := os.Stat(newest); err != nil {
		t.Fatalf("newest payload was removed: %v", err)
	}
	resolved, cleanup, err := ResolveProjectRootTransient(root)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if resolved == root {
		t.Fatal("newest payload was not materialized")
	}
}

func TestPruneOlderRuntimeBundlesRefusesDuplicateNewestVersion(t *testing.T) {
	root := t.TempDir()
	writeRuntimeBundleForVersion(t, filepath.Join(root, "UNBURGER_A.unburger"), "0.0.98")
	writeRuntimeBundleForVersion(t, filepath.Join(root, "UNBURGER_B.unburger"), "0.0.98")
	if _, err := PruneOlderRuntimeBundles(root); err == nil {
		t.Fatal("expected duplicate newest version to remain fail-closed")
	}
	for _, name := range []string{"UNBURGER_A.unburger", "UNBURGER_B.unburger"} {
		if _, err := os.Stat(filepath.Join(root, name)); err != nil {
			t.Fatalf("ambiguous newest payload was deleted: %s: %v", name, err)
		}
	}
}

func writeRuntimeBundleForVersion(t *testing.T, path, version string) {
	t.Helper()
	files := map[string][]byte{
		"RELEASE_MANIFEST.json":               []byte(fmt.Sprintf("{\"type\":\"unburger_release_manifest\",\"format_version\":2,\"core_version\":%q}\n", version)),
		"content/translation/records.v1.json": []byte("{}\n"),
	}
	var sums string
	for name, data := range files {
		h := sha256.Sum256(data)
		sums += fmt.Sprintf("%s  ./%s\n", hex.EncodeToString(h[:]), name)
	}
	files["SHA256SUMS"] = []byte(sums)
	writeZip(t, path, files)
}

func TestResolveProjectRootMaterializesUnburgerV3TarZstd(t *testing.T) {
	if _, err := exec.LookPath("zstd"); err != nil {
		t.Skip("zstd CLI unavailable")
	}
	root := t.TempDir()
	files := map[string][]byte{
		"RELEASE_MANIFEST.json":               []byte("{\"type\":\"unburger_release_manifest\",\"format_version\":3,\"core_version\":\"0.0.100\"}\n"),
		"content/translation/records.v1.json": []byte("{}\n"),
	}
	var sums string
	for name, data := range files {
		h := sha256.Sum256(data)
		sums += fmt.Sprintf("%s  ./%s\n", hex.EncodeToString(h[:]), name)
	}
	files["SHA256SUMS"] = []byte(sums)
	tarPath := filepath.Join(root, "payload.tar")
	f, err := os.Create(tarPath)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	for _, name := range []string{"RELEASE_MANIFEST.json", "content/translation/records.v1.json", "SHA256SUMS"} {
		data := files[name]
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o644, Size: int64(len(data))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	bundle := filepath.Join(root, "UNBURGER_0.0.100.unburger")
	cmd := exec.Command("zstd", "-q", "-19", "-f", tarPath, "-o", bundle)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("zstd: %v: %s", err, out)
	}
	_ = os.Remove(tarPath)
	version, err := runtimeBundleCoreVersion(bundle)
	if err != nil {
		t.Fatal(err)
	}
	if version != "0.0.100" {
		t.Fatalf("version=%q", version)
	}
	resolved, cleanup, err := ResolveProjectRootTransient(root)
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if _, err := os.Stat(filepath.Join(resolved, requiredRecordPath)); err != nil {
		t.Fatal(err)
	}
}
