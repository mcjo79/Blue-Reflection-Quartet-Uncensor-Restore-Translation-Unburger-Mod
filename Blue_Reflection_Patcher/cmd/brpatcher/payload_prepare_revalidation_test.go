package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestPrepareRevalidatedPayloadTransactionAcceptsEquivalentCanonicalPlan(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	original := rebuildPayloadPreviewForPreparation
	rebuildPayloadPreviewForPreparation = func(_ string, selection model.SelectionResult) (payloadpreview.Preview, error) {
		if len(selection.Targets) != 1 || len(selection.Targets[0].SelectedModuleIDs) != 1 {
			t.Fatalf("unexpected revalidation selection: %+v", selection)
		}
		fresh := preview
		fresh.GeneratedUTC = time.Now().UTC().Add(time.Second)
		return fresh, nil
	}
	defer func() { rebuildPayloadPreviewForPreparation = original }()

	report, err := prepareRevalidatedPayloadTransaction(preview)
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "prepared" || !report.PreviewRevalidated {
		t.Fatalf("preview was not revalidated before preparation: %+v", report)
	}
	if report.PreviewPlanSHA256 == "" || report.PreviewPlanSHA256 != report.ConfirmedPreviewPlanSHA256 {
		t.Fatalf("unexpected preview plan fingerprints: %+v", report)
	}
	if _, err := transaction.DiscardPrepared(report.JournalPath); err != nil {
		t.Fatal(err)
	}
}

func TestPrepareRevalidatedPayloadTransactionRejectsChangedPlanBeforeStateCreation(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	original := rebuildPayloadPreviewForPreparation
	rebuildPayloadPreviewForPreparation = func(_ string, _ model.SelectionResult) (payloadpreview.Preview, error) {
		fresh := preview
		fresh.GeneratedUTC = time.Now().UTC().Add(time.Second)
		fresh.Targets[0].Modules[0].Artifacts[0].SourceSHA256 = strings.Repeat("f", 64)
		return fresh, nil
	}
	defer func() { rebuildPayloadPreviewForPreparation = original }()

	_, err := prepareRevalidatedPayloadTransaction(preview)
	if err == nil || !strings.Contains(err.Error(), "payload plan changed after confirmation") {
		t.Fatalf("changed plan was not rejected: %v", err)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("revalidation failure modified game target: %q", got)
	}
	if entries, readErr := os.ReadDir(filepath.Join(state, "transactions")); readErr == nil && len(entries) != 0 {
		t.Fatalf("revalidation failure created transaction state: %v", entries)
	}
}

func TestSelectionRequestsExactQuartetCompositionModules(t *testing.T) {
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: "blue_reflection_quartet", Root: "/game",
		SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_legacy_dlc"},
	}}}
	root, modules, requested := selectionRequestsQuartetComposition(selection)
	if !requested || root != "/game" || !sameQuartetCompositionModules(modules, []string{"blue_reflection_translation", "quartet_legacy_dlc"}) {
		t.Fatalf("Translation+Legacy DLC composition selection was not preserved: root=%q modules=%v requested=%v", root, modules, requested)
	}

	selection.Targets[0].SelectedModuleIDs = []string{"blue_reflection_translation"}
	if _, _, requested := selectionRequestsQuartetComposition(selection); requested {
		t.Fatal("Translation-only selection unexpectedly requested composition")
	}

	selection.Targets[0].SelectedModuleIDs = []string{"quartet_restoration", "quartet_legacy_dlc"}
	_, modules, requested = selectionRequestsQuartetComposition(selection)
	if !requested || !sameQuartetCompositionModules(modules, []string{"quartet_restoration", "quartet_legacy_dlc"}) {
		t.Fatalf("Restoration+Legacy DLC composition selection was not preserved: modules=%v requested=%v", modules, requested)
	}
}
