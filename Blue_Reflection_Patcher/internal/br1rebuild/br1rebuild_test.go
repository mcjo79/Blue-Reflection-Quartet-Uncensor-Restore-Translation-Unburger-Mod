package br1rebuild

import (
	"bytes"
	"encoding/binary"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeA18Fixture(t *testing.T, path string, items map[string][]byte) *ArchiveReader {
	t.Helper()
	names := []string{}
	for n := range items {
		names = append(names, n)
	}
	sortStrings(names)
	key := []byte("12345678901234567890")
	table := make([]byte, len(names)*a18EntrySize)
	var off uint64
	var data []byte
	for i, n := range names {
		raw := table[i*a18EntrySize : (i+1)*a18EntrySize]
		nb := make([]byte, 128)
		copy(nb, []byte(n))
		xorInPlace(nb, key, 0)
		copy(raw[:128], nb)
		binary.LittleEndian.PutUint32(raw[128:132], uint32(len(items[n])))
		copy(raw[132:152], key)
		binary.LittleEndian.PutUint64(raw[152:160], off)
		plain := append([]byte(nil), items[n]...)
		xorInPlace(plain, key, 0)
		data = append(data, plain...)
		off += uint64(len(plain))
	}
	hdr := make([]byte, 16)
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(names)))
	binary.LittleEndian.PutUint32(hdr[8:12], 16)
	binary.LittleEndian.PutUint32(hdr[12:16], 0x10)
	blob := append(hdr, table...)
	blob = append(blob, data...)
	if err := os.WriteFile(path, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	p, err := OpenA18(path)
	if err != nil {
		t.Fatal(err)
	}
	return p
}
func writeA22Fixture(t *testing.T, path string, items map[string][]byte) {
	t.Helper()
	names := []string{}
	for n := range items {
		names = append(names, n)
	}
	sortStrings(names)
	entryKey := []byte("abcdefghijklmnopqrstuvwxyzABCDEF")
	master := a22MasterKeys[2].key
	eff := effectiveKey(entryKey, master)
	table := make([]byte, len(names)*a22EntrySize)
	var off uint64
	var data []byte
	for i, n := range names {
		raw := table[i*a22EntrySize : (i+1)*a22EntrySize]
		nb := make([]byte, 128)
		copy(nb, []byte(n))
		xorInPlace(nb, eff, 0)
		copy(raw[:128], nb)
		binary.LittleEndian.PutUint32(raw[128:132], uint32(len(items[n])))
		copy(raw[132:164], entryKey)
		binary.LittleEndian.PutUint64(raw[168:176], off)
		plain := append([]byte(nil), items[n]...)
		xorInPlace(plain, eff, 0)
		data = append(data, plain...)
		off += uint64(len(plain))
	}
	hdr := make([]byte, 16)
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(names)))
	binary.LittleEndian.PutUint32(hdr[8:12], 16)
	binary.LittleEndian.PutUint32(hdr[12:16], 0x10)
	blob := append(hdr, table...)
	blob = append(blob, data...)
	if err := os.WriteFile(path, blob, 0o644); err != nil {
		t.Fatal(err)
	}
}
func sortStrings(s []string) {
	for i := 0; i < len(s); i++ {
		for j := i + 1; j < len(s); j++ {
			if s[j] < s[i] {
				s[i], s[j] = s[j], s[i]
			}
		}
	}
}

