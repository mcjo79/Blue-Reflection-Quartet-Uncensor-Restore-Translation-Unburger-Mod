package br1rebuild

import (
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
		SourceMembers:            members,
		ImageFiles:               imageFiles,
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(manifest.SourceMembers)
	bundleDir := t.TempDir()
	bundle := filepath.Join(bundleDir, "UNBURGER_BR1_DLC_ASSETS_v1.unburger-assets")
	if err := packageSourceAssetImage(stage, bundle, manifest); err != nil {
		t.Fatal(err)
	}
	location, err := LocateSourceInstall(SourceLocator{AssetRoot: bundleDir})
	if err != nil {
		t.Fatal(err)
	}
	if location.Origin != "asset_bundle" {
		t.Fatalf("unexpected source origin: %s", location.Origin)
	}
	if err := validateSourceInstall(location.Root); err != nil {
		t.Fatalf("materialized source image is unusable: %v", err)
	}
	location2, err := LocateSourceInstall(SourceLocator{AssetRoot: bundle})
	if err != nil {
		t.Fatal(err)
	}
	if location2.Root != location.Root {
		t.Fatalf("bundle cache was not reused: %q != %q", location2.Root, location.Root)
	}
}

func TestSourceAssetManifestRejectsWrongCapability(t *testing.T) {
	manifest := SourceAssetManifest{
		Type:                     "unburger_br1_dlc_source_assets",
		FormatVersion:            SourceAssetsFormatVersion,
		Capability:               "other_capability",
		ReconstructionCapability: "br1_legacy_content_rebuild_v1",
		SourceMembers:            []SourceAssetMember{{ArchivePath: "DATA/PACK01.PAK", MemberPath: `\x`, Size: 1, SHA256: string(make([]byte, 64))}},
		ImageFiles:               []SourceAssetImageFile{{Path: "source/x", Size: 1, SHA256: string(make([]byte, 64))}},
	}
	manifest.SourceFingerprint = sourceAssetFingerprint(manifest.SourceMembers)
	if err := validateSourceAssetManifest(manifest); err == nil {
		t.Fatal("incompatible capability was accepted")
	}
}
