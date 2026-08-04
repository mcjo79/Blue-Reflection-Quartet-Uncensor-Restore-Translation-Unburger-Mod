package archivepolicy

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAnalyticalArchiveRecognitionIsExactAndCaseInsensitive(t *testing.T) {
	for _, path := range []string{"DATA/PACK00_02.PAK_", "data/example.pak_"} {
		if !IsAnalyticalArchivePath(path) {
			t.Fatalf("analytical archive was not recognized: %s", path)
		}
	}
	for _, path := range []string{"DATA/PACK00_02.PAK", "DATA/PACK00_02.PAK.bak", "DATA/notpak_"} {
		if IsAnalyticalArchivePath(path) {
			t.Fatalf("ordinary path was misclassified: %s", path)
		}
	}
}

func TestFindAnalyticalArchivesReportsSiblingWithoutHashing(t *testing.T) {
	root := t.TempDir()
	data := filepath.Join(root, "DATA")
	if err := os.MkdirAll(data, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(data, "PACK00_02.PAK"), []byte("official"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(data, "PACK00_02.PAK_"), []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	items, err := FindAnalyticalArchives(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].RelativePath != "DATA/PACK00_02.PAK_" || !items[0].ProductionExists {
		t.Fatalf("unexpected analytical archive report: %+v", items)
	}
	if items[0].ProductionRelativePath != "DATA/PACK00_02.PAK" || items[0].Classification != "ignored_analytical_archive" {
		t.Fatalf("unexpected analytical archive metadata: %+v", items[0])
	}
}

func TestFindAnalyticalArchivesResolvesLegacyDirectorySibling(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "DATA", "legacy"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "DATA", "legacy", "PACK00_02.PAK_"), []byte("old"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "DATA", "PACK00_02.PAK"), []byte("official"), 0o644); err != nil {
		t.Fatal(err)
	}
	items, err := FindAnalyticalArchives(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("expected one analytical archive, got %d", len(items))
	}
	if items[0].ProductionRelativePath != "DATA/PACK00_02.PAK" || !items[0].ProductionExists {
		t.Fatalf("legacy analytical sibling was not resolved to DATA production file: %+v", items[0])
	}
}