func TestReadWardrobeTableUsesPESectionForNeutralCandidateFilename(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "module-layout.bin")
	const peOff = 0x80
	const sectionRaw = 0x200
	const count = 122
	blob := make([]byte, sectionRaw+(count+1)*rosterRecordSize)
	binary.LittleEndian.PutUint32(blob[0x3c:0x40], peOff)
	binary.LittleEndian.PutUint16(blob[peOff+6:peOff+8], 1)
	binary.LittleEndian.PutUint16(blob[peOff+20:peOff+22], 0)
	sect := peOff + 24
	copy(blob[sect:sect+8], []byte(".b1cos"))
	binary.LittleEndian.PutUint32(blob[sect+20:sect+24], sectionRaw)
	for i := 0; i < count; i++ {
		o := sectionRaw + i*rosterRecordSize
		binary.LittleEndian.PutUint32(blob[o:o+4], uint32(rosterStrLo+(i%100)))
		binary.LittleEndian.PutUint32(blob[o+4:o+8], uint32(i%15))
	}
	if err := os.WriteFile(path, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	recs, err := readWardrobeTable(path, targetRosterOffset)
	if err != nil {
		t.Fatal(err)
	}
	if len(recs) != count {
		t.Fatalf("read %d records, expected %d", len(recs), count)
	}
}

func TestA18ToA22SurgicalTranscodeAndVerify(t *testing.T) {
	dir := t.TempDir()
	a18 := filepath.Join(dir, "src.pak")
	src := writeA18Fixture(t, a18, map[string][]byte{`\data\x64\character\pc00\pc00_dlc_bkn.g1t`: bytes.Repeat([]byte("abc123"), 1000)})
	defer src.Close()
	a22 := filepath.Join(dir, "dst.pak")
	writeA22Fixture(t, a22, map[string][]byte{`\data\b1\x64\character\pc00\pc00_scl.g1t`: []byte("stock")})
	e := src.Entries[0]
	name := `\data\b1\x64\character\pc00\pc00_dlc_bkn.g1t`
	s := CrossFormatEntry{src, e}
	want, err := s.PlainSHA256()
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "out.pak")
	if _, err := RewriteA22(a22, out, ArchiveEdits{Additions: map[string]ArchiveInput{name: s}}, nil); err != nil {
		t.Fatal(err)
	}
	vr, err := AuditA22Rewrite(a22, out, map[string]string{name: want}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(vr.Problems) != 0 || vr.Changed != 1 || vr.Unchanged != 1 {
		t.Fatalf("bad verify: %+v", vr)
	}
	p, err := OpenA22(out)
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	gotE, ok := p.Find(name)
	if !ok {
		t.Fatal("added entry missing")
	}
	got, err := p.Read(gotE)
	if err != nil {
		t.Fatal(err)
	}
	srcPlain, err := src.Read(e)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, srcPlain) {
		t.Fatal("transcoded plaintext mismatch")
	}
}

func TestPatchStringsOnlyBlankRows(t *testing.T) {
	blob := []byte("<str String_No=\"393339\" Text=\"-\"/>\r\n<str String_No=\"393340\" Text=\"Keep\"/>\r\n")
	out, n := patchStrings(blob, map[int][]byte{393339: []byte("Bikini"), 393340: []byte("Wrong")}, map[int]bool{393339: true, 393340: true})
	if n != 1 {
		t.Fatalf("changed %d", n)
	}
	if !bytes.Contains(out, []byte(`Text="Bikini"`)) || !bytes.Contains(out, []byte(`Text="Keep"`)) {
		t.Fatalf("unexpected output %s", out)
	}
}

func TestRelocationExactFootprintOnSurveyedSites(t *testing.T) {
	d := make([]byte, 0x2dc20)
	sites := map[int]uint32{0x2bdf9: 0x400, 0x2d3d1: 0x2a0, 0x2d3ca: 0xe8, 0x2d42e: 0xec, 0x2db94: 0xec, 0x2dbef: 0xec}
	for o, v := range sites {
		binary.LittleEndian.PutUint32(d[o:o+4], v)
	}
	old := []byte{0x48, 0x8d, 0x04, 0x40, 0x48, 0x8d, 0x40, 0x3a, 0x48, 0x8d, 0x04, 0x86}
	copy(d[0x2d023:], old)
	if err := patchRelocatedCostumeArray(d, 122); err != nil {
		t.Fatal(err)
	}
	if got := binary.LittleEndian.Uint32(d[0x2bdf9:]); got != 0xa00 {
		t.Fatalf("alloc=0x%x", got)
	}
	if got := binary.LittleEndian.Uint32(d[0x2d3d1:]); got != 122*12 {
		t.Fatalf("end=%d", got)
	}
	if got := binary.LittleEndian.Uint32(d[0x2d3ca:]); got != 0x400 {
		t.Fatalf("base=0x%x", got)
	}
}

