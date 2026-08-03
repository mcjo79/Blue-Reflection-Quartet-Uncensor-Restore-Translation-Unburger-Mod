package main

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestInstallationStateDirectoryIsStoreIndependentAndInstallationSpecific(t *testing.T) {
	base := filepath.Join(t.TempDir(), "state")
	first := installationStateDirectory(base, "blue_reflection_original", filepath.Join(t.TempDir(), "game-a"))
	second := installationStateDirectory(base, "blue_reflection_original", filepath.Join(t.TempDir(), "game-b"))
	if first == second {
		t.Fatal("different installations received the same state directory")
	}
	for _, forbidden := range []string{"steam", "app-id", "build-id"} {
		if strings.Contains(strings.ToLower(first), forbidden) {
			t.Fatalf("store metadata leaked into state path: %s", first)
		}
	}
	if !strings.Contains(first, "blue_reflection_original-") {
		t.Fatalf("target id missing from state path: %s", first)
	}
}
