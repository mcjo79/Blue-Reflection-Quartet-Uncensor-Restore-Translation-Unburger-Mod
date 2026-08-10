package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func testSHA(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func TestQuartetMovieRestorationArtifactsMapExactThreeLooseFiles(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "content", "restoration", "movies")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	manifest := quartetMovieManifest{Type: "unburger_quartet_movie_restoration", FormatVersion: 1, TargetRelativeDir: "Data/B1/x64/Movie"}
	for i, name := range quartetMovieNames {
		payload := []byte{byte(i + 1), 0x42, 0x52}
		if err := os.WriteFile(filepath.Join(dir, name), payload, 0o644); err != nil {
			t.Fatal(err)
		}
		manifest.Files = append(manifest.Files, quartetMovieManifestFile{Name: name, SHA256: testSHA(payload)})
	}
	blob, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "MANIFEST.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	artifacts, err := quartetMovieRestorationArtifacts(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(artifacts) != 3 {
		t.Fatalf("expected 3 movie artifacts, got %d", len(artifacts))
	}
	for i, name := range quartetMovieNames {
		want := filepath.ToSlash(filepath.Join("Data/B1/x64/Movie", name))
		if artifacts[i].RelativePath != want {
			t.Fatalf("artifact %d target=%q want=%q", i, artifacts[i].RelativePath, want)
		}
	}
}

func TestQuartetMovieRestorationRejectsTamperedPayload(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "content", "restoration", "movies")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	manifest := quartetMovieManifest{Type: "unburger_quartet_movie_restoration", FormatVersion: 1, TargetRelativeDir: "Data/B1/x64/Movie"}
	for _, name := range quartetMovieNames {
		payload := []byte("expected-" + name)
		if err := os.WriteFile(filepath.Join(dir, name), payload, 0o644); err != nil {
			t.Fatal(err)
		}
		manifest.Files = append(manifest.Files, quartetMovieManifestFile{Name: name, SHA256: testSHA(payload)})
	}
	blob, _ := json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(dir, "MANIFEST.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, quartetMovieNames[1]), []byte("tampered"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := quartetMovieRestorationArtifacts(root); err == nil {
		t.Fatal("tampered movie restoration payload was accepted")
	}
}
