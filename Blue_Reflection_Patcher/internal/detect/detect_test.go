package detect

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func writeMarkers(t *testing.T, root string, markers []string) {
	t.Helper()
	for _, marker := range markers {
		path := filepath.Join(root, filepath.FromSlash(marker))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("pak"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDetectionByStructuralFiles(t *testing.T) {
	root := t.TempDir()
	required := []string{"Data/PACK11.PAK", "Data/PACK12.PAK"}
	writeMarkers(t, root, required)
	specs := []model.TargetSpec{{
		TargetID: "quartet", DisplayName: "Quartet", RequiredFiles: required,
	}}
	items, err := Detect(specs, []RootCandidate{{Path: root, Source: "current_directory"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].TargetID != "quartet" || items[0].Confidence != "structural_files" {
		t.Fatalf("unexpected detections: %+v", items)
	}
	if items[0].Source != "current_directory" || len(items[0].MatchedFiles) != 2 {
		t.Fatalf("unexpected detection metadata: %+v", items[0])
	}
}

func TestDetectionIsCaseInsensitive(t *testing.T) {
	root := t.TempDir()
	writeMarkers(t, root, []string{"data/pack01.pak", "data/pack02.pak"})
	specs := []model.TargetSpec{{
		TargetID: "second_light", DisplayName: "Second Light",
		RequiredFiles: []string{"Data/PACK01.PAK", "Data/PACK02.PAK"},
	}}
	items, err := Detect(specs, []RootCandidate{{Path: root, Source: "explicit_path"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].TargetID != "second_light" {
		t.Fatalf("unexpected detections: %+v", items)
	}
}

func TestFilePathUsesParentDirectory(t *testing.T) {
	root := t.TempDir()
	required := []string{"DATA/PACK01.PAK"}
	writeMarkers(t, root, required)
	launcher := filepath.Join(root, "Launcher.exe")
	if err := os.WriteFile(launcher, []byte("exe"), 0o755); err != nil {
		t.Fatal(err)
	}
	specs := []model.TargetSpec{{TargetID: "br1", DisplayName: "BR1", RequiredFiles: required}}
	items, err := Detect(specs, []RootCandidate{{Path: launcher, Source: "explicit_path"}})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Root != root {
		t.Fatalf("unexpected detections: %+v", items)
	}
}

func TestDuplicateCandidateKeepsFirstSource(t *testing.T) {
	root := t.TempDir()
	required := []string{"DATA/PACK01.PAK"}
	writeMarkers(t, root, required)
	specs := []model.TargetSpec{{TargetID: "br1", DisplayName: "BR1", RequiredFiles: required}}
	items, err := Detect(specs, []RootCandidate{
		{Path: root, Source: "current_directory"},
		{Path: root, Source: "explicit_path"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Source != "current_directory" {
		t.Fatalf("unexpected detections: %+v", items)
	}
}

func TestAmbiguousStructuralMatchFails(t *testing.T) {
	root := t.TempDir()
	writeMarkers(t, root, []string{"Data/A.PAK", "Data/B.PAK"})
	specs := []model.TargetSpec{
		{TargetID: "one", DisplayName: "One", RequiredFiles: []string{"Data/A.PAK"}},
		{TargetID: "two", DisplayName: "Two", RequiredFiles: []string{"Data/B.PAK"}},
	}
	if _, err := Detect(specs, []RootCandidate{{Path: root, Source: "explicit_path"}}); err == nil {
		t.Fatal("expected ambiguous detection error")
	}
}
