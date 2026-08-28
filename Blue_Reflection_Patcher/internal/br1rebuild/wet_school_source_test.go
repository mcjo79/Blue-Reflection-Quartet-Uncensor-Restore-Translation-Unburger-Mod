package br1rebuild

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestWetSchoolSourceMemberNamesExactRoster(t *testing.T) {
	wanted := wetSchoolSourceMemberNames()
	if len(wanted) != 30 {
		t.Fatalf("wet-school member set=%d, expected 30", len(wanted))
	}
	for i := 0; i < 15; i++ {
		pc := fmtPC(i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			name := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			if !wanted[name] {
				t.Fatalf("missing %s", name)
			}
		}
	}
}

func TestValidateWetSchoolCanonicalPayloadExactRoster(t *testing.T) {
	payloadRoot := t.TempDir()
	sourceRoot := filepath.Join(payloadRoot, "source")
	if err := os.MkdirAll(filepath.Join(sourceRoot, "DATA"), 0o755); err != nil {
		t.Fatal(err)
	}
	items := map[string]ArchiveInput{}
	members := make([]SourceAssetMember, 0, 30)
	for i := 0; i < 15; i++ {
		pc := fmtPC(i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			name := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			payload := []byte("canonical-" + pc + suffix)
			items[name] = MemoryEntry{Data: payload}
			members = append(members, SourceAssetMember{Group: "quartet_wet_school", ArchivePath: "DATA/PACK00_02.PAK", MemberPath: name, Size: int64(len(payload)), SHA256: shaBytes(payload)})
		}
	}
	if err := writePlainA18(filepath.Join(sourceRoot, "DATA", "PACK00_02.PAK"), items); err != nil {
		t.Fatal(err)
	}
	members, err := normalizeSourceMembers(members)
	if err != nil {
		t.Fatal(err)
	}
	manifest := WetSchoolCanonicalSourceManifest{
		Type: "unburger_quartet_wet_school_canonical_source", FormatVersion: 1,
		Capability: WetSchoolCanonicalSourceCapability, SourceFingerprint: sourceAssetFingerprint(members), SourceMembers: members,
	}
	blob, _ := json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(payloadRoot, "MANIFEST.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateWetSchoolCanonicalPayload(payloadRoot); err != nil {
		t.Fatal(err)
	}
	// Tamper with one manifest hash: canonical payload validation must fail closed.
	manifest.SourceMembers[0].SHA256 = "0000000000000000000000000000000000000000000000000000000000000000"
	blob, _ = json.Marshal(manifest)
	if err := os.WriteFile(filepath.Join(payloadRoot, "MANIFEST.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateWetSchoolCanonicalPayload(payloadRoot); err == nil {
		t.Fatal("tampered canonical wet-school manifest was accepted")
	}
}

func TestCopyWetSchoolCanonicalPayloadFromLocalCache(t *testing.T) {
	sourcePayload := t.TempDir()
	sourceRoot := filepath.Join(sourcePayload, "source")
	if err := os.MkdirAll(filepath.Join(sourceRoot, "DATA"), 0o755); err != nil {
		t.Fatal(err)
	}
	items := map[string]ArchiveInput{}
	members := make([]SourceAssetMember, 0, 30)
	for i := 0; i < 15; i++ {
		pc := fmtPC(i)
		for _, suffix := range []string{".elixir.gz", ".g1t"} {
			name := `\data\x64\character\` + pc + `\` + pc + `_scl_w` + suffix
			payload := []byte("cached-" + pc + suffix)
			items[name] = MemoryEntry{Data: payload}
			members = append(members, SourceAssetMember{Group: "quartet_wet_school", ArchivePath: "DATA/PACK00_02.PAK", MemberPath: name, Size: int64(len(payload)), SHA256: shaBytes(payload)})
		}
	}
	if err := writePlainA18(filepath.Join(sourceRoot, "DATA", "PACK00_02.PAK"), items); err != nil {
		t.Fatal(err)
	}
	members, err := normalizeSourceMembers(members)
	if err != nil {
		t.Fatal(err)
	}
	manifest := WetSchoolCanonicalSourceManifest{
		Type: "unburger_quartet_wet_school_canonical_source", FormatVersion: 1,
		Capability: WetSchoolCanonicalSourceCapability, SourceFingerprint: sourceAssetFingerprint(members), SourceMembers: members,
	}
	blob, _ := json.MarshalIndent(manifest, "", "  ")
	if err := os.WriteFile(filepath.Join(sourcePayload, "MANIFEST.json"), append(blob, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := ValidateWetSchoolCanonicalPayload(sourcePayload); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(t.TempDir(), "wet-school")
	copied, err := CopyWetSchoolCanonicalPayload(sourcePayload, destination)
	if err != nil {
		t.Fatal(err)
	}
	if copied.SourceFingerprint != manifest.SourceFingerprint || len(copied.SourceMembers) != 30 {
		t.Fatalf("unexpected copied manifest: %+v", copied)
	}
	if err := ValidateWetSchoolCanonicalPayload(destination); err != nil {
		t.Fatal(err)
	}
	srcPack, err := os.ReadFile(filepath.Join(sourcePayload, "source", "DATA", "PACK00_02.PAK"))
	if err != nil {
		t.Fatal(err)
	}
	dstPack, err := os.ReadFile(filepath.Join(destination, "source", "DATA", "PACK00_02.PAK"))
	if err != nil {
		t.Fatal(err)
	}
	if string(srcPack) != string(dstPack) {
		t.Fatal("local canonical source cache was not copied byte-exactly")
	}
}

func fmtPC(i int) string {
	return string([]byte{'p', 'c', byte('0' + i/10), byte('0' + i%10)})
}
