package detect

import (
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func TestManualDetectionByMarkers(t *testing.T) {
	root := t.TempDir()
	markers := []string{"Data/PACK11.PAK", "Data/PACK12.PAK"}
	for _, marker := range markers {
		path := filepath.Join(root, filepath.FromSlash(marker))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("pak"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	specs := []model.TargetSpec{{
		TargetID: "quartet", DisplayName: "Quartet", SteamAppID: 1, Markers: markers,
	}}
	items, err := Detect(specs, []string{root})
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].TargetID != "quartet" || items[0].Confidence != "markers_only" {
		t.Fatalf("unexpected detections: %+v", items)
	}
}
