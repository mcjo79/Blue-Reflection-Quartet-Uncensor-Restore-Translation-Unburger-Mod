package main

import (
	"strings"
	"testing"
)

func TestParseGustPakListingNormalizesArchiveRoot(t *testing.T) {
	listing := "Listing 'PACK11.PAK'...\nOFFSET    SIZE     NAME\n000000160 00000020 \\event\\b1\\event_jp\\test.ebd*\n"
	entries, err := parseGustPakListing(listing)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0] != "event/b1/event_jp/test.ebd" {
		t.Fatalf("unexpected entries: %#v", entries)
	}
}

func TestParseGustPakListingRejectsCaseFoldedDuplicate(t *testing.T) {
	listing := "OFFSET    SIZE     NAME\n" +
		"000000160 00000020 event/b1/Test.ebd*\n" +
		"000000180 00000020 event/b1/test.ebd*\n"
	if _, err := parseGustPakListing(listing); err == nil || !strings.Contains(err.Error(), "duplicate") {
		t.Fatalf("expected duplicate-member rejection, got %v", err)
	}
}

func TestNormalizeCompositionMemberRejectsTraversal(t *testing.T) {
	for _, candidate := range []string{"../outside", "a/../outside", "C:/outside", "/../outside", "a//b"} {
		if _, err := normalizeCompositionMember(candidate); err == nil {
			t.Fatalf("unsafe member accepted: %q", candidate)
		}
	}
}

func TestMergeCompositionOverlayCoalescesIdenticalPayload(t *testing.T) {
	overlays := map[string]compositionOverlaySource{}
	first := compositionOverlaySource{Member: compositionBuildMember{InternalPath: "a.bin", SHA256: strings.Repeat("a", 64), Bytes: 7, SourceProfileIDs: []string{"p1"}}, SourcePath: "one"}
	second := compositionOverlaySource{Member: compositionBuildMember{InternalPath: "a.bin", SHA256: strings.Repeat("a", 64), Bytes: 7, SourceProfileIDs: []string{"p2"}}, SourcePath: "two"}
	if err := mergeCompositionOverlay(overlays, "a.bin", first); err != nil {
		t.Fatal(err)
	}
	if err := mergeCompositionOverlay(overlays, "a.bin", second); err != nil {
		t.Fatal(err)
	}
	owners := overlays["a.bin"].Member.SourceProfileIDs
	if len(owners) != 2 || owners[0] != "p1" || owners[1] != "p2" {
		t.Fatalf("identical overlay owners were not coalesced: %#v", owners)
	}
}

func TestMergeCompositionOverlayBlocksDifferentPayload(t *testing.T) {
	overlays := map[string]compositionOverlaySource{}
	first := compositionOverlaySource{Member: compositionBuildMember{InternalPath: "a.bin", SHA256: strings.Repeat("a", 64), Bytes: 7, SourceProfileIDs: []string{"p1"}}}
	second := compositionOverlaySource{Member: compositionBuildMember{InternalPath: "a.bin", SHA256: strings.Repeat("b", 64), Bytes: 7, SourceProfileIDs: []string{"p2"}}}
	if err := mergeCompositionOverlay(overlays, "a.bin", first); err != nil {
		t.Fatal(err)
	}
	if err := mergeCompositionOverlay(overlays, "a.bin", second); err == nil || !strings.Contains(err.Error(), "non-identical") {
		t.Fatalf("different overlay payload was not blocked: %v", err)
	}
}
