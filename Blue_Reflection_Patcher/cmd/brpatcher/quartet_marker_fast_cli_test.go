package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestReplaceFastMarkerFileInstallAndRestoreExact(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "PACK00_04_01.PAK")
	candidate := filepath.Join(root, "candidate.PAK")
	backup := filepath.Join(root, "backup.PAK")
	original := bytes.Repeat([]byte("original-marker-pak\n"), 1024)
	desired := bytes.Repeat([]byte("candidate-marker-pak\n"), 1024)
	if err := os.WriteFile(target, original, 0o644); err != nil {
		t.Fatal(err)
	}
	originalHash, originalBytes, err := copyAndHashFastMarker(target, backup, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(candidate, desired, 0o600); err != nil {
		t.Fatal(err)
	}
	candidateHash, candidateBytes, err := hashFastMarkerFile(candidate)
	if err != nil {
		t.Fatal(err)
	}
	if err := replaceFastMarkerFile(candidate, target, candidateHash, candidateBytes, originalHash, originalBytes); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, desired) {
		t.Fatal("candidate was not installed exactly")
	}
	if err := replaceFastMarkerFile(backup, target, originalHash, originalBytes, candidateHash, candidateBytes); err != nil {
		t.Fatal(err)
	}
	got, err = os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Fatal("original was not restored byte-for-byte")
	}
}

func TestReplaceFastMarkerFileRefusesTargetDrift(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "PACK00_04_01.PAK")
	candidate := filepath.Join(root, "candidate.PAK")
	if err := os.WriteFile(target, []byte("current"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(candidate, []byte("candidate"), 0o644); err != nil {
		t.Fatal(err)
	}
	candidateHash, candidateBytes, err := hashFastMarkerFile(candidate)
	if err != nil {
		t.Fatal(err)
	}
	if err := replaceFastMarkerFile(candidate, target, candidateHash, candidateBytes, "0000000000000000000000000000000000000000000000000000000000000000", 7); err == nil {
		t.Fatal("target drift was not rejected")
	}
	got, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != "current" {
		t.Fatal("target changed after rejected fast replacement")
	}
}
