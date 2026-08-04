package baseline

import (
	"os"
	"path/filepath"
	"testing"
)

func TestEnsureReusesAndPreservesVersionedBaselines(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	firstPath := filepath.Join(game, "Data", "PACK11.PAK")
	secondPath := filepath.Join(game, "Data", "PACK10_01.PAK")
	if err := os.WriteFile(firstPath, []byte("version-one-event"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(secondPath, []byte("version-one-shader"), 0o644); err != nil {
		t.Fatal(err)
	}
	paths := []string{"Data/PACK11.PAK", "Data/PACK10_01.PAK", "Data/ADDED.PAK"}
	first, err := Ensure(game, state, "blue_reflection_quartet", paths)
	if err != nil {
		t.Fatal(err)
	}
	if first.Action != ActionCreated || len(first.Manifest.Files) != 3 {
		t.Fatalf("unexpected first baseline: %+v", first)
	}
	if _, ok := first.StoredFiles["Data/PACK11.PAK"]; !ok {
		t.Fatalf("stored baseline missing PACK11: %+v", first.StoredFiles)
	}
	second, err := Ensure(game, state, "blue_reflection_quartet", paths)
	if err != nil {
		t.Fatal(err)
	}
	if second.Action != ActionReused || second.Manifest.BaselineID != first.Manifest.BaselineID {
		t.Fatalf("identical state was not reused: first=%+v second=%+v", first.Manifest, second.Manifest)
	}
	inspection, err := Inspect(game, state, "blue_reflection_quartet")
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != "matches_known_baseline" || inspection.BaselineCount != 1 {
		t.Fatalf("unexpected initial inspection: %+v", inspection)
	}
	if err := os.WriteFile(firstPath, []byte("version-two-event"), 0o644); err != nil {
		t.Fatal(err)
	}
	changed, err := Inspect(game, state, "blue_reflection_quartet")
	if err != nil {
		t.Fatal(err)
	}
	if changed.Status != "mixed_changes" {
		t.Fatalf("changed state was not classified as mixed: %+v", changed)
	}
	third, err := Ensure(game, state, "blue_reflection_quartet", paths)
	if err != nil {
		t.Fatal(err)
	}
	if third.Action != ActionCreated || third.Manifest.BaselineID == first.Manifest.BaselineID {
		t.Fatalf("changed state did not create a versioned baseline: first=%s third=%s", first.Manifest.BaselineID, third.Manifest.BaselineID)
	}
	final, err := Inspect(game, state, "blue_reflection_quartet")
	if err != nil {
		t.Fatal(err)
	}
	if final.Status != "matches_known_baseline" || final.BaselineCount != 2 || final.MatchingBaselineID != third.Manifest.BaselineID {
		t.Fatalf("new baseline was not recognized: %+v", final)
	}
	storedFirst, err := os.ReadFile(first.StoredFiles["Data/PACK11.PAK"])
	if err != nil {
		t.Fatal(err)
	}
	if string(storedFirst) != "version-one-event" {
		t.Fatalf("old baseline was modified: %q", storedFirst)
	}
}

func TestEnsureRejectsSymlinkTarget(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	outside := filepath.Join(root, "outside")
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(outside, []byte("outside"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(game, "Data", "PACK11.PAK")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if _, err := Ensure(game, state, "blue_reflection_quartet", []string{"Data/PACK11.PAK"}); err == nil {
		t.Fatal("symlink target was accepted")
	}
}

func TestEnsureWithInheritedDoesNotCaptureActiveModAsBaseline(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	managed := filepath.Join(game, "Data", "PACK11.PAK")
	newPath := filepath.Join(game, "Data", "PACK10_01.PAK")
	if err := os.WriteFile(managed, []byte("original-event"), 0o644); err != nil {
		t.Fatal(err)
	}
	first, err := Ensure(game, state, "blue_reflection_quartet", []string{"Data/PACK11.PAK"})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(managed, []byte("active-mod-event"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(newPath, []byte("current-shader"), 0o644); err != nil {
		t.Fatal(err)
	}

	extended, err := EnsureWithInherited(game, state, "blue_reflection_quartet", []string{"Data/PACK11.PAK", "Data/PACK10_01.PAK"}, first.ManifestPath)
	if err != nil {
		t.Fatal(err)
	}
	if extended.Manifest.Classification != "observed_preinstall_extended_from_active" {
		t.Fatalf("unexpected extended classification: %+v", extended.Manifest)
	}
	managedStored, err := os.ReadFile(extended.StoredFiles["Data/PACK11.PAK"])
	if err != nil {
		t.Fatal(err)
	}
	if string(managedStored) != "original-event" {
		t.Fatalf("active mod was captured as inherited baseline: %q", managedStored)
	}
	newStored, err := os.ReadFile(extended.StoredFiles["Data/PACK10_01.PAK"])
	if err != nil {
		t.Fatal(err)
	}
	if string(newStored) != "current-shader" {
		t.Fatalf("new unmanaged path was not observed: %q", newStored)
	}
}

func TestAdoptCurrentRecordsProvenanceAndRejectsAnalyticalArchive(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	if err := os.MkdirAll(filepath.Join(game, "DATA"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "DATA", "PACK01.PAK"), []byte("current"), 0o644); err != nil {
		t.Fatal(err)
	}
	result, err := AdoptCurrent(game, state, "blue_reflection_original", []string{"DATA/PACK01.PAK"}, AdoptionProvenance{
		AdoptionID: "adopt-test", PreviousStateArchive: "/tmp/old-state",
	})
	if err != nil {
		t.Fatal(err)
	}
	if result.Manifest.Classification != ClassificationManualAdoptCurrent || result.Manifest.CaptureMethod != "manual_adopt_current" {
		t.Fatalf("unexpected adoption provenance: %+v", result.Manifest)
	}
	if result.Manifest.SourceClassification != SourceCurrentInstallation || result.Manifest.AdoptionID != "adopt-test" {
		t.Fatalf("missing source provenance: %+v", result.Manifest)
	}
	if len(result.Manifest.Files) != 1 || result.Manifest.Files[0].SourceClassification != SourceCurrentInstallation || result.Manifest.Files[0].SourcePath == "" {
		t.Fatalf("missing file provenance: %+v", result.Manifest.Files)
	}
	if _, err := AdoptCurrent(game, filepath.Join(root, "bad-state"), "blue_reflection_original", []string{"DATA/PACK01.PAK_"}, AdoptionProvenance{}); err == nil {
		t.Fatal("analytical .PAK_ path was accepted as an adopted baseline target")
	}
}
