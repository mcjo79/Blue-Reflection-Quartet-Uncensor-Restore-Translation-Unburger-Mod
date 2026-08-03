package payloadpreview

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func testWrite(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func digest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func syntheticProject(t *testing.T, targetID string, artifacts map[string][]byte) (string, string) {
	t.Helper()
	root := t.TempDir()
	game := filepath.Join(root, "game")
	testWrite(t, filepath.Join(root, "workstreams/core/VERSION"), []byte("test\n"))
	testWrite(t, filepath.Join(root, "Blue_Reflection_Patcher/go.mod"), []byte("module test\n"))
	var archives []repackArchiveEntry
	for relative, data := range artifacts {
		outputRelative := filepath.ToSlash(filepath.Join(".local/build/translation/archives", targetID, filepath.FromSlash(relative)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), data)
		testWrite(t, filepath.Join(game, filepath.FromSlash(relative)), []byte("stock-"+relative))
		archives = append(archives, repackArchiveEntry{
			TargetID: targetID, ArchiveRelativePath: relative, OutputPath: outputRelative,
			OutputSHA256: digest(data), OutputBytes: int64(len(data)), Failures: []string{},
		})
	}
	reportData, err := json.Marshal(repackReport{Status: "ok", Archives: archives})
	if err != nil {
		t.Fatal(err)
	}
	testWrite(t, filepath.Join(root, filepath.FromSlash(repackReportRelative)), reportData)
	return root, game
}

func TestTranslationArtifactsAreVerifiedPreviewOnly(t *testing.T) {
	artifacts := map[string][]byte{
		"DATA/PACK01.PAK":      []byte("translated-event"),
		"DATA/PACK02_1.PAK":    []byte("translated-text"),
		"DATA/PACK00_04_1.PAK": []byte("title-marker"),
	}
	root, game := syntheticProject(t, "blue_reflection_original", artifacts)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: "blue_reflection_original", DisplayName: "BR1", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"blue_reflection_translation"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready" || preview.CommitEnabled {
		t.Fatalf("unexpected preview envelope: %+v", preview)
	}
	target := preview.Targets[0]
	if target.Status != "ready" || target.ReadyArtifactCount != 3 || target.PendingModuleCount != 0 {
		t.Fatalf("unexpected target preview: %+v", target)
	}
	for _, artifact := range target.Modules[0].Artifacts {
		if !artifact.ReportVerified || !artifact.TransactionReady || artifact.DesiredAction != "replace" {
			t.Fatalf("unexpected artifact preview: %+v", artifact)
		}
	}
}

func TestSelectedRestorationAdvertisesCompositionPreflight(t *testing.T) {
	artifacts := map[string][]byte{
		"Data/PACK11.PAK":       []byte("translated-event"),
		"Data/PACK12.PAK":       []byte("translated-text"),
		"Data/PACK00_04_01.PAK": []byte("title-marker"),
	}
	root, game := syntheticProject(t, "blue_reflection_quartet", artifacts)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: "blue_reflection_quartet", DisplayName: "Quartet", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_restoration"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "partial" || preview.Targets[0].Status != "partial" || preview.Targets[0].PendingModuleCount != 1 {
		t.Fatalf("restoration pending state was not preserved: %+v", preview)
	}
	if preview.Targets[0].Modules[1].ConnectionStatus != "composition_build_available" || preview.Targets[0].Modules[1].Ready {
		t.Fatalf("unexpected restoration module preview: %+v", preview.Targets[0].Modules[1])
	}
}

func TestTamperedBuildArtifactIsBlocked(t *testing.T) {
	artifacts := map[string][]byte{
		"DATA/PACK01.PAK":      []byte("translated-event"),
		"DATA/PACK02_1.PAK":    []byte("translated-text"),
		"DATA/PACK00_04_1.PAK": []byte("title-marker"),
	}
	root, game := syntheticProject(t, "blue_reflection_original", artifacts)
	path := filepath.Join(root, ".local/build/translation/archives/blue_reflection_original/DATA/PACK01.PAK")
	testWrite(t, path, []byte("tampered"))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: "blue_reflection_original", DisplayName: "BR1", Root: game,
		SelectedModuleIDs: []string{"blue_reflection_translation"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "partial" || preview.Targets[0].Modules[0].Ready {
		t.Fatalf("tampered artifact did not block the module: %+v", preview)
	}
	if preview.Targets[0].Modules[0].Artifacts[0].TransactionReady {
		t.Fatal("tampered artifact was marked transaction-ready")
	}
}

func TestCatalogIsValid(t *testing.T) {
	items, err := LoadCatalog()
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 5 {
		t.Fatalf("unexpected local payload mapping count: %d", len(items))
	}
}
