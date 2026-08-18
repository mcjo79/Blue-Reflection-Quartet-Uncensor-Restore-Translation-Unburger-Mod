package br1rebuild

import (
	"archive/zip"
	"compress/flate"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/workspace"
)

const (
	SourceAssetsCapability          = "br1_legacy_source_assets_v2"
	SourceAssetsFormatVersion       = 2
	legacySourceAssetsCapability    = "br1_legacy_source_assets_v1"
	legacySourceAssetsFormatVersion = 1
	SourceAnchorsCapability         = "br1_legacy_clean_source_anchors_v1"
	SourceAnchorsFormatVersion      = 1
	expectedSourceAnchorMembers     = 1682
	sourceAssetsManifestName        = "MANIFEST.json"
)

type SourceAssetMember struct {
	Group       string `json:"group"`
	ArchivePath string `json:"archive_path"`
	MemberPath  string `json:"member_path"`
	Size        int64  `json:"size"`
	SHA256      string `json:"sha256"`
}

type SourceAssetImageFile struct {
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type SupplementalSourceAssetManifest struct {
	Capability        string              `json:"capability"`
	Root              string              `json:"root"`
	SourceFingerprint string              `json:"source_fingerprint"`
	SourceMembers     []SourceAssetMember `json:"source_members"`
}

type SourceAssetManifest struct {
	Type                     string                            `json:"type"`
	FormatVersion            int                               `json:"format_version"`
	Capability               string                            `json:"capability"`
	ReconstructionCapability string                            `json:"reconstruction_capability"`
	CleanAnchorCapability    string                            `json:"clean_anchor_capability"`
	CleanAnchorFingerprint   string                            `json:"clean_anchor_fingerprint"`
	SourceFingerprint        string                            `json:"source_fingerprint"`
	SourceMembers            []SourceAssetMember               `json:"source_members"`
	ImageFiles               []SourceAssetImageFile            `json:"image_files"`
	SupplementalSources      []SupplementalSourceAssetManifest `json:"supplemental_sources,omitempty"`
}

type SourceAnchorManifest struct {
	Type              string              `json:"type"`
	FormatVersion     int                 `json:"format_version"`
	Capability        string              `json:"capability"`
	SourceFingerprint string              `json:"source_fingerprint"`
	SourceMembers     []SourceAssetMember `json:"source_members"`
}

type sourceAssetBuildResult struct {
	Manifest SourceAssetManifest
	Path     string
	SHA256   string
	Size     int64
}

func BuildSourceAssetBundle(sourceRoot, outputPath, anchorPath string) (SourceAssetManifest, error) {
	return BuildSourceAssetBundleWithProgress(sourceRoot, outputPath, anchorPath, nil)
}

func BuildSourceAssetBundleWithProgress(sourceRoot, outputPath, anchorPath string, progress BuildProgressFunc) (SourceAssetManifest, error) {
	stage, err := workspace.MkdirTemp("unburger-br1-assets-")
	if err != nil {
		return SourceAssetManifest{}, err
	}
	defer os.RemoveAll(stage)
	if progress != nil {
		progress(BuildProgress{Phase: "source_bundle_build_br1", CurrentFile: "BLUE REFLECTION (2017) reduced DLC source"})
	}
	manifest, err := buildBR1SourceAssetStage(sourceRoot, stage, anchorPath)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	if err := packageSourceAssetImageV3WithProgress(stage, outputPath, manifest, progress); err != nil {
		return SourceAssetManifest{}, err
	}
	return manifest, nil
}

func buildBR1SourceAssetStage(sourceRoot, stage, anchorPath string) (SourceAssetManifest, error) {
	anchors, err := ReadSourceAnchorManifest(anchorPath)
	if err != nil {
		return SourceAssetManifest{}, fmt.Errorf("read clean-source anchors: %w", err)
	}
	if err := validateSourceAnchorManifest(anchors); err != nil {
		return SourceAssetManifest{}, fmt.Errorf("validate clean-source anchors: %w", err)
	}
	location, err := LocateSourceInstall(SourceLocator{LooseRoot: sourceRoot})
	if err != nil {
		return SourceAssetManifest{}, err
	}
	imageRoot := filepath.Join(stage, "source")
	dataRoot := filepath.Join(imageRoot, "DATA")
	if err := os.MkdirAll(dataRoot, 0o755); err != nil {
		return SourceAssetManifest{}, err
	}

	sourceData, err := sourceDataDirectory(location.Root)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	members := []SourceAssetMember{}

	roster, err := readWardrobeTable(casePath(location.Root, "BLUE_REFLECTION.exe"), sourceRosterOffset)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	if len(roster) != 120 {
		return SourceAssetManifest{}, fmt.Errorf("source wardrobe table contains %d records, expected 120", len(roster))
	}
	rosterBlob := encodeWardrobeRecords(roster)
	exePath := filepath.Join(imageRoot, "BLUE_REFLECTION.exe")
	if err := writeRosterImage(exePath, rosterBlob); err != nil {
		return SourceAssetManifest{}, err
	}
	members = append(members, SourceAssetMember{Group: "wardrobe_metadata", ArchivePath: "BLUE_REFLECTION.exe", MemberPath: "wardrobe_table", Size: int64(len(rosterBlob)), SHA256: shaBytes(rosterBlob)})

	pack00_02 := casePath(sourceData, "PACK00_02.PAK")
	if err := buildReducedA18(pack00_02, filepath.Join(dataRoot, "PACK00_02.PAK"), func(name string) bool {
		return isWardrobeAssetPath(name)
	}, "wardrobe_asset", &members); err != nil {
		return SourceAssetManifest{}, err
	}
	count, bytes, err := MeasureWardrobeArchive(filepath.Join(dataRoot, "PACK00_02.PAK"))
	if err != nil || count != expectedWardrobeSourceFiles || bytes != expectedWardrobeSourceBytes {
		return SourceAssetManifest{}, fmt.Errorf("reduced wardrobe source mismatch: %d files/%d bytes; expected %d/%d: %v", count, bytes, expectedWardrobeSourceFiles, expectedWardrobeSourceBytes, err)
	}

	pack00_03 := casePath(sourceData, "PACK00_03.PAK")
	needle := `\field\` + islandFieldKey + `\`
	if err := buildReducedA18(pack00_03, filepath.Join(dataRoot, "PACK00_03.PAK"), func(name string) bool {
		return strings.Contains(strings.ToLower(name), needle)
	}, "island_geometry", &members); err != nil {
		return SourceAssetManifest{}, err
	}

	pack01 := casePath(sourceData, "PACK01.PAK")
	if err := buildReducedA18(pack01, filepath.Join(dataRoot, "PACK01.PAK"), func(name string) bool {
		lower := strings.ToLower(name)
		if !strings.HasSuffix(lower, ".ebm") {
			return false
		}
		for _, locale := range []string{"event_en", "event_jp", "event_ch"} {
			marker := `\` + locale + `\`
			position := strings.Index(lower, marker)
			if position < 0 {
				continue
			}
			remainder := lower[position+len(marker):]
			folder := strings.SplitN(remainder, `\`, 2)[0]
			return islandEventFolder(folder)
		}
		return false
	}, "island_event", &members); err != nil {
		return SourceAssetManifest{}, err
	}
	counts, err := inspectIslandEventSources(filepath.Join(dataRoot, "PACK01.PAK"))
	if err != nil {
		return SourceAssetManifest{}, err
	}
	for _, locale := range []string{"event_en", "event_jp", "event_ch"} {
		if counts[locale] < 470 {
			return SourceAssetManifest{}, fmt.Errorf("reduced Island event inventory %s=%d, expected at least 470", locale, counts[locale])
		}
	}

	catalogBlob, err := sourceCharacterCatalogBlob(location.Root)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	localeSpecs := []struct {
		archive string
		folder  string
		group   string
	}{
		{"PACK02_1.PAK", "saves_en", "strings_en"},
		{"PACK02_2.PAK", "saves_ch", "strings_tc"},
		{"PACK02_3.PAK", "saves_jp", "strings_jp"},
	}
	for _, spec := range localeSpecs {
		sourceArchive := casePath(sourceData, spec.archive)
		p, openErr := OpenA18(sourceArchive)
		if openErr != nil {
			return SourceAssetManifest{}, openErr
		}
		entries := map[string]ArchiveInput{}
		if spec.archive == "PACK02_1.PAK" {
			entries[`\saves_en\chara\charabase.xml`] = MemoryEntry{Data: catalogBlob}
			members = append(members, SourceAssetMember{Group: "character_catalog", ArchivePath: "DATA/" + spec.archive, MemberPath: `\saves_en\chara\charabase.xml`, Size: int64(len(catalogBlob)), SHA256: shaBytes(catalogBlob)})
		}
		wanted := `\` + spec.folder + `\text\strcombineall.xml`
		e, ok := p.Find(wanted)
		if !ok {
			p.Close()
			return SourceAssetManifest{}, fmt.Errorf("%s missing %s", sourceArchive, wanted)
		}
		entry := CrossFormatEntry{Pak: p, Entry: e}
		entries[wanted] = entry
		digest, digestErr := entry.PlainSHA256()
		if digestErr != nil {
			p.Close()
			return SourceAssetManifest{}, digestErr
		}
		members = append(members, SourceAssetMember{Group: spec.group, ArchivePath: "DATA/" + spec.archive, MemberPath: wanted, Size: int64(e.Size), SHA256: digest})
		dst := filepath.Join(dataRoot, spec.archive)
		if err := writePlainA18(dst, entries); err != nil {
			p.Close()
			return SourceAssetManifest{}, err
		}
		p.Close()
	}

	imageFiles, err := inventoryImageFiles(stage)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	sort.Slice(members, func(i, j int) bool {
		ki := members[i].ArchivePath + "\x00" + members[i].MemberPath
		kj := members[j].ArchivePath + "\x00" + members[j].MemberPath
		return ki < kj
	})
	manifest := SourceAssetManifest{
		Type:                     "unburger_br1_dlc_source_assets",
		FormatVersion:            SourceAssetsFormatVersion,
		Capability:               SourceAssetsCapability,
		ReconstructionCapability: "br1_legacy_content_rebuild_v1",
		CleanAnchorCapability:    anchors.Capability,
		CleanAnchorFingerprint:   anchors.SourceFingerprint,
		SourceMembers:            members,
		ImageFiles:               imageFiles,
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(members)
	if err := verifySourceMembersAgainstAnchors(manifest.SourceMembers, anchors); err != nil {
		return SourceAssetManifest{}, err
	}
	return manifest, nil
}

func sourceCharacterCatalogBlob(sourceRoot string) ([]byte, error) {
	// The developer .unburger-assets builder must be provenance-stable.  A loose
	// DATA/saves_en/chara/charabase.xml can legitimately exist in a modified
	// working installation, but it must never override the canonical retail
	// member when capturing the reusable source bundle.
	dataRoot, err := sourceDataDirectory(sourceRoot)
	if err != nil {
		return nil, err
	}
	archivePath := casePath(dataRoot, "PACK02_1.PAK")
	p, err := OpenA18(archivePath)
	if err != nil {
		return nil, err
	}
	defer p.Close()
	const wanted = `\saves_en\chara\charabase.xml`
	e, ok := p.Find(wanted)
	if !ok {
		return nil, fmt.Errorf("canonical source catalog member missing: %s#%s", archivePath, wanted)
	}
	return p.Read(e)
}

func encodeWardrobeRecords(records []WardrobeRecord) []byte {
	out := make([]byte, 0, len(records)*rosterRecordSize)
	var scratch [4]byte
	for _, record := range records {
		for _, value := range record {
			binary.LittleEndian.PutUint32(scratch[:], uint32(value))
			out = append(out, scratch[:]...)
		}
	}
	return out
}

func writeRosterImage(path string, roster []byte) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	if err := f.Truncate(int64(sourceRosterOffset + len(roster) + 4)); err != nil {
		return err
	}
	_, err = f.WriteAt(roster, int64(sourceRosterOffset))
	return err
}

func buildReducedA18(sourcePath, outputPath string, keep func(string) bool, group string, members *[]SourceAssetMember) error {
	p, err := OpenA18(sourcePath)
	if err != nil {
		return err
	}
	defer p.Close()
	selected := map[string]ArchiveInput{}
	for _, e := range p.Entries {
		if !keep(e.Name) {
			continue
		}
		entry := CrossFormatEntry{Pak: p, Entry: e}
		digest, err := entry.PlainSHA256()
		if err != nil {
			return err
		}
		selected[e.Name] = entry
		*members = append(*members, SourceAssetMember{Group: group, ArchivePath: "DATA/" + filepath.Base(outputPath), MemberPath: e.Name, Size: int64(e.Size), SHA256: digest})
	}
	if len(selected) == 0 {
		return fmt.Errorf("no source members selected from %s", sourcePath)
	}
	return writePlainA18(outputPath, selected)
}

func writePlainA18(path string, entries map[string]ArchiveInput) error {
	if len(entries) == 0 {
		return fmt.Errorf("cannot write empty A18 source image")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for name := range entries {
		if !strings.HasPrefix(name, `\`) || len(name) >= a18NameSize {
			return fmt.Errorf("invalid A18 member name %q", name)
		}
		names = append(names, name)
	}
	sort.Slice(names, func(i, j int) bool { return strings.ToLower(names[i]) < strings.ToLower(names[j]) })
	out, err := os.Create(path)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(path)
		}
	}()
	var hdr [pakHeaderSize]byte
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(names)))
	binary.LittleEndian.PutUint32(hdr[8:12], pakHeaderSize)
	if _, err := out.Write(hdr[:]); err != nil {
		return err
	}
	var offset uint64
	for _, name := range names {
		raw := make([]byte, a18EntrySize)
		copy(raw[:a18NameSize], []byte(name))
		binary.LittleEndian.PutUint32(raw[128:132], uint32(entries[name].Size()))
		binary.LittleEndian.PutUint64(raw[152:160], offset)
		if _, err := out.Write(raw); err != nil {
			return err
		}
		offset += uint64(entries[name].Size())
	}
	for _, name := range names {
		if err := entries[name].WriteEncrypted(out, []byte{0}); err != nil {
			return err
		}
	}
	if err := out.Sync(); err != nil {
		return err
	}
	ok = true
	return out.Close()
}

func inventoryImageFiles(stage string) ([]SourceAssetImageFile, error) {
	var out []SourceAssetImageFile
	err := filepath.WalkDir(filepath.Join(stage, "source"), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(stage, path)
		if err != nil {
			return err
		}
		hash, size, err := hashPath(path)
		if err != nil {
			return err
		}
		out = append(out, SourceAssetImageFile{Path: filepath.ToSlash(rel), Size: size, SHA256: hash})
		return nil
	})
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out, err
}

func sourceAssetFingerprint(members []SourceAssetMember) string {
	ordered := append([]SourceAssetMember(nil), members...)
	sort.Slice(ordered, func(i, j int) bool { return sourceMemberKey(ordered[i]) < sourceMemberKey(ordered[j]) })
	h := sha256.New()
	for _, item := range ordered {
		fmt.Fprintf(h, "%s\x00%s\x00%d\x00%s\n", item.ArchivePath, item.MemberPath, item.Size, item.SHA256)
	}
	return hex.EncodeToString(h.Sum(nil))
}

func sourceMemberKey(item SourceAssetMember) string {
	return strings.ToLower(filepath.ToSlash(item.ArchivePath)) + "\x00" + strings.ToLower(strings.ReplaceAll(item.MemberPath, `/`, `\`))
}

func normalizeSourceMembers(members []SourceAssetMember) ([]SourceAssetMember, error) {
	out := append([]SourceAssetMember(nil), members...)
	sort.Slice(out, func(i, j int) bool { return sourceMemberKey(out[i]) < sourceMemberKey(out[j]) })
	seen := map[string]bool{}
	for _, item := range out {
		key := sourceMemberKey(item)
		if item.ArchivePath == "" || item.MemberPath == "" || item.Group == "" || item.Size < 0 || len(item.SHA256) != 64 {
			return nil, fmt.Errorf("invalid source member anchor: %s#%s", item.ArchivePath, item.MemberPath)
		}
		if _, err := hex.DecodeString(item.SHA256); err != nil {
			return nil, fmt.Errorf("invalid source member SHA-256: %s#%s", item.ArchivePath, item.MemberPath)
		}
		if seen[key] {
			return nil, fmt.Errorf("duplicate source member anchor: %s#%s", item.ArchivePath, item.MemberPath)
		}
		seen[key] = true
	}
	return out, nil
}

func ReadSourceAnchorManifest(path string) (SourceAnchorManifest, error) {
	if strings.TrimSpace(path) == "" {
		return SourceAnchorManifest{}, fmt.Errorf("clean-source anchor file is required")
	}
	blob, err := os.ReadFile(path)
	if err != nil {
		return SourceAnchorManifest{}, err
	}
	var manifest SourceAnchorManifest
	if err := json.Unmarshal(blob, &manifest); err != nil {
		return SourceAnchorManifest{}, err
	}
	return manifest, nil
}

func validateSourceAnchorManifest(manifest SourceAnchorManifest) error {
	if manifest.Type != "unburger_br1_dlc_clean_source_anchors" || manifest.FormatVersion != SourceAnchorsFormatVersion {
		return fmt.Errorf("unsupported clean-source anchor manifest type/version")
	}
	if manifest.Capability != SourceAnchorsCapability {
		return fmt.Errorf("unsupported clean-source anchor capability")
	}
	if len(manifest.SourceMembers) == 0 {
		return fmt.Errorf("clean-source anchor set is empty")
	}
	members, err := normalizeSourceMembers(manifest.SourceMembers)
	if err != nil {
		return err
	}
	if sourceAssetFingerprint(members) != manifest.SourceFingerprint {
		return fmt.Errorf("clean-source anchor fingerprint mismatch")
	}
	return nil
}

func verifySourceMembersAgainstAnchors(actual []SourceAssetMember, anchors SourceAnchorManifest) error {
	if err := validateSourceAnchorManifest(anchors); err != nil {
		return err
	}
	got, err := normalizeSourceMembers(actual)
	if err != nil {
		return err
	}
	want, err := normalizeSourceMembers(anchors.SourceMembers)
	if err != nil {
		return err
	}
	if len(got) != len(want) {
		return fmt.Errorf("clean-source member coverage mismatch: got %d, expected %d", len(got), len(want))
	}
	for i := range want {
		if sourceMemberKey(got[i]) != sourceMemberKey(want[i]) {
			return fmt.Errorf("clean-source member identity mismatch at %d: got %s#%s expected %s#%s", i, got[i].ArchivePath, got[i].MemberPath, want[i].ArchivePath, want[i].MemberPath)
		}
		if got[i].Group != want[i].Group || got[i].Size != want[i].Size || !strings.EqualFold(got[i].SHA256, want[i].SHA256) {
			return fmt.Errorf("clean-source member mismatch: %s#%s", got[i].ArchivePath, got[i].MemberPath)
		}
	}
	return nil
}

func WriteSourceAnchorProposal(sourceRoot, outputPath string) (SourceAnchorManifest, error) {
	members, err := inventorySourceAssetMembers(sourceRoot)
	if err != nil {
		return SourceAnchorManifest{}, err
	}
	members, err = normalizeSourceMembers(members)
	if err != nil {
		return SourceAnchorManifest{}, err
	}
	if len(members) != expectedSourceAnchorMembers {
		return SourceAnchorManifest{}, fmt.Errorf("source anchor proposal contains %d members, expected %d", len(members), expectedSourceAnchorMembers)
	}
	manifest := SourceAnchorManifest{
		Type:              "unburger_br1_dlc_clean_source_anchors",
		FormatVersion:     SourceAnchorsFormatVersion,
		Capability:        SourceAnchorsCapability,
		SourceMembers:     members,
		SourceFingerprint: sourceAssetFingerprint(members),
	}
	if err := validateSourceAnchorManifest(manifest); err != nil {
		return SourceAnchorManifest{}, err
	}
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return SourceAnchorManifest{}, err
	}
	blob, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return SourceAnchorManifest{}, err
	}
	blob = append(blob, '\n')
	tmp := outputPath + ".tmp"
	if err := os.WriteFile(tmp, blob, 0o644); err != nil {
		return SourceAnchorManifest{}, err
	}
	if err := os.Rename(tmp, outputPath); err != nil {
		_ = os.Remove(tmp)
		return SourceAnchorManifest{}, err
	}
	return manifest, nil
}

func inventorySourceAssetMembers(sourceRoot string) ([]SourceAssetMember, error) {
	location, err := LocateSourceInstall(SourceLocator{LooseRoot: sourceRoot})
	if err != nil {
		return nil, err
	}
	sourceData, err := sourceDataDirectory(location.Root)
	if err != nil {
		return nil, err
	}
	members := []SourceAssetMember{}

	roster, err := readWardrobeTable(casePath(location.Root, "BLUE_REFLECTION.exe"), sourceRosterOffset)
	if err != nil {
		return nil, err
	}
	if len(roster) != 120 {
		return nil, fmt.Errorf("source wardrobe table contains %d records, expected 120", len(roster))
	}
	rosterBlob := encodeWardrobeRecords(roster)
	members = append(members, SourceAssetMember{Group: "wardrobe_metadata", ArchivePath: "BLUE_REFLECTION.exe", MemberPath: "wardrobe_table", Size: int64(len(rosterBlob)), SHA256: shaBytes(rosterBlob)})

	appendArchive := func(archiveName, group string, keep func(string) bool) error {
		path := casePath(sourceData, archiveName)
		p, err := OpenA18(path)
		if err != nil {
			return err
		}
		defer p.Close()
		count := 0
		var bytes int64
		for _, e := range p.Entries {
			if !keep(e.Name) {
				continue
			}
			entry := CrossFormatEntry{Pak: p, Entry: e}
			digest, err := entry.PlainSHA256()
			if err != nil {
				return err
			}
			members = append(members, SourceAssetMember{Group: group, ArchivePath: "DATA/" + archiveName, MemberPath: e.Name, Size: int64(e.Size), SHA256: digest})
			count++
			bytes += int64(e.Size)
		}
		if count == 0 {
			return fmt.Errorf("no source members selected from %s", path)
		}
		if group == "wardrobe_asset" && (count != expectedWardrobeSourceFiles || bytes != expectedWardrobeSourceBytes) {
			return fmt.Errorf("wardrobe source inventory mismatch: %d files/%d bytes; expected %d/%d", count, bytes, expectedWardrobeSourceFiles, expectedWardrobeSourceBytes)
		}
		if group == "island_geometry" && count != 3 {
			return fmt.Errorf("Island geometry inventory=%d, expected 3", count)
		}
		if group == "island_event" && count != 1410 {
			return fmt.Errorf("Island event inventory=%d, expected 1410", count)
		}
		return nil
	}

	if err := appendArchive("PACK00_02.PAK", "wardrobe_asset", isWardrobeAssetPath); err != nil {
		return nil, err
	}
	needle := `\field\` + islandFieldKey + `\`
	if err := appendArchive("PACK00_03.PAK", "island_geometry", func(name string) bool {
		return strings.Contains(strings.ToLower(name), needle)
	}); err != nil {
		return nil, err
	}
	if err := appendArchive("PACK01.PAK", "island_event", func(name string) bool {
		lower := strings.ToLower(name)
		if !strings.HasSuffix(lower, ".ebm") {
			return false
		}
		for _, locale := range []string{"event_en", "event_jp", "event_ch"} {
			marker := `\` + locale + `\`
			position := strings.Index(lower, marker)
			if position < 0 {
				continue
			}
			remainder := lower[position+len(marker):]
			folder := strings.SplitN(remainder, `\`, 2)[0]
			return islandEventFolder(folder)
		}
		return false
	}); err != nil {
		return nil, err
	}

	catalogBlob, err := sourceCharacterCatalogBlob(location.Root)
	if err != nil {
		return nil, err
	}
	members = append(members, SourceAssetMember{Group: "character_catalog", ArchivePath: "DATA/PACK02_1.PAK", MemberPath: `\saves_en\chara\charabase.xml`, Size: int64(len(catalogBlob)), SHA256: shaBytes(catalogBlob)})

	localeSpecs := []struct {
		archive string
		folder  string
		group   string
	}{
		{"PACK02_1.PAK", "saves_en", "strings_en"},
		{"PACK02_2.PAK", "saves_ch", "strings_tc"},
		{"PACK02_3.PAK", "saves_jp", "strings_jp"},
	}
	for _, spec := range localeSpecs {
		p, err := OpenA18(casePath(sourceData, spec.archive))
		if err != nil {
			return nil, err
		}
		wanted := `\` + spec.folder + `\text\strcombineall.xml`
		e, ok := p.Find(wanted)
		if !ok {
			p.Close()
			return nil, fmt.Errorf("%s missing %s", spec.archive, wanted)
		}
		entry := CrossFormatEntry{Pak: p, Entry: e}
		digest, err := entry.PlainSHA256()
		p.Close()
		if err != nil {
			return nil, err
		}
		members = append(members, SourceAssetMember{Group: spec.group, ArchivePath: "DATA/" + spec.archive, MemberPath: wanted, Size: int64(e.Size), SHA256: digest})
	}

	return members, nil
}

func packageSourceAssetImage(stage, outputPath string, manifest SourceAssetManifest) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return err
	}
	f, err := os.Create(outputPath)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = f.Close()
		if !ok {
			_ = os.Remove(outputPath)
		}
	}()
	zw := zip.NewWriter(f)
	zw.RegisterCompressor(zip.Deflate, func(out io.Writer) (io.WriteCloser, error) {
		return flate.NewWriter(out, flate.BestSpeed)
	})
	fixed := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	manifestBytes, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	manifestBytes = append(manifestBytes, '\n')
	if err := writeZipBytes(zw, sourceAssetsManifestName, manifestBytes, fixed); err != nil {
		return err
	}
	for _, item := range manifest.ImageFiles {
		if err := writeZipFile(zw, filepath.Join(stage, filepath.FromSlash(item.Path)), item.Path, fixed); err != nil {
			return err
		}
	}
	if err := zw.Close(); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	ok = true
	return f.Close()
}

func writeZipBytes(zw *zip.Writer, name string, data []byte, mod time.Time) error {
	header := &zip.FileHeader{Name: name, Method: zip.Deflate}
	header.SetModTime(mod)
	header.SetMode(0o644)
	w, err := zw.CreateHeader(header)
	if err != nil {
		return err
	}
	_, err = w.Write(data)
	return err
}

func writeZipFile(zw *zip.Writer, path, name string, mod time.Time) error {
	in, err := os.Open(path)
	if err != nil {
		return err
	}
	defer in.Close()
	header := &zip.FileHeader{Name: filepath.ToSlash(name), Method: zip.Deflate}
	header.SetModTime(mod)
	header.SetMode(0o644)
	w, err := zw.CreateHeader(header)
	if err != nil {
		return err
	}
	_, err = io.CopyBuffer(w, in, make([]byte, 8<<20))
	return err
}

// FindCompatibleSourceAssetBundle performs a metadata-only lookup for a verified
// .unburger-assets bundle. It does not materialize the bundle. This is used by
// the public launcher to prefer a sibling developer/test source bundle before
// asking the user to locate the original BLUE REFLECTION installation.
func FindCompatibleSourceAssetBundle(raw, anchorPath string) (string, bool, error) {
	anchors, err := ReadSourceAnchorManifest(anchorPath)
	if err != nil {
		return "", false, fmt.Errorf("clean-source anchors are required for developer asset bundles: %w", err)
	}
	if err := validateSourceAnchorManifest(anchors); err != nil {
		return "", false, fmt.Errorf("clean-source anchors are invalid: %w", err)
	}
	path := strings.Trim(strings.TrimSpace(raw), `"`)
	if path == "" {
		return "", false, nil
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", false, err
	}
	st, err := os.Stat(abs)
	if os.IsNotExist(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if !st.IsDir() {
		if !strings.HasSuffix(strings.ToLower(abs), ".unburger-assets") {
			return "", false, nil
		}
		manifest, err := ReadSourceAssetManifest(abs)
		if err != nil || validateSourceAssetManifest(manifest) != nil || !sourceAssetManifestMatchesAnchors(manifest, anchors) {
			return "", false, nil
		}
		return abs, true, nil
	}
	candidates, err := compatibleAssetBundles(abs, anchors)
	if err != nil {
		return "", false, err
	}
	if len(candidates) == 0 {
		return "", false, nil
	}
	// Keep the existing deterministic filename ordering used by the explicit
	// directory locator. Current bundles are capability/version checked above.
	return candidates[len(candidates)-1], true, nil
}

func locateSourceAssetBundle(raw, anchorPath string, progress BuildProgressFunc) (SourceLocation, error) {
	anchors, err := ReadSourceAnchorManifest(anchorPath)
	if err != nil {
		return SourceLocation{}, fmt.Errorf("clean-source anchors are required for developer asset bundles: %w", err)
	}
	if err := validateSourceAnchorManifest(anchors); err != nil {
		return SourceLocation{}, fmt.Errorf("clean-source anchors are invalid: %w", err)
	}
	path := strings.Trim(strings.TrimSpace(raw), `"`)
	if path == "" {
		return SourceLocation{}, fmt.Errorf("empty assets path")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return SourceLocation{}, err
	}
	st, err := os.Stat(abs)
	if err != nil {
		return SourceLocation{}, err
	}
	bundle := abs
	if st.IsDir() {
		candidates, err := compatibleAssetBundles(abs, anchors)
		if err != nil {
			return SourceLocation{}, err
		}
		if len(candidates) == 0 {
			return SourceLocation{}, fmt.Errorf("no compatible .unburger-assets bundle found in %s", abs)
		}
		bundle = candidates[len(candidates)-1]
	} else if !strings.HasSuffix(strings.ToLower(abs), ".unburger-assets") {
		return SourceLocation{}, fmt.Errorf("assets source must be a .unburger-assets file or a folder containing one")
	}
	manifest, err := ReadSourceAssetManifest(bundle)
	if err != nil {
		return SourceLocation{}, err
	}
	if err := validateSourceAssetManifest(manifest); err != nil {
		return SourceLocation{}, err
	}
	if !sourceAssetManifestMatchesAnchors(manifest, anchors) {
		return SourceLocation{}, fmt.Errorf("source assets bundle does not match approved clean-source anchors")
	}
	root, cleanupRoot, err := materializeSourceAssetBundle(bundle, manifest, progress)
	if err != nil {
		return SourceLocation{}, err
	}
	if err := validateSourceInstall(root); err != nil {
		_ = os.RemoveAll(cleanupRoot)
		return SourceLocation{}, fmt.Errorf("materialized source bundle is invalid: %w", err)
	}
	return SourceLocation{Root: root, Origin: "asset_bundle", CleanupRoot: cleanupRoot}, nil
}

// VerifySourceAssetBundle performs the expensive, content-level verification
// used when bootstrapping a missing whole-file SHA-256 sidecar.  Unlike
// FindCompatibleSourceAssetBundle, this materializes the container, checks each
// image digest, every BR1 source member, and every supplemental source member,
// then removes the transient workspace.
func VerifySourceAssetBundle(path, anchorPath string) (SourceAssetManifest, error) {
	return VerifySourceAssetBundleWithProgress(path, anchorPath, nil)
}

func VerifySourceAssetBundleWithProgress(path, anchorPath string, progress BuildProgressFunc) (SourceAssetManifest, error) {
	anchors, err := ReadSourceAnchorManifest(anchorPath)
	if err != nil {
		return SourceAssetManifest{}, fmt.Errorf("clean-source anchors are required for source bundle verification: %w", err)
	}
	if err := validateSourceAnchorManifest(anchors); err != nil {
		return SourceAssetManifest{}, fmt.Errorf("clean-source anchors are invalid: %w", err)
	}
	abs, err := filepath.Abs(strings.Trim(strings.TrimSpace(path), `"`))
	if err != nil {
		return SourceAssetManifest{}, err
	}
	manifest, err := ReadSourceAssetManifest(abs)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	if err := validateSourceAssetManifest(manifest); err != nil {
		return SourceAssetManifest{}, err
	}
	if !sourceAssetManifestMatchesAnchors(manifest, anchors) {
		return SourceAssetManifest{}, fmt.Errorf("source assets bundle does not match approved clean-source anchors")
	}
	root, cleanupRoot, err := materializeSourceAssetBundle(abs, manifest, progress)
	if err != nil {
		return SourceAssetManifest{}, err
	}
	defer os.RemoveAll(cleanupRoot)
	if err := validateSourceInstall(root); err != nil {
		return SourceAssetManifest{}, fmt.Errorf("materialized source bundle is invalid: %w", err)
	}
	return manifest, nil
}

func compatibleAssetBundles(dir string, anchors SourceAnchorManifest) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(strings.ToLower(entry.Name()), ".unburger-assets") {
			continue
		}
		path := filepath.Join(dir, entry.Name())
		manifest, err := ReadSourceAssetManifest(path)
		if err == nil && validateSourceAssetManifest(manifest) == nil && sourceAssetManifestMatchesAnchors(manifest, anchors) {
			out = append(out, path)
		}
	}
	sort.Strings(out)
	return out, nil
}