func TestSaveTreeResyncsAcrossBareCount(t *testing.T) {
	leaf := func(name string, payload []byte) []byte {
		size := 4 + len(name) + 1 + len(payload)
		b := make([]byte, size)
		binary.LittleEndian.PutUint32(b[:4], uint32(size))
		copy(b[4:], name)
		b[4+len(name)] = 0
		copy(b[5+len(name):], payload)
		return b
	}
	eventPayload := make([]byte, 4)
	binary.LittleEndian.PutUint32(eventPayload, 604)
	child := leaf("eventFlag", eventPayload)
	containerPayload := append([]byte{1, 0, 0, 0}, child...)
	container := leaf("event", containerPayload)
	b := make([]byte, 0x20)
	copy(b, saveMagic)
	b = append(b, container...)
	nodes, err := parseSaveTree(b)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, n := range nodes {
		if n.Path == "/event/eventFlag" {
			found = true
		}
	}
	if !found {
		t.Fatalf("eventFlag not found: %+v", nodes)
	}
}

func TestA22NoOpPatchIsByteIdentical(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.pak")
	writeA22Fixture(t, src, map[string][]byte{
		`\data\b1\x64\character\pc00\pc00_scl.g1t`: []byte("stock-a"),
		`\saves\b1\chara\charabase.xml`:            []byte("stock-b"),
	})
	before, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "out.pak")
	stats, err := RewriteA22(src, out, ArchiveEdits{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatal("no-op surgical rebuild changed archive bytes")
	}
	if stats.Replaced != 0 || stats.Added != 0 || stats.EntriesBefore != stats.EntriesAfter {
		t.Fatalf("unexpected no-op stats: %+v", stats)
	}
}

func TestExtraCostumeBoundsExactOnePlusSeventeen(t *testing.T) {
	d := make([]byte, 0x320000)
	// Standalone model-load guard.
	copy(d[0x2b224-6:0x2b224], []byte{0x83, 0xbe, 0x48, 0x01, 0x00, 0x00})
	d[0x2b224] = 0x37
	// Seventeen callers of the field/party getter, each followed by cmp eax,56 + Jcc.
	const getter = 0x2f5f0
	for n := 0; n < 17; n++ {
		i := 0x10000 + n*0x40
		d[i] = 0xe8
		binary.LittleEndian.PutUint32(d[i+1:i+5], uint32(int32(getter-(i+5))))
		copy(d[i+5:i+9], []byte{0x83, 0xf8, 0x38, 0x72})
	}
	n, err := patchExtraCostumeBounds(d, 122)
	if err != nil {
		t.Fatal(err)
	}
	if n != 18 {
		t.Fatalf("patched %d extra bounds, expected 18", n)
	}
	if d[0x2b224] != 121 {
		t.Fatalf("model guard = %d, expected 121", d[0x2b224])
	}
	for x := 0; x < 17; x++ {
		i := 0x10000 + x*0x40
		if d[i+7] != 121 {
			t.Fatalf("field gate %d = %d, expected 121", x, d[i+7])
		}
	}
}

