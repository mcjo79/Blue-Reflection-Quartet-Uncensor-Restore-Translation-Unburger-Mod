package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

func writeCompositionMemberFixture(t *testing.T, root, relative string, data []byte) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestVerifyLegacyDLCMemberDeltaAcceptsExactPACK12Change(t *testing.T) {
	baselineRoot := t.TempDir()
	candidateRoot := t.TempDir()
	entries := []string{"saves/b1/chara/charabase.xml", "saves/b1/text_en/unchanged.xml"}
	writeCompositionMemberFixture(t, baselineRoot, entries[0], []byte("baseline-charabase"))
	writeCompositionMemberFixture(t, candidateRoot, entries[0], []byte("dlc-charabase"))
	writeCompositionMemberFixture(t, baselineRoot, entries[1], []byte("same"))
	writeCompositionMemberFixture(t, candidateRoot, entries[1], []byte("same"))
	baseline := compositionExtractedArchive{Root: baselineRoot, Entries: entries}
	candidate := compositionExtractedArchive{Root: candidateRoot, Entries: entries}
	baselineMembers, err := hashCompositionMembers(baselineRoot, entries)
	if err != nil {
		t.Fatal(err)
	}
	overlays, err := verifyLegacyDLCMemberDelta(baseline, baselineMembers, candidate, payloadpreview.LegacyDLCCompositionArtifact{
		RelativePath: "Data/PACK12.PAK", ChangedMembers: []string{"saves/b1/chara/charabase.xml"}, AddedMembers: []string{}, RemovedMembers: []string{},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(overlays) != 1 {
		t.Fatalf("unexpected overlay count: %d", len(overlays))
	}
	for _, overlay := range overlays {
		if len(overlay.Member.SourceModuleIDs) != 1 || overlay.Member.SourceModuleIDs[0] != quartetLegacyDLCModule {
			t.Fatalf("Legacy DLC provenance missing: %+v", overlay.Member)
		}
	}
}

func TestVerifyLegacyDLCMemberDeltaRejectsUndeclaredChange(t *testing.T) {
	baselineRoot := t.TempDir()
	candidateRoot := t.TempDir()
	entries := []string{"saves/b1/chara/charabase.xml", "unexpected.bin"}
	for _, relative := range entries {
		writeCompositionMemberFixture(t, baselineRoot, relative, []byte("baseline-"+relative))
		writeCompositionMemberFixture(t, candidateRoot, relative, []byte("candidate-"+relative))
	}
	baseline := compositionExtractedArchive{Root: baselineRoot, Entries: entries}
	candidate := compositionExtractedArchive{Root: candidateRoot, Entries: entries}
	baselineMembers, err := hashCompositionMembers(baselineRoot, entries)
	if err != nil {
		t.Fatal(err)
	}
	_, err = verifyLegacyDLCMemberDelta(baseline, baselineMembers, candidate, payloadpreview.LegacyDLCCompositionArtifact{
		RelativePath: "Data/PACK12.PAK", ChangedMembers: []string{"saves/b1/chara/charabase.xml"}, AddedMembers: []string{}, RemovedMembers: []string{},
	})
	if err == nil || !strings.Contains(err.Error(), "member delta mismatch") {
		t.Fatalf("undeclared change was not rejected: %v", err)
	}
}

func TestMergeModuleCompositionOverlayRejectsNonIdenticalConflict(t *testing.T) {
	overlays := map[string]compositionOverlaySource{
		"shared": {Member: compositionBuildMember{InternalPath: "shared.bin", SHA256: strings.Repeat("a", 64), Bytes: 1, SourceModuleIDs: []string{quartetLegacyDLCModule}}},
	}
	err := mergeModuleCompositionOverlay(overlays, "shared", compositionOverlaySource{
		Member: compositionBuildMember{InternalPath: "shared.bin", SHA256: strings.Repeat("b", 64), Bytes: 1, SourceModuleIDs: []string{quartetRestorationModule}},
	})
	if err == nil || !strings.Contains(err.Error(), "non-identical module overlay conflict") {
		t.Fatalf("non-identical conflict was not rejected: %v", err)
	}
}

func TestMergeModuleCompositionOverlayCoalescesIdenticalProvenance(t *testing.T) {
	overlays := map[string]compositionOverlaySource{
		"shared": {Member: compositionBuildMember{InternalPath: "shared.bin", SHA256: strings.Repeat("a", 64), Bytes: 1, SourceModuleIDs: []string{quartetLegacyDLCModule}}},
	}
	err := mergeModuleCompositionOverlay(overlays, "shared", compositionOverlaySource{
		Member: compositionBuildMember{InternalPath: "shared.bin", SHA256: strings.Repeat("a", 64), Bytes: 1, SourceModuleIDs: []string{quartetRestorationModule}},
	})
	if err != nil {
		t.Fatal(err)
	}
	got := overlays["shared"].Member.SourceModuleIDs
	if len(got) != 2 || got[0] != quartetLegacyDLCModule || got[1] != quartetRestorationModule {
		t.Fatalf("identical provenance was not coalesced: %v", got)
	}
}