func ReadSourceAssetManifest(path string) (SourceAssetManifest, error) {
	if modern, err := isSourceAssetV3(path); err == nil && modern {
		container, err := readSourceAssetV3Manifest(path)
		if err != nil {
			return SourceAssetManifest{}, err
		}
		return container.SourceManifest, nil
	}
	zr, err := zip.OpenReader(path)
	if err != nil {
		return SourceAssetManifest{}, fmt.Errorf("open source assets bundle: %w", err)
	}
	defer zr.Close()
	for _, item := range zr.File {
		if item.Name != sourceAssetsManifestName {
			continue
		}
		r, err := item.Open()
		if err != nil {
			return SourceAssetManifest{}, err
		}
		defer r.Close()
		var manifest SourceAssetManifest
		if err := json.NewDecoder(io.LimitReader(r, 16<<20)).Decode(&manifest); err != nil {
			return SourceAssetManifest{}, err
		}
		return manifest, nil
	}
	return SourceAssetManifest{}, fmt.Errorf("source assets bundle is missing %s", sourceAssetsManifestName)
}

func validateSourceAssetManifest(manifest SourceAssetManifest) error {
	if manifest.Type != "unburger_br1_dlc_source_assets" {
		return fmt.Errorf("unsupported source assets manifest type")
	}
	if manifest.ReconstructionCapability != "br1_legacy_content_rebuild_v1" {
		return fmt.Errorf("incompatible source assets reconstruction capability")
	}
	switch manifest.FormatVersion {
	case legacySourceAssetsFormatVersion:
		if manifest.Capability != legacySourceAssetsCapability {
			return fmt.Errorf("incompatible legacy source assets capability")
		}
	case SourceAssetsFormatVersion:
		if manifest.Capability != SourceAssetsCapability {
			return fmt.Errorf("incompatible source assets capability")
		}
		if manifest.CleanAnchorCapability != SourceAnchorsCapability || len(manifest.CleanAnchorFingerprint) != 64 {
			return fmt.Errorf("source assets bundle is not bound to a supported clean-source anchor set")
		}
		if _, err := hex.DecodeString(manifest.CleanAnchorFingerprint); err != nil {
			return fmt.Errorf("invalid clean-source anchor fingerprint")
		}
	default:
		return fmt.Errorf("unsupported source assets manifest version %d", manifest.FormatVersion)
	}
	if len(manifest.SourceMembers) == 0 || len(manifest.ImageFiles) == 0 {
		return fmt.Errorf("source assets manifest is empty")
	}
	if sourceAssetFingerprint(manifest.SourceMembers) != manifest.SourceFingerprint {
		return fmt.Errorf("source assets fingerprint mismatch")
	}
	if manifest.FormatVersion == SourceAssetsFormatVersion && !strings.EqualFold(manifest.SourceFingerprint, manifest.CleanAnchorFingerprint) {
		return fmt.Errorf("source assets fingerprint differs from clean-source anchor fingerprint")
	}
	seen := map[string]bool{}
	for _, item := range manifest.ImageFiles {
		clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(item.Path)))
		if !strings.HasPrefix(clean, "source/") || strings.Contains(clean, "../") || seen[clean] || item.Size < 0 || len(item.SHA256) != 64 {
			return fmt.Errorf("invalid source image file entry %q", item.Path)
		}
		if _, err := hex.DecodeString(item.SHA256); err != nil {
			return fmt.Errorf("invalid source image SHA-256 for %q", item.Path)
		}
		seen[clean] = true
	}
	seenSupplement := map[string]bool{}
	for _, supplement := range manifest.SupplementalSources {
		root := filepath.ToSlash(filepath.Clean(filepath.FromSlash(supplement.Root)))
		if supplement.Capability == "" || root == "." || root == "" || strings.Contains(root, "../") || strings.HasPrefix(root, "/") || seenSupplement[supplement.Capability] {
			return fmt.Errorf("invalid supplemental source capability/root")
		}
		seenSupplement[supplement.Capability] = true
		members, err := normalizeSourceMembers(supplement.SourceMembers)
		if err != nil {
			return err
		}
		if len(members) == 0 || sourceAssetFingerprint(members) != supplement.SourceFingerprint {
			return fmt.Errorf("supplemental source fingerprint mismatch for %s", supplement.Capability)
		}
	}
	return nil
}

