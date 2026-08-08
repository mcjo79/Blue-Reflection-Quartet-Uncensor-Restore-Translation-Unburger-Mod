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
)

const (
	SourceAssetsCapability    = "br1_legacy_source_assets_v1"
	SourceAssetsFormatVersion = 1
	sourceAssetsManifestName  = "MANIFEST.json"
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

type SourceAssetManifest struct {
	Type                     string                 `json:"type"`
	FormatVersion            int                    `json:"format_version"`
	Capability               string                 `json:"capability"`
	ReconstructionCapability string                 `json:"reconstruction_capability"`
	SourceFingerprint        string                 `json:"source_fingerprint"`
	SourceMembers            []SourceAssetMember    `json:"source_members"`
	ImageFiles               []SourceAssetImageFile `json:"image_files"`
}

type sourceAssetBuildResult struct {
	Manifest SourceAssetManifest
	Path     string
	SHA256   string
	Size     int64
}

func BuildSourceAssetBundle(sourceRoot, outputPath string) (SourceAssetManifest, error) {
	location, err := LocateSourceInstall(SourceLocator{LooseRoot: sourceRoot})
	if err != nil {
		return SourceAssetManifest{}, err
	}
	stage, err := os.MkdirTemp("", "unburger-br1-assets-")
	if err != nil {
		return SourceAssetManifest{}, err
	}
	defer os.RemoveAll(stage)
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
		SourceMembers:            members,
		ImageFiles:               imageFiles,
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(members)
	if err := packageSourceAssetImage(stage, outputPath, manifest); err != nil {
		return SourceAssetManifest{}, err
	}
	return manifest, nil
}

func sourceCharacterCatalogBlob(sourceRoot string) ([]byte, error) {
	_, loc, err := readSourceCharacterCatalog(sourceRoot)
	if err != nil {
		return nil, err
	}
	if loc.Kind == "loose" {
		return os.ReadFile(loc.Path)
	}
	p, err := OpenA18(loc.Path)
	if err != nil {
		return nil, err
	}
	defer p.Close()
	e, ok := p.Find(loc.Member)
	if !ok {
		return nil, fmt.Errorf("source catalog member disappeared: %s", loc.Member)
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
	h := sha256.New()
	for _, item := range members {
		fmt.Fprintf(h, "%s\x00%s\x00%d\x00%s\n", item.ArchivePath, item.MemberPath, item.Size, item.SHA256)
	}
	return hex.EncodeToString(h.Sum(nil))
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

func locateSourceAssetBundle(raw string) (SourceLocation, error) {
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
		candidates, err := compatibleAssetBundles(abs)
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
	root, err := materializeSourceAssetBundle(bundle, manifest)
	if err != nil {
		return SourceLocation{}, err
	}
	if err := validateSourceInstall(root); err != nil {
		return SourceLocation{}, fmt.Errorf("materialized source bundle is invalid: %w", err)
	}
	return SourceLocation{Root: root, Origin: "asset_bundle"}, nil
}

func compatibleAssetBundles(dir string) ([]string, error) {
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
		if err == nil && validateSourceAssetManifest(manifest) == nil {
			out = append(out, path)
		}
	}
	sort.Strings(out)
	return out, nil
}

func ReadSourceAssetManifest(path string) (SourceAssetManifest, error) {
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
	if manifest.Type != "unburger_br1_dlc_source_assets" || manifest.FormatVersion != SourceAssetsFormatVersion {
		return fmt.Errorf("unsupported source assets manifest type/version")
	}
	if manifest.Capability != SourceAssetsCapability || manifest.ReconstructionCapability != "br1_legacy_content_rebuild_v1" {
		return fmt.Errorf("incompatible source assets capability")
	}
	if len(manifest.SourceMembers) == 0 || len(manifest.ImageFiles) == 0 {
		return fmt.Errorf("source assets manifest is empty")
	}
	if sourceAssetFingerprint(manifest.SourceMembers) != manifest.SourceFingerprint {
		return fmt.Errorf("source assets fingerprint mismatch")
	}
	seen := map[string]bool{}
	for _, item := range manifest.ImageFiles {
		clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(item.Path)))
		if !strings.HasPrefix(clean, "source/") || strings.Contains(clean, "../") || seen[clean] || item.Size < 0 || len(item.SHA256) != 64 {
			return fmt.Errorf("invalid source image file entry %q", item.Path)
		}
		seen[clean] = true
	}
	return nil
}

