package br1rebuild

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

const (
	quartetFixtureEntry0 = 0x34
	quartetFixtureEntry1 = 0x1c2050
	quartetFixtureEntry2 = 0x1daf6c
	quartetFixtureTotal  = 0x205f08
)

func makeQuartetTitleG1TFixture(t *testing.T) []byte {
	t.Helper()
	data := make([]byte, quartetFixtureTotal)
	copy(data[:4], []byte("GT1G"))
	binary.LittleEndian.PutUint32(data[8:12], uint32(len(data)))
	const headerSize = 28 + 3*4
	binary.LittleEndian.PutUint32(data[12:16], headerSize)
	binary.LittleEndian.PutUint32(data[16:20], 3)
	binary.LittleEndian.PutUint32(data[20:24], quartetMarkerPlatformWindows)
	starts := []int{quartetFixtureEntry0, quartetFixtureEntry1, quartetFixtureEntry2}
	dims := [][2]int{{1152, 1600}, {672, 152}, {quartetMarkerWidth, quartetMarkerHeight}}
	for index, start := range starts {
		binary.LittleEndian.PutUint32(data[headerSize+index*4:headerSize+index*4+4], uint32(start-headerSize))
		data[start] = 0x10 // one mipmap in the stored high nibble
		data[start+1] = quartetMarkerTextureType
		binary.LittleEndian.PutUint32(data[start+8:start+12], 20)
		binary.LittleEndian.PutUint32(data[start+20:start+24], uint32(dims[index][0]))
		binary.LittleEndian.PutUint32(data[start+24:start+28], uint32(dims[index][1]))
	}
	// Deterministic non-zero payload makes accidental overlap easy to detect.
	info, err := locateQuartetMarkerTexture(data)
	if err != nil {
		t.Fatalf("fixture does not parse: %v", err)
	}
	for i := 0; i < info.PayloadBytes; i++ {
		data[info.PayloadOffset+i] = byte((i*17 + 3) & 0xff)
	}
	return data
}

func TestBC7Mode5MatchesApprovedEncoderCases(t *testing.T) {
	cases := []struct {
		name string
		fill [16]markerRGBA
		want string
	}{
		{name: "transparent", want: "20000000000000000000000000000000"},
		{name: "white", want: "20ffffffffffffff0300000000000000"},
	}
	for i := range cases[1].fill {
		cases[1].fill[i] = markerRGBA{255, 255, 255, 255}
	}
	for _, tc := range cases {
		got, err := encodeBC7Mode5(tc.fill)
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if hex.EncodeToString(got[:]) != tc.want {
			t.Fatalf("%s: got %x want %s", tc.name, got, tc.want)
		}
	}
}

func TestLocateQuartetMarkerTextureSkipsEntryHeaderAndExtendedData(t *testing.T) {
	original := makeQuartetTitleG1TFixture(t)
	got, err := locateQuartetMarkerTexture(original)
	if err != nil {
		t.Fatal(err)
	}
	if got.EntryOffset != quartetFixtureEntry2 {
		t.Fatalf("entry offset = 0x%x, want 0x%x", got.EntryOffset, quartetFixtureEntry2)
	}
	if got.ExtendedBytes != 20 {
		t.Fatalf("extended bytes = %d, want 20", got.ExtendedBytes)
	}
	if got.PayloadOffset != 0x1daf88 {
		t.Fatalf("payload offset = 0x%x, want 0x1daf88", got.PayloadOffset)
	}
	if got.PayloadBytes != quartetMarkerTextureBytes {
		t.Fatalf("payload bytes = 0x%x, want 0x%x", got.PayloadBytes, quartetMarkerTextureBytes)
	}
	if got.PayloadOffset+got.PayloadBytes != len(original) {
		t.Fatalf("payload does not end at G1T end: 0x%x != 0x%x", got.PayloadOffset+got.PayloadBytes, len(original))
	}
}

