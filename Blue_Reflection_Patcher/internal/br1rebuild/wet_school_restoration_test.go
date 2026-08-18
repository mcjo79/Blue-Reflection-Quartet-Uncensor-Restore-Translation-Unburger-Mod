package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func TestApplyWetSchoolRestorationReplacesOnlyValidatedRosterMembers(t *testing.T) {
	sourceRoot := t.TempDir()
	if err := os.MkdirAll(filepath.Join(sourceRoot, "DATA"), 0o755); err != nil {
		t.Fatal(err)
	}
	sourceItems := map[string][]byte{}
	targetItems := map[string][]byte{`\data\b1\x64\keep\noise.bin`: []byte("keep-me")}
	for i := 0; i < 15; i++ {
		pc := fmt.Sprintf("pc%02d", i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			src := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			dst := `\data\b1\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			sourceItems[src] = []byte("original-" + pc + suffix)
			targetItems[dst] = []byte("quartet-" + pc + suffix)
		}
	}
	if err := writePlainA18(filepath.Join(sourceRoot, "DATA", "PACK00_02.PAK"), archiveInputs(sourceItems)); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "PACK10_02.PAK")
	writeA22Fixture(t, target, targetItems)
	work := t.TempDir()
	audit, candidates, err := ApplyWetSchoolRestoration(work, sourceRoot, map[string]string{wetSchoolTargetArchiveRelative: target}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if audit.Characters != 15 || audit.ReplacedMembers != 30 || len(audit.Members) != 30 {
		t.Fatalf("unexpected audit: %+v", audit)
	}
	out := candidates[wetSchoolTargetArchiveRelative]
	p, err := OpenA22(out)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	for i := 0; i < 15; i++ {
		pc := fmt.Sprintf("pc%02d", i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			src := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			dst := `\data\b1\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			e, ok := p.Find(dst)
			if !ok {
				t.Fatalf("missing output %s", dst)
			}
			got, err := p.Read(e)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != string(sourceItems[src]) {
				t.Fatalf("wrong donor payload for %s: %q", dst, got)
			}
		}
	}
	e, ok := p.Find(`\data\b1\x64\keep\noise.bin`)
	if !ok {
		t.Fatal("unrelated target member was lost")
	}
	got, err := p.Read(e)
	if err != nil || string(got) != "keep-me" {
		t.Fatalf("unrelated target member changed: %q %v", got, err)
	}
}

func archiveInputs(items map[string][]byte) map[string]ArchiveInput {
	out := make(map[string]ArchiveInput, len(items))
	for name, data := range items {
		out[name] = MemoryEntry{Data: data}
	}
	return out
}
