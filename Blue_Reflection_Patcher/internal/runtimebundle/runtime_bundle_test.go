package runtimebundle

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
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
	resolved, err := ResolveProjectRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	if resolved == root {
		t.Fatal("expected a materialized cache root")
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
	if _, err := ResolveProjectRoot(root); err == nil {
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
