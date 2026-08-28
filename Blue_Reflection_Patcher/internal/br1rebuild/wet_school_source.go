package br1rebuild

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	WetSchoolCanonicalSourceCapability = "quartet_wet_school_canonical_source_v1"
	WetSchoolCanonicalRelativeRoot     = "content/restoration/wet-school/source"
	expectedWetSchoolSourceMembers     = 30
)

type WetSchoolCanonicalSourceManifest struct {
	Type              string              `json:"type"`
	FormatVersion     int                 `json:"format_version"`
	Capability        string              `json:"capability"`
	SourceFingerprint string              `json:"source_fingerprint"`
	SourceMembers     []SourceAssetMember `json:"source_members"`
}

func wetSchoolSourceMemberNames() map[string]bool {
	out := make(map[string]bool, expectedWetSchoolSourceMembers)
	for i := 0; i < 15; i++ {
		pc := fmt.Sprintf("pc%02d", i)
		base := `\data\x64\character\` + pc + `\` + pc + `_scl_w`
		out[strings.ToLower(base+`.elixir.gz`)] = true
		out[strings.ToLower(base+`.g1t`)] = true
	}
	return out
}

func writeWetSchoolSourceRoot(sourceRoot, root string) ([]SourceAssetMember, error) {
	location, err := LocateSourceInstall(SourceLocator{LooseRoot: sourceRoot})
	if err != nil {
		return nil, err
	}
	sourceData, err := sourceDataDirectory(location.Root)
	if err != nil {
		return nil, err
	}
	sourceArchive := casePath(sourceData, "PACK00_02.PAK")
	if info, err := os.Stat(sourceArchive); err != nil || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("wet-school canonical source missing DATA/PACK00_02.PAK")
	}
	dataRoot := filepath.Join(root, "DATA")
	if err := os.MkdirAll(dataRoot, 0o755); err != nil {
		return nil, err
	}
	wanted := wetSchoolSourceMemberNames()
	members := []SourceAssetMember{}
	dst := filepath.Join(dataRoot, "PACK00_02.PAK")
	if err := buildReducedA18(sourceArchive, dst, func(name string) bool {
		return wanted[strings.ToLower(name)]
	}, "quartet_wet_school", &members); err != nil {
		return nil, err
	}
	if len(members) != expectedWetSchoolSourceMembers {
		return nil, fmt.Errorf("wet-school canonical source contains %d members, expected %d", len(members), expectedWetSchoolSourceMembers)
	}
	seen := map[string]bool{}
	for _, item := range members {
		seen[strings.ToLower(item.MemberPath)] = true
	}
	for name := range wanted {
		if !seen[name] {
			return nil, fmt.Errorf("wet-school canonical source missing %s", name)
		}
	}
	sort.Slice(members, func(i, j int) bool {
		ki := members[i].ArchivePath + "\x00" + members[i].MemberPath
		kj := members[j].ArchivePath + "\x00" + members[j].MemberPath
		return ki < kj
	})
	return members, nil
}

// BuildWetSchoolCanonicalPayload stages the exact validated Original SCL_W
// donor family inside the always-shipped runtime bundle. The public patcher
// therefore never needs a sibling .unburger-assets bundle or a retail BR1
// installation to provide canonical UNCENSOR content.
func BuildWetSchoolCanonicalPayload(sourceRoot, payloadRoot string) (WetSchoolCanonicalSourceManifest, error) {
	if err := os.RemoveAll(payloadRoot); err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	root := filepath.Join(payloadRoot, "source")
	members, err := writeWetSchoolSourceRoot(sourceRoot, root)
	if err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	manifest := WetSchoolCanonicalSourceManifest{
		Type:              "unburger_quartet_wet_school_canonical_source",
		FormatVersion:     1,
		Capability:        WetSchoolCanonicalSourceCapability,
		SourceFingerprint: sourceAssetFingerprint(members),
		SourceMembers:     members,
	}
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	if err := os.WriteFile(filepath.Join(payloadRoot, "MANIFEST.json"), append(data, '\n'), 0o644); err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	if err := ValidateWetSchoolCanonicalPayload(payloadRoot); err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	return manifest, nil
}

func readWetSchoolCanonicalManifest(payloadRoot string) (WetSchoolCanonicalSourceManifest, error) {
	data, err := os.ReadFile(filepath.Join(payloadRoot, "MANIFEST.json"))
	if err != nil {
		return WetSchoolCanonicalSourceManifest{}, fmt.Errorf("read wet-school canonical manifest: %w", err)
	}
	var manifest WetSchoolCanonicalSourceManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return WetSchoolCanonicalSourceManifest{}, fmt.Errorf("parse wet-school canonical manifest: %w", err)
	}
	return manifest, nil
}

func copyCanonicalFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".tmp"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(out, in)
	closeErr := out.Close()
	if copyErr != nil {
		_ = os.Remove(tmp)
		return copyErr
	}
	if closeErr != nil {
		_ = os.Remove(tmp)
		return closeErr
	}
	if err := os.Rename(tmp, dst); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

// CopyWetSchoolCanonicalPayload materializes a previously imported, validated
// local canonical source cache into release staging. It intentionally copies
// only the two capability files (manifest + reduced 30-member PACK00_02.PAK),
// never a retail BR1 installation or unrelated local state.
func CopyWetSchoolCanonicalPayload(sourcePayloadRoot, destinationPayloadRoot string) (WetSchoolCanonicalSourceManifest, error) {
	if err := ValidateWetSchoolCanonicalPayload(sourcePayloadRoot); err != nil {
		return WetSchoolCanonicalSourceManifest{}, fmt.Errorf("validate local wet-school canonical source cache: %w", err)
	}
	manifest, err := readWetSchoolCanonicalManifest(sourcePayloadRoot)
	if err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	if err := os.RemoveAll(destinationPayloadRoot); err != nil {
		return WetSchoolCanonicalSourceManifest{}, err
	}
	files := [][2]string{
		{filepath.Join(sourcePayloadRoot, "MANIFEST.json"), filepath.Join(destinationPayloadRoot, "MANIFEST.json")},
		{filepath.Join(sourcePayloadRoot, "source", "DATA", "PACK00_02.PAK"), filepath.Join(destinationPayloadRoot, "source", "DATA", "PACK00_02.PAK")},
	}
	for _, pair := range files {
		if err := copyCanonicalFile(pair[0], pair[1]); err != nil {
			return WetSchoolCanonicalSourceManifest{}, fmt.Errorf("copy canonical wet-school cache: %w", err)
		}
	}
	if err := ValidateWetSchoolCanonicalPayload(destinationPayloadRoot); err != nil {
		return WetSchoolCanonicalSourceManifest{}, fmt.Errorf("validate staged wet-school canonical payload: %w", err)
	}
	return manifest, nil
}

func ValidateWetSchoolCanonicalPayload(payloadRoot string) error {
	data, err := os.ReadFile(filepath.Join(payloadRoot, "MANIFEST.json"))
	if err != nil {
		return fmt.Errorf("read wet-school canonical manifest: %w", err)
	}
	var manifest WetSchoolCanonicalSourceManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return fmt.Errorf("parse wet-school canonical manifest: %w", err)
	}
	if manifest.Type != "unburger_quartet_wet_school_canonical_source" || manifest.FormatVersion != 1 || manifest.Capability != WetSchoolCanonicalSourceCapability {
		return fmt.Errorf("unsupported wet-school canonical manifest")
	}
	if len(manifest.SourceMembers) != expectedWetSchoolSourceMembers || sourceAssetFingerprint(manifest.SourceMembers) != manifest.SourceFingerprint {
		return fmt.Errorf("wet-school canonical manifest fingerprint/count mismatch")
	}
	root := filepath.Join(payloadRoot, "source")
	if err := validateWetSchoolSourceRoot(root); err != nil {
		return err
	}
	p, err := OpenA18(filepath.Join(root, "DATA", "PACK00_02.PAK"))
	if err != nil {
		return err
	}
	defer p.Close()
	for _, item := range manifest.SourceMembers {
		e, ok := p.Find(item.MemberPath)
		if !ok {
			return fmt.Errorf("wet-school canonical payload missing %s", item.MemberPath)
		}
		if int64(e.Size) != item.Size {
			return fmt.Errorf("wet-school canonical payload size mismatch for %s", item.MemberPath)
		}
		digest, err := (CrossFormatEntry{Pak: p, Entry: e}).PlainSHA256()
		if err != nil {
			return err
		}
		if !strings.EqualFold(digest, item.SHA256) {
			return fmt.Errorf("wet-school canonical payload checksum mismatch for %s", item.MemberPath)
		}
	}
	return nil
}

func validateWetSchoolSourceRoot(root string) error {
	archivePath := filepath.Join(root, "DATA", "PACK00_02.PAK")
	if info, err := os.Stat(archivePath); err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("wet-school source missing DATA/PACK00_02.PAK")
	}
	p, err := OpenA18(archivePath)
	if err != nil {
		return err
	}
	defer p.Close()
	wanted := wetSchoolSourceMemberNames()
	for name := range wanted {
		if _, ok := p.Find(name); !ok {
			return fmt.Errorf("wet-school source member missing: %s", name)
		}
	}
	return nil
}
