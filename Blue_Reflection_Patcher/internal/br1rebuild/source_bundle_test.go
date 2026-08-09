package br1rebuild

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSourceAssetBundleLoadsAsHiddenSource(t *testing.T) {
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	stage := t.TempDir()
	root := filepath.Join(stage, "source")
	data := filepath.Join(root, "DATA")
	if err := os.MkdirAll(data, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "BLUE_REFLECTION.exe"), []byte("fixture"), 0o644); err != nil {
		t.Fatal(err)
	}
	members := []SourceAssetMember{}
	for _, name := range []string{"PACK00_02.PAK", "PACK00_03.PAK", "PACK01.PAK"} {
		memberName := `\fixture\` + name + `.bin`
		payload := []byte("payload-" + name)
		if err := writePlainA18(filepath.Join(data, name), map[string]ArchiveInput{memberName: MemoryEntry{Data: payload}}); err != nil {
			t.Fatal(err)
		}
		members = append(members, SourceAssetMember{Group: "fixture", ArchivePath: "DATA/" + name, MemberPath: memberName, Size: int64(len(payload)), SHA256: shaBytes(payload)})
	}
	imageFiles, err := inventoryImageFiles(stage)
	if err != nil {
		t.Fatal(err)
	}
	manifest := SourceAssetManifest{
		Type:                     "unburger_br1_dlc_source_assets",
		FormatVersion:            SourceAssetsFormatVersion,
		Capability:               SourceAssetsCapability,
		ReconstructionCapability: "br1_legacy_content_rebuild_v1",
		CleanAnchorCapability:    SourceAnchorsCapability,
		SourceMembers:            members,
		ImageFiles:               imageFiles,
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(manifest.SourceMembers)
	manifest.CleanAnchorFingerprint = manifest.SourceFingerprint
	anchors := SourceAnchorManifest{
		Type:              "unburger_br1_dlc_clean_source_anchors",
		FormatVersion:     SourceAnchorsFormatVersion,
		Capability:        SourceAnchorsCapability,
		SourceFingerprint: manifest.SourceFingerprint,
		SourceMembers:     append([]SourceAssetMember(nil), members...),
	}
	anchorPath := filepath.Join(t.TempDir(), "anchors.json")
	blob, err := json.Marshal(anchors)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(anchorPath, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	bundleDir := t.TempDir()
	bundle := filepath.Join(bundleDir, "UNBURGER_BR1_DLC_ASSETS_v2.unburger-assets")
	if err := packageSourceAssetImage(stage, bundle, manifest); err != nil {
		t.Fatal(err)
	}
	foundBundle, found, err := FindCompatibleSourceAssetBundle(bundleDir, anchorPath)
	if err != nil {
		t.Fatal(err)
	}
	if !found || foundBundle != bundle {
		t.Fatalf("metadata-only sibling lookup failed: found=%v path=%q want=%q", found, foundBundle, bundle)
	}
	var progress []BuildProgress
	location, err := LocateSourceInstall(SourceLocator{AssetRoot: bundleDir, AnchorPath: anchorPath, Progress: func(item BuildProgress) {
		progress = append(progress, item)
	}})
	if err != nil {
		t.Fatal(err)
	}
	phases := map[string]bool{}
	for _, item := range progress {
		phases[item.Phase] = true
	}
	for _, phase := range []string{"source_bundle_manifest", "source_bundle_extract", "source_bundle_verify"} {
		if !phases[phase] {
			t.Fatalf("source bundle progress never reported %s: %+v", phase, progress)
		}
	}
	last := progress[len(progress)-1]
	if last.Phase != "source_bundle_verify" || last.OverallTotal <= 0 || last.OverallDone != last.OverallTotal {
		t.Fatalf("source bundle verification did not reach 100%%: %+v", last)
	}
	if location.Origin != "asset_bundle" {
		t.Fatalf("unexpected source origin: %s", location.Origin)
	}
	if err := validateSourceInstall(location.Root); err != nil {
		t.Fatalf("materialized source image is unusable: %v", err)
	}
	if location.CleanupRoot == "" {
		t.Fatal("asset bundle materialization must be transient")
	}
	defer os.RemoveAll(location.CleanupRoot)
	location2, err := LocateSourceInstall(SourceLocator{AssetRoot: bundle, AnchorPath: anchorPath})
	if err != nil {
		t.Fatal(err)
	}
	if location2.CleanupRoot == "" || location2.Root == location.Root {
		t.Fatalf("expected independent transient materializations: %#v %#v", location, location2)
	}
	cleanup2 := location2.CleanupRoot
	if err := os.RemoveAll(cleanup2); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(cleanup2); !os.IsNotExist(err) {
		t.Fatalf("transient asset root survived cleanup: %v", err)
	}
}

func TestSourceAssetManifestRejectsWrongCapability(t *testing.T) {
	manifest := SourceAssetManifest{
		Type:                     "unburger_br1_dlc_source_assets",
		FormatVersion:            SourceAssetsFormatVersion,
		Capability:               "other_capability",
		ReconstructionCapability: "br1_legacy_content_rebuild_v1",
		CleanAnchorCapability:    SourceAnchorsCapability,
		CleanAnchorFingerprint:   string(make([]byte, 64)),
		SourceMembers:            []SourceAssetMember{{ArchivePath: "DATA/PACK01.PAK", MemberPath: `\x`, Size: 1, SHA256: string(make([]byte, 64))}},
		ImageFiles:               []SourceAssetImageFile{{Path: "source/x", Size: 1, SHA256: string(make([]byte, 64))}},
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(manifest.SourceMembers)
	if err := validateSourceAssetManifest(manifest); err == nil {
		t.Fatal("incompatible capability was accepted")
	}
}

func TestSourceAssetBundleRejectsDifferentApprovedAnchorSet(t *testing.T) {
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	stage := t.TempDir()
	root := filepath.Join(stage, "source")
	data := filepath.Join(root, "DATA")
	if err := os.MkdirAll(data, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "BLUE_REFLECTION.exe"), []byte("fixture"), 0o644); err != nil {
		t.Fatal(err)
	}
	payload := []byte("payload")
	memberName := `\fixture\x.bin`
	if err := writePlainA18(filepath.Join(data, "PACK00_02.PAK"), map[string]ArchiveInput{memberName: MemoryEntry{Data: payload}}); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"PACK00_03.PAK", "PACK01.PAK"} {
		if err := writePlainA18(filepath.Join(data, name), map[string]ArchiveInput{`\fixture\x.bin`: MemoryEntry{Data: payload}}); err != nil {
			t.Fatal(err)
		}
	}
	members := []SourceAssetMember{{Group: "fixture", ArchivePath: "DATA/PACK00_02.PAK", MemberPath: memberName, Size: int64(len(payload)), SHA256: shaBytes(payload)}}
	imageFiles, err := inventoryImageFiles(stage)
	if err != nil {
		t.Fatal(err)
	}
	fingerprint := sourceAssetFingerprint(members)
	manifest := SourceAssetManifest{
		Type:                     "unburger_br1_dlc_source_assets",
		FormatVersion:            SourceAssetsFormatVersion,
		Capability:               SourceAssetsCapability,
		ReconstructionCapability: "br1_legacy_content_rebuild_v1",
		CleanAnchorCapability:    SourceAnchorsCapability,
		CleanAnchorFingerprint:   fingerprint,
		SourceFingerprint:        fingerprint,
		SourceMembers:            members,
		ImageFiles:               imageFiles,
	}
	bundle := filepath.Join(t.TempDir(), "assets.unburger-assets")
	if err := packageSourceAssetImage(stage, bundle, manifest); err != nil {
		t.Fatal(err)
	}
	anchors := SourceAnchorManifest{
		Type:          "unburger_br1_dlc_clean_source_anchors",
		FormatVersion: SourceAnchorsFormatVersion,
		Capability:    SourceAnchorsCapability,
		SourceMembers: []SourceAssetMember{{Group: "fixture", ArchivePath: "DATA/PACK00_02.PAK", MemberPath: memberName, Size: int64(len(payload)), SHA256: shaBytes([]byte("different"))}},
	}
	anchors.SourceFingerprint = sourceAssetFingerprint(anchors.SourceMembers)
	blob, err := json.Marshal(anchors)
	if err != nil {
		t.Fatal(err)
	}
	anchorPath := filepath.Join(t.TempDir(), "anchors.json")
	if err := os.WriteFile(anchorPath, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LocateSourceInstall(SourceLocator{AssetRoot: bundle, AnchorPath: anchorPath}); err == nil {
		t.Fatal("asset bundle built against a different clean-source anchor set was accepted")
	}
}
