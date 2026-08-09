package br1rebuild

import (
	"bytes"
	"path/filepath"
	"testing"
)

func TestArchiveAuditReportsProgressInsideLargeMember(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "source.pak")
	dst := filepath.Join(root, "candidate.pak")
	payload := bytes.Repeat([]byte{0x5a}, 20<<20)
	items := map[string][]byte{`\data\b1\x64\field\large.bin`: payload}
	writeA22Fixture(t, src, items)
	writeA22Fixture(t, dst, items)
	var samples []int64
	_, err := AuditA22Rewrite(src, dst, map[string]string{}, map[string]ArchiveInput{}, func(phase, name string, done, total int64) {
		if phase == "verify" && name == `\data\b1\x64\field\large.bin` {
			samples = append(samples, done)
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(samples) < 4 {
		t.Fatalf("expected chunk-level progress samples, got %d: %v", len(samples), samples)
	}
	foundIntermediate := false
	for _, value := range samples {
		if value > 0 && value < int64(len(payload)) {
			foundIntermediate = true
			break
		}
	}
	if !foundIntermediate {
		t.Fatalf("no intermediate member progress reported: %v", samples)
	}
}