func sourceAssetManifestMatchesAnchors(manifest SourceAssetManifest, anchors SourceAnchorManifest) bool {
	if verifySourceMembersAgainstAnchors(manifest.SourceMembers, anchors) != nil {
		return false
	}
	if !strings.EqualFold(manifest.SourceFingerprint, anchors.SourceFingerprint) {
		return false
	}
	if manifest.FormatVersion == SourceAssetsFormatVersion {
		return manifest.CleanAnchorCapability == anchors.Capability && strings.EqualFold(manifest.CleanAnchorFingerprint, anchors.SourceFingerprint)
	}
	return manifest.FormatVersion == legacySourceAssetsFormatVersion && manifest.Capability == legacySourceAssetsCapability
}

func materializeSourceAssetBundle(path string, manifest SourceAssetManifest, progress BuildProgressFunc) (string, string, error) {
	if modern, err := isSourceAssetV3(path); err == nil && modern {
		return materializeSourceAssetBundleV3(path, manifest, progress)
	}
	// One-time migration cleanup for the persistent source-image cache used by
	// older public releases. Failure to remove it must not block this run.
	if cacheBase, cacheErr := os.UserCacheDir(); cacheErr == nil && strings.TrimSpace(cacheBase) != "" {
		_ = os.RemoveAll(filepath.Join(cacheBase, "unburger-patcher", "br1-assets"))
	}
	stage, err := workspace.MkdirTemp("unburger-br1-assets-")
	if err != nil {
		return "", "", err
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.RemoveAll(stage)
		}
	}()
	root := filepath.Join(stage, "source")
	zr, err := zip.OpenReader(path)
	if err != nil {
		return "", "", err
	}
	defer zr.Close()
	allowed := map[string]SourceAssetImageFile{}
	var extractTotal int64
	for _, item := range manifest.ImageFiles {
		allowed[item.Path] = item
		extractTotal += item.Size
	}
	var extractDone int64
	if progress != nil {
		progress(BuildProgress{Phase: "source_bundle_manifest", CurrentFile: filepath.Base(path)})
	}
	for _, zf := range zr.File {
		if zf.Name == sourceAssetsManifestName {
			continue
		}
		expected, exists := allowed[zf.Name]
		if !exists {
			return "", "", fmt.Errorf("unexpected file in source assets bundle: %s", zf.Name)
		}
		dst := filepath.Join(stage, filepath.FromSlash(zf.Name))
		if err := extractZipFile(zf, dst, expected, func(done, total int64) {
			if progress != nil {
				progress(BuildProgress{Phase: "source_bundle_extract", CurrentFile: zf.Name, CurrentDone: done, CurrentTotal: total, OverallDone: min64(extractDone+done, extractTotal), OverallTotal: extractTotal})
			}
		}); err != nil {
			return "", "", err
		}
		extractDone += expected.Size
		delete(allowed, zf.Name)
	}
	if len(allowed) != 0 {
		return "", "", fmt.Errorf("source assets bundle is missing %d image files", len(allowed))
	}
	if err := validateMaterializedSourceImage(stage, manifest, progress); err != nil {
		return "", "", err
	}
	ok = true
	return root, stage, nil
}

