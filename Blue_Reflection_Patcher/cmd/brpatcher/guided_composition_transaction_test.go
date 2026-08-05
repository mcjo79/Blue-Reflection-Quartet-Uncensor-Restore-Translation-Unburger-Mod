package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestGuidedTranslationLegacyDLCPrepareCreatesOneTenFileTransaction(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	relatives := []string{
		"Data/PACK00_04_01.PAK",
		"Data/PACK01_01.PAK",
		"Data/PACK01_02.PAK",
		"Data/PACK01_03.PAK",
		"Data/PACK02_01.PAK",
		"Data/PACK02_02.PAK",
		"Data/PACK02_03.PAK",
		"Data/PACK10_02.PAK",
		"Data/PACK11.PAK",
		"Data/PACK12.PAK",
	}
	artifacts := make([]payloadpreview.ArtifactPreview, 0, len(relatives))
	for index, relative := range relatives {
		source := filepath.Join(root, "composition", filepath.FromSlash(relative))
		target := filepath.Join(game, filepath.FromSlash(relative))
		mustWriteTestFile(t, source, []byte(fmt.Sprintf("composed-%02d", index)))
		mustWriteTestFile(t, target, []byte(fmt.Sprintf("baseline-%02d", index)))
		sourceHash, _ := hashRegularFile(source)
		targetHash, _ := hashRegularFile(target)
		sourceInfo, _ := os.Stat(source)
		targetInfo, _ := os.Stat(target)
		artifacts = append(artifacts, payloadpreview.ArtifactPreview{
			ModuleID: "blue_reflection_translation", RelativePath: relative,
			SourcePath: source, SourceSHA256: sourceHash, SourceBytes: sourceInfo.Size(),
			ReportSHA256: sourceHash, ReportBytes: sourceInfo.Size(), ReportVerified: true,
			CompositionVerified: true, SourceReport: ".local/reports/core/BR_QUARTET_COMPOSITION_BUILD_REPORT.json",
			TargetPath: target, TargetExists: true, TargetSHA256: targetHash, TargetBytes: targetInfo.Size(),
			DesiredAction: "replace", TransactionReady: true, Status: "ready",
		})
	}
	preview := payloadpreview.Preview{
		Type: payloadpreview.PreviewType, FormatVersion: payloadpreview.PreviewFormatVersion,
		Status: "ready", GeneratedUTC: time.Now().UTC(), ProjectRoot: root,
		CompositionReport: ".local/reports/core/BR_QUARTET_COMPOSITION_BUILD_REPORT.json",
		CommitEnabled:     false,
		Targets: []payloadpreview.TargetPreview{{
			TargetID: "blue_reflection_quartet", DisplayName: "BLUE REFLECTION Quartet", GameRoot: game,
			DetectionSource: "explicit_path", StateDirectory: state, Status: "ready",
			SelectedModules:    []string{"blue_reflection_translation", "quartet_legacy_dlc"},
			ReadyArtifactCount: len(artifacts), PendingModuleCount: 0,
			Modules: []payloadpreview.ModulePreview{
				{ModuleID: "blue_reflection_translation", SourceKind: "verified_content_aware_composition", ConnectionStatus: "connected_composition_preview_only", Ready: true, Artifacts: artifacts},
				{ModuleID: "quartet_legacy_dlc", SourceKind: "verified_content_aware_composition", ConnectionStatus: "connected_composition_preview_only", Ready: true, Artifacts: []payloadpreview.ArtifactPreview{}},
			},
		}},
	}

	original := rebuildPayloadPreviewForPreparation
	rebuildPayloadPreviewForPreparation = func(_ string, selection model.SelectionResult) (payloadpreview.Preview, error) {
		if len(selection.Targets) != 1 || !sameQuartetCompositionModules(selection.Targets[0].SelectedModuleIDs, preview.Targets[0].SelectedModules) {
			t.Fatalf("unexpected preparation selection: %+v", selection)
		}
		fresh := preview
		fresh.GeneratedUTC = time.Now().UTC().Add(time.Second)
		return fresh, nil
	}
	defer func() { rebuildPayloadPreviewForPreparation = original }()

	var output bytes.Buffer
	result, err := executeGuidedPayloadAction(preview, guidedActionPrepare, &output)
	if err != nil {
		t.Fatal(err)
	}
	if result.PrepareReport.Status != "prepared" || result.PrepareReport.PreparedChangeCount != 10 || !result.PrepareReport.PreviewRevalidated {
		t.Fatalf("unexpected guided composition preparation: %+v", result.PrepareReport)
	}
	if !strings.Contains(output.String(), "Transaction preparation") {
		t.Fatalf("guided output did not report preparation: %s", output.String())
	}
	journal, err := transaction.Load(result.PrepareReport.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if len(journal.Files) != 10 || !sameQuartetCompositionModules(journal.SelectedModules, []string{"blue_reflection_translation", "quartet_legacy_dlc"}) {
		t.Fatalf("unexpected single composition journal: %+v", journal)
	}
	seen := map[string]int{}
	for _, file := range journal.Files {
		seen[strings.ToLower(filepath.ToSlash(file.RelativePath))]++
		if got, _ := os.ReadFile(filepath.Join(game, filepath.FromSlash(file.RelativePath))); !strings.HasPrefix(string(got), "baseline-") {
			t.Fatalf("prepare modified game file %s: %q", file.RelativePath, got)
		}
	}
	if seen["data/pack12.pak"] != 1 || seen["data/pack10_02.pak"] != 1 {
		t.Fatalf("shared composition paths were duplicated or missing: %+v", seen)
	}
	if _, err := transaction.DiscardPrepared(result.PrepareReport.JournalPath); err != nil {
		t.Fatal(err)
	}
}
