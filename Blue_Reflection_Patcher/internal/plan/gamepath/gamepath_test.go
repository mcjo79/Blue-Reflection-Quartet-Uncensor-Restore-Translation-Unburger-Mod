package gamepath

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolvePreservesExistingCaseInsensitivePath(t *testing.T) {
	root := t.TempDir()
	actual := filepath.Join(root, "data", "pack01.pak")
	if err := os.MkdirAll(filepath.Dir(actual), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(actual, []byte("pak"), 0o644); err != nil {
		t.Fatal(err)
	}
	resolved, exists, err := Resolve(root, "DATA/PACK01.PAK")
	if err != nil {
		t.Fatal(err)
	}
	if !exists || resolved != actual {
		t.Fatalf("resolved=%q exists=%v want=%q", resolved, exists, actual)
	}
}

func TestResolveRejectsAmbiguousCaseFold(t *testing.T) {
	root := t.TempDir()
	for _, name := range []string{"DATA", "data"} {
		if err := os.MkdirAll(filepath.Join(root, name), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if _, _, err := Resolve(root, "Data/PACK01.PAK"); err == nil {
		t.Fatal("expected ambiguous case-insensitive path rejection")
	}
}