func TestPatchCharacterCatalogRestoresOnlyImportableRows(t *testing.T) {
	sourceLine := []byte(`<chara BaseTag="PC00_BKN" Model="pc00_bkn" defaultTexture="pc00_bkn_a" ActionCharaBaseTag="PC00_BASE" Extra="keep"/>`)
	targetLine := []byte(`<chara BaseTag="PC00_BKN" Model="pc00_scl" defaultTexture="pc00_scl_a" ActionCharaBaseTag="WRONG" Motion1="bad" Facial="bad" Extra="target"/>`)
	otherLine := []byte(`<chara BaseTag="PC00_OTHER" Model="unchanged" defaultTexture="unchanged"/>`)
	cs := &WardrobePlan{
		SourceCharacterCatalog: parseCharacterCatalogBytes(append(sourceLine, '\n')),
		TargetCharacterCatalog: parseCharacterCatalogBytes(append(append([]byte(nil), targetLine...), '\n')),
		Importable:             []WardrobeEntryPlan{{Tags: [3]string{"PC00_BKN", "", ""}, Importable: true}},
	}
	input := append(append(append([]byte(nil), targetLine...), []byte("\r\n")...), otherLine...)
	out, changed, err := patchCharacterCatalog(input, cs)
	if err != nil {
		t.Fatal(err)
	}
	if changed != 1 {
		t.Fatalf("changed rows=%d, expected 1", changed)
	}
	if !bytes.Contains(out, []byte(`Model="pc00_bkn"`)) || !bytes.Contains(out, []byte(`defaultTexture="pc00_bkn_a"`)) || !bytes.Contains(out, []byte(`ActionCharaBaseTag="PC00_BASE"`)) {
		t.Fatalf("expected reconstructed attributes missing: %s", out)
	}
	if bytes.Contains(out, []byte(`Motion1="bad"`)) || bytes.Contains(out, []byte(`Facial="bad"`)) {
		t.Fatalf("source-absent attributes were not removed: %s", out)
	}
	if !bytes.Contains(out, []byte(`Extra="target"`)) || !bytes.Contains(out, otherLine) {
		t.Fatalf("Quartet-only/unrelated data was not preserved: %s", out)
	}
}