func materializeSourceAssetBundle(path string, manifest SourceAssetManifest) (string, error) {
	hash, _, err := hashPath(path)
	if err != nil {
		return "", err
	}
	cacheBase, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	cache := filepath.Join(cacheBase, "unburger-patcher", "br1-assets", hash[:20])
	root := filepath.Join(cache, "source")
	marker := filepath.Join(cache, "BUNDLE_SHA256")
	if blob, err := os.ReadFile(marker); err == nil && strings.TrimSpace(string(blob)) == hash {
		if validateMaterializedSourceImage(cache, manifest) == nil {
			return root, nil
		}
	}
	_ = os.RemoveAll(cache)
	if err := os.MkdirAll(cache, 0o755); err != nil {
		return "", err
	}
	zr, err := zip.OpenReader(path)
	if err != nil {
		return "", err
	}
	defer zr.Close()
	allowed := map[string]SourceAssetImageFile{}
	for _, item := range manifest.ImageFiles {
		allowed[item.Path] = item
	}
	for _, zf := range zr.File {
		if zf.Name == sourceAssetsManifestName {
			continue
		}
		expected, ok := allowed[zf.Name]
		if !ok {
			return "", fmt.Errorf("unexpected file in source assets bundle: %s", zf.Name)
		}
		dst := filepath.Join(cache, filepath.FromSlash(zf.Name))
		if err := extractZipFile(zf, dst, expected); err != nil {
			return "", err
		}
		delete(allowed, zf.Name)
	}
	if len(allowed) != 0 {
		return "", fmt.Errorf("source assets bundle is missing %d image files", len(allowed))
	}
	if err := validateMaterializedSourceImage(cache, manifest); err != nil {
		return "", err
	}
	if err := os.WriteFile(marker, []byte(hash+"\n"), 0o644); err != nil {
		return "", err
	}
	return root, nil
}

func extractZipFile(zf *zip.File, dst string, expected SourceAssetImageFile) error {
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
	_, copyErr := io.CopyBuffer(io.MultiWriter(out, h), r, make([]byte, 8<<20))
	closeErr := out.Close()
	if copyErr != nil {
		return copyErr
	}
	if closeErr != nil {
		return closeErr
	}
	if hex.EncodeToString(h.Sum(nil)) != expected.SHA256 {
		return fmt.Errorf("source image hash mismatch for %s", zf.Name)
	}
	return nil
}

func validateMaterializedSourceImage(cache string, manifest SourceAssetManifest) error {
	for _, item := range manifest.ImageFiles {
		path := filepath.Join(cache, filepath.FromSlash(item.Path))
		hash, size, err := hashPath(path)
		if err != nil || size != item.Size || hash != item.SHA256 {
			return fmt.Errorf("source image validation failed for %s", item.Path)
		}
	}
	root := filepath.Join(cache, "source")
	for _, item := range manifest.SourceMembers {
		if item.ArchivePath == "BLUE_REFLECTION.exe" && item.MemberPath == "wardrobe_table" {
			f, err := os.Open(filepath.Join(root, "BLUE_REFLECTION.exe"))
			if err != nil {
				return err
			}
			blob := make([]byte, item.Size)
			_, err = f.ReadAt(blob, sourceRosterOffset)
			f.Close()
			if err != nil || shaBytes(blob) != item.SHA256 {
				return fmt.Errorf("source wardrobe metadata validation failed")
			}
			continue
		}
		archivePath := filepath.Join(root, filepath.FromSlash(item.ArchivePath))
		p, err := OpenA18(archivePath)
		if err != nil {
			return err
		}
		e, ok := p.Find(item.MemberPath)
		if !ok {
			p.Close()
			return fmt.Errorf("source asset member missing: %s#%s", item.ArchivePath, item.MemberPath)
		}
		digest, err := p.PlainDigest(e)
		p.Close()
		if err != nil || int64(e.Size) != item.Size || digest != item.SHA256 {
			return fmt.Errorf("source asset member mismatch: %s#%s", item.ArchivePath, item.MemberPath)
		}
	}
	return nil
}
