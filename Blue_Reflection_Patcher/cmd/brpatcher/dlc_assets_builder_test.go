package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

func TestResolveDLCAssetOutputPathExplicitFileAndDirectory(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "custom.unburger-assets")
	got, err := resolveDLCAssetOutputPath("", "", file)
	if err != nil {
		t.Fatal(err)
	}
	if got != file {
		t.Fatalf("explicit file=%q want=%q", got, file)
	}
	got, err = resolveDLCAssetOutputPath("", "", root)
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(root, defaultDLCAssetBundleName)
	if got != want {
		t.Fatalf("explicit directory=%q want=%q", got, want)
	}
}

func TestValidateCombinedDLCAssetManifestRequiresFrozenCounts(t *testing.T) {
	manifest := br1rebuild.SourceAssetManifest{
		SourceMembers: make([]br1rebuild.SourceAssetMember, 1682),
		SupplementalSources: []br1rebuild.SupplementalSourceAssetManifest{{
			Capability:    br1rebuild.SecondLightSourceAssetsCapability,
			SourceMembers: make([]br1rebuild.SourceAssetMember, 2942),
		}},
	}
	br1, sl, err := validateCombinedDLCAssetManifest(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if br1 != 1682 || sl != 2942 {
		t.Fatalf("counts=%d/%d", br1, sl)
	}
	manifest.SupplementalSources[0].SourceMembers = manifest.SupplementalSources[0].SourceMembers[:2941]
	if _, _, err := validateCombinedDLCAssetManifest(manifest); err == nil {
		t.Fatal("2941-member Second Light supplement was accepted")
	}
}

func TestWriteDLCAssetSHA256Sidecar(t *testing.T) {
	bundle := filepath.Join(t.TempDir(), defaultDLCAssetBundleName)
	if err := os.WriteFile(bundle, []byte("fixture"), 0o644); err != nil {
		t.Fatal(err)
	}
	digest := strings.Repeat("a", 64)
	if err := writeDLCAssetSHA256Sidecar(bundle, digest); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(bundle + ".sha256")
	if err != nil {
		t.Fatal(err)
	}
	want := digest + "  " + filepath.Base(bundle) + "\n"
	if string(blob) != want {
		t.Fatalf("sidecar=%q want=%q", string(blob), want)
	}
}

func TestVerifyDLCSourceArchiveHashesAcceptsExactContractAndRejectsDrift(t *testing.T) {
	project := t.TempDir()
	br1 := filepath.Join(t.TempDir(), "br1")
	sl := filepath.Join(t.TempDir(), "sl")
	if err := os.MkdirAll(filepath.Join(project, "contracts"), 0o755); err != nil {
		t.Fatal(err)
	}
	makeGame := func(id, root string, count int) dlcSourceArchiveHashGame {
		game := dlcSourceArchiveHashGame{ID: id}
		for i := 0; i < count; i++ {
			rel := filepath.ToSlash(filepath.Join("Data", "fixture-"+string(rune('a'+i))+".bin"))
			payload := []byte(id + ":" + rel)
			path := filepath.Join(root, filepath.FromSlash(rel))
			if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, payload, 0o644); err != nil {
				t.Fatal(err)
			}
			h := sha256.Sum256(payload)
			game.Files = append(game.Files, dlcSourceArchiveHashFile{Path: rel, Size: int64(len(payload)), SHA256: hex.EncodeToString(h[:])})
		}
		return game
	}
	contract := dlcSourceArchiveHashContract{
		Type: "unburger_dlc_source_archive_hashes", FormatVersion: 1,
		Games: []dlcSourceArchiveHashGame{makeGame("blue_reflection_2017", br1, 7), makeGame("blue_reflection_second_light", sl, 6)},
	}
	blob, err := json.Marshal(contract)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(project, "contracts", "DLC_SOURCE_ARCHIVE_HASHES_V1.json"), blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := verifyDLCSourceArchiveHashes(project, br1, sl, nil); err != nil {
		t.Fatal(err)
	}
	drift := filepath.Join(sl, filepath.FromSlash(contract.Games[1].Files[0].Path))
	if err := os.WriteFile(drift, []byte("same-size-but-drifted........"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := verifyDLCSourceArchiveHashes(project, br1, sl, nil); err == nil {
		t.Fatal("modified source archive was accepted")
	}
}