func TestLocateSourceInstallFromSteamManifest(t *testing.T) {
	root := t.TempDir()
	library := filepath.Join(root, "LibraryB")
	if err := os.MkdirAll(filepath.Join(root, "steamapps"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(library, "steamapps", "common", "BR2017", "Data", "saves_en", "chara"), 0o755); err != nil {
		t.Fatal(err)
	}
	vdf := "\"libraryfolders\"\n{\n  \"1\"\n  {\n    \"path\" \"" + strings.ReplaceAll(library, `\`, `\\`) + "\"\n  }\n}\n"
	if err := os.WriteFile(filepath.Join(root, "steamapps", "libraryfolders.vdf"), []byte(vdf), 0o644); err != nil {
		t.Fatal(err)
	}
	manifest := "\"AppState\"\n{\n \"appid\" \"658260\"\n \"installdir\" \"BR2017\"\n}\n"
	if err := os.WriteFile(filepath.Join(library, "steamapps", "appmanifest_658260.acf"), []byte(manifest), 0o644); err != nil {
		t.Fatal(err)
	}
	game := filepath.Join(library, "steamapps", "common", "BR2017")
	for _, rel := range []string{"BLUE_REFLECTION.exe", "Data/PACK00_02.PAK", "Data/PACK00_03.PAK", "Data/PACK01.PAK", "Data/saves_en/chara/charabase.xml"} {
		path := filepath.Join(game, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte{1}, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	found, err := LocateSourceInstall(SourceLocator{SteamRoot: root})
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Clean(found.Root) != filepath.Clean(game) || found.Origin != "steam_manifest" {
		t.Fatalf("unexpected location: %+v", found)
	}
}

func TestLocateSourceInstallLooseFolder(t *testing.T) {
	game := t.TempDir()
	for _, rel := range []string{"BLUE_REFLECTION.exe", "Data/PACK00_02.PAK", "Data/PACK00_03.PAK", "Data/PACK01.PAK", "Data/saves_en/chara/charabase.xml"} {
		path := filepath.Join(game, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte{1}, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	found, err := LocateSourceInstall(SourceLocator{LooseRoot: game})
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Clean(found.Root) != filepath.Clean(game) || found.Origin != "explicit_game_folder" {
		t.Fatalf("unexpected location: %+v", found)
	}
}

func TestSourceCharacterCatalogFromA18WhenLooseFileIsAbsent(t *testing.T) {
	game := t.TempDir()
	data := filepath.Join(game, "DATA")
	if err := os.MkdirAll(data, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, rel := range []string{"BLUE_REFLECTION.exe", "DATA/PACK00_02.PAK", "DATA/PACK00_03.PAK", "DATA/PACK01.PAK"} {
		path := filepath.Join(game, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte{1}, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	catalogBlob := []byte("<root>\r\n<chara BaseTag=\"PC00_SCL\" Model=\"character/pc00_scl\" defaultTexture=\"pc00_scl\"/>\r\n</root>\r\n")
	fixture := writeA18Fixture(t, filepath.Join(data, "PACK02_1.PAK"), map[string][]byte{`\saves_en\chara\charabase.xml`: catalogBlob})
	fixture.Close()

	found, err := LocateSourceInstall(SourceLocator{LooseRoot: game})
	if err != nil {
		t.Fatal(err)
	}
	cat, loc, err := readSourceCharacterCatalog(found.Root)
	if err != nil {
		t.Fatal(err)
	}
	if len(cat.Order) != 1 || cat.Order[0] != "PC00_SCL" {
		t.Fatalf("unexpected catalog: %+v", cat.Order)
	}
	if loc.Kind != "a18_member" || !strings.EqualFold(filepath.Base(loc.Path), "PACK02_1.PAK") || !strings.EqualFold(loc.Member, `\saves_en\chara\charabase.xml`) {
		t.Fatalf("unexpected catalog location: %+v", loc)
	}
}

func TestLocateSourceInstallLooseFolderUppercaseDATA(t *testing.T) {
	game := t.TempDir()
	for _, rel := range []string{"BLUE_REFLECTION.exe", "DATA/PACK00_02.PAK", "DATA/PACK00_03.PAK", "DATA/PACK01.PAK", "DATA/saves_en/chara/charabase.xml"} {
		path := filepath.Join(game, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte{1}, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	found, err := LocateSourceInstall(SourceLocator{LooseRoot: game})
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Clean(found.Root) != filepath.Clean(game) || found.Origin != "explicit_game_folder" {
		t.Fatalf("unexpected location: %+v", found)
	}
	sourceFiles, _ := ResolveContentFiles(found.Root, t.TempDir())
	if got := filepath.Base(filepath.Dir(sourceFiles["pack00_02"])); got != "DATA" {
		t.Fatalf("expected resolved DATA directory, got %q (%s)", got, sourceFiles["pack00_02"])
	}
}

func TestA18SurgicalRewritePreservesUnchangedMembers(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.pak")
	p := writeA18Fixture(t, src, map[string][]byte{`\event\event_en\a.ebm`: []byte("aaa"), `\event\event_en\b.ebm`: []byte("bbb")})
	_ = p.Close()
	out := filepath.Join(dir, "out.pak")
	repl := map[string]ArchiveInput{`\event\event_en\a.ebm`: MemoryEntry{Data: []byte("translated")}}
	if _, err := RewriteA18(src, out, ArchiveEdits{Replacements: repl}, nil); err != nil {
		t.Fatal(err)
	}
	audit, err := AuditA18Rewrite(src, out, nil, repl, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(audit.Problems) != 0 {
		t.Fatalf("audit problems: %v", audit.Problems)
	}
	if audit.Changed != 1 || audit.Unchanged != 1 {
		t.Fatalf("audit=%+v", audit)
	}
	opened, err := OpenA18(out)
	if err != nil {
		t.Fatal(err)
	}
	defer opened.Close()
	entry, ok := opened.Find(`\event\event_en\a.ebm`)
	if !ok {
		t.Fatal("replacement missing")
	}
	blob, err := opened.Read(entry)
	if err != nil {
		t.Fatal(err)
	}
	if string(blob) != "translated" {
		t.Fatalf("replacement=%q", blob)
	}
}