func TestPatchQuartetMarkerPreservesG1TStructureAndReplacesAllTexture002Blocks(t *testing.T) {
	original := makeQuartetTitleG1TFixture(t)
	info, err := locateQuartetMarkerTexture(original)
	if err != nil {
		t.Fatal(err)
	}
	headerAndExtended := append([]byte(nil), original[info.EntryOffset:info.PayloadOffset]...)
	patched, patchedBlocks, err := patchQuartetMarkerG1T(original, "UNBURGER / UNCENSOR / DLC")
	if err != nil {
		t.Fatal(err)
	}
	if patchedBlocks != quartetMarkerTextureBytes/16 {
		t.Fatalf("patched blocks=%d want=%d", patchedBlocks, quartetMarkerTextureBytes/16)
	}
	if !bytes.Equal(original[:info.PayloadOffset], patched[:info.PayloadOffset]) {
		t.Fatal("bytes before texture 002 BC7 payload changed")
	}
	if !bytes.Equal(original[info.PayloadOffset+info.PayloadBytes:], patched[info.PayloadOffset+info.PayloadBytes:]) {
		t.Fatal("bytes after texture 002 BC7 payload changed")
	}
	if !bytes.Equal(headerAndExtended, patched[info.EntryOffset:info.PayloadOffset]) {
		t.Fatal("texture 002 header or extended dimensions changed")
	}
	if bytes.Equal(original[info.PayloadOffset:info.PayloadOffset+info.PayloadBytes], patched[info.PayloadOffset:info.PayloadOffset+info.PayloadBytes]) {
		t.Fatal("texture 002 payload did not change")
	}
	if _, err := locateQuartetMarkerTexture(patched); err != nil {
		t.Fatalf("patched G1T structure is no longer valid: %v", err)
	}
}

func TestApprovedQuartetMarkerPayloadHash(t *testing.T) {
	pixels, err := renderQuartetMarker("UNBURGER / UNCENSOR")
	if err != nil {
		t.Fatal(err)
	}
	payload, err := encodeQuartetMarkerBC7(pixels)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(payload)
	const want = "5b3efaa4cf490572a49c2d72906ef528de7337494388b5cc017bb798751035e9"
	if hex.EncodeToString(sum[:]) != want {
		t.Fatalf("approved marker payload changed: got %x want %s", sum, want)
	}
}

func TestLocateQuartetMarkerTextureRejectsCorruptExtendedDimensions(t *testing.T) {
	original := makeQuartetTitleG1TFixture(t)
	binary.LittleEndian.PutUint32(original[quartetFixtureEntry2+20:quartetFixtureEntry2+24], 1759)
	if _, err := locateQuartetMarkerTexture(original); err == nil {
		t.Fatal("corrupt texture dimensions were accepted")
	}
}

func TestApplyQuartetTitleMarkerRewritesOnlyConfirmedMember(t *testing.T) {
	root := t.TempDir()
	source := filepath.Join(root, "PACK00_04_01.PAK")
	g1t := makeQuartetTitleG1TFixture(t)
	other := []byte("unchanged fixture member")
	writeA22Fixture(t, source, map[string][]byte{
		quartetMarkerMember:                g1t,
		`\data\b4\x64\res_en\ui\other.bin`: other,
	})
	audit, output, err := ApplyQuartetTitleMarker(filepath.Join(root, "out"), source, "UNBURGER / UNCENSOR / DLC", nil)
	if err != nil {
		t.Fatal(err)
	}
	if audit.Label != "UNBURGER / UNCENSOR / DLC" || audit.PatchedBlocks != quartetMarkerTextureBytes/16 || audit.EntriesChecked != 2 {
		t.Fatalf("unexpected audit: %+v", audit)
	}
	reader, err := OpenA22(output)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	entry, ok := reader.Find(`\data\b4\x64\res_en\ui\other.bin`)
	if !ok {
		t.Fatal("other member missing")
	}
	got, err := reader.Read(entry)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, other) {
		t.Fatal("unrelated member changed")
	}
	markerEntry, ok := reader.Find(quartetMarkerMember)
	if !ok {
		t.Fatal("marker member missing")
	}
	marker, err := reader.Read(markerEntry)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := locateQuartetMarkerTexture(marker); err != nil {
		t.Fatalf("rewritten member is structurally invalid: %v", err)
	}
	if info, err := os.Stat(output); err != nil || !info.Mode().IsRegular() {
		t.Fatalf("output missing: %v", err)
	}
}

func TestQuartetMarkerAcceptsVersionedThreeModuleReleaseLabel(t *testing.T) {
	label := "UNBURGER (v0.0.203) / UNCENSOR (v0.1.78) / DLC (v0.1.0)"
	pixels, err := renderQuartetMarker(label)
	if err != nil {
		t.Fatal(err)
	}
	if len(pixels) != quartetMarkerWidth*quartetMarkerHeight {
		t.Fatalf("pixel count=%d want=%d", len(pixels), quartetMarkerWidth*quartetMarkerHeight)
	}
	payload, err := encodeQuartetMarkerBC7(pixels)
	if err != nil {
		t.Fatal(err)
	}
	if len(payload) != quartetMarkerTextureBytes {
		t.Fatalf("payload bytes=%d want=%d", len(payload), quartetMarkerTextureBytes)
	}
}