func extractZipFile(zf *zip.File, dst string, expected SourceAssetImageFile, report func(done, total int64)) error {
	if int64(zf.UncompressedSize64) != expected.Size {
		return fmt.Errorf("source image size mismatch for %s", zf.Name)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	r, err := zf.Open()
	if err != nil {
		return err
	}
	defer r.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	h := sha256.New()
	buffer := make([]byte, 8<<20)
	var done int64
	for {
		n, readErr := r.Read(buffer)
		if n > 0 {
			if _, err := out.Write(buffer[:n]); err != nil {
				out.Close()
				return err
			}
			_, _ = h.Write(buffer[:n])
			done += int64(n)
			if report != nil {
				report(done, expected.Size)
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			out.Close()
			return readErr
		}
	}
	if err := out.Close(); err != nil {
		return err
	}
	if done != expected.Size || hex.EncodeToString(h.Sum(nil)) != expected.SHA256 {
		return fmt.Errorf("source image hash mismatch for %s", zf.Name)
	}
	return nil
}

func validateMaterializedSourceImage(cache string, manifest SourceAssetManifest, progress BuildProgressFunc) error {
	// Extraction already checked every complete image by exact uncompressed size
	// and SHA-256 while writing it. Do not immediately reread every multi-GB image
	// just to recompute the same digest. The structural member pass below is the
	// independent compatibility proof needed by the reconstruction layer.
	for _, item := range manifest.ImageFiles {
		path := filepath.Join(cache, filepath.FromSlash(item.Path))
		info, err := os.Lstat(path)
		if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || info.Size() != item.Size {
			return fmt.Errorf("source image validation failed for %s", item.Path)
		}
	}
	var verifyTotal int64
	for _, item := range manifest.SourceMembers {
		verifyTotal += item.Size
	}
	var verifyDone int64
	root := filepath.Join(cache, "source")

	// SourceMembers are normalized/sorted by archive path. Keep one A18 reader
	// open for all members from the same reduced image. Older code reopened and
	// reparsed a multi-GB archive for every one of the 1,682 members, which made
	// sibling .unburger-assets verification look stalled even on fast storage.
	var currentArchivePath string
	var currentArchive *ArchiveReader
	closeArchive := func() {
		if currentArchive != nil {
			_ = currentArchive.Close()
			currentArchive = nil
			currentArchivePath = ""
		}
	}
	defer closeArchive()

	for _, item := range manifest.SourceMembers {
		label := item.ArchivePath + "#" + item.MemberPath
		if progress != nil {
			progress(BuildProgress{Phase: "source_bundle_verify", CurrentFile: label, OverallDone: verifyDone, OverallTotal: verifyTotal})
		}
		if item.ArchivePath == "BLUE_REFLECTION.exe" && item.MemberPath == "wardrobe_table" {
			closeArchive()
			f, err := os.Open(filepath.Join(root, "BLUE_REFLECTION.exe"))
			if err != nil {
				return err
			}
			blob := make([]byte, item.Size)
			_, err = f.ReadAt(blob, sourceRosterOffset)
			_ = f.Close()
			if err != nil || shaBytes(blob) != item.SHA256 {
				return fmt.Errorf("source wardrobe metadata validation failed")
			}
			verifyDone += item.Size
			if progress != nil {
				progress(BuildProgress{Phase: "source_bundle_verify", CurrentFile: label, CurrentDone: item.Size, CurrentTotal: item.Size, OverallDone: min64(verifyDone, verifyTotal), OverallTotal: verifyTotal})
			}
			continue
		}

		archivePath := filepath.Join(root, filepath.FromSlash(item.ArchivePath))
		if currentArchive == nil || !strings.EqualFold(currentArchivePath, archivePath) {
			closeArchive()
			p, err := OpenA18(archivePath)
			if err != nil {
				return err
			}
			currentArchive = p
			currentArchivePath = archivePath
		}
		e, ok := currentArchive.Find(item.MemberPath)
		if !ok {
			return fmt.Errorf("source asset member missing: %s#%s", item.ArchivePath, item.MemberPath)
		}
		digest, err := currentArchive.plainDigestWithProgress(e, func(done, total int64) {
			if progress != nil {
				progress(BuildProgress{
					Phase:        "source_bundle_verify",
					CurrentFile:  label,
					CurrentDone:  done,
					CurrentTotal: total,
					OverallDone:  min64(verifyDone+done, verifyTotal),
					OverallTotal: verifyTotal,
				})
			}
		})
		if err != nil || int64(e.Size) != item.Size || digest != item.SHA256 {
			return fmt.Errorf("source asset member mismatch: %s#%s", item.ArchivePath, item.MemberPath)
		}
		verifyDone += item.Size
		if progress != nil {
			progress(BuildProgress{Phase: "source_bundle_verify", CurrentFile: label, CurrentDone: item.Size, CurrentTotal: item.Size, OverallDone: min64(verifyDone, verifyTotal), OverallTotal: verifyTotal})
		}
	}
	if err := validateSupplementalSourceAssets(root, manifest.SupplementalSources, progress); err != nil {
		return err
	}
	return nil
}
