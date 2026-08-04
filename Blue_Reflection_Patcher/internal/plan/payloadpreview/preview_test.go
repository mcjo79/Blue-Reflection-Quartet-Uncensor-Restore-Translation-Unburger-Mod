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

func TestSelectedRestorationRequiresCompositionBuild(t *testing.T) {
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
	if preview.Status != "not_ready" || preview.Targets[0].Status != "not_ready" || preview.Targets[0].PendingModuleCount != 2 {
		t.Fatalf("missing composition build did not block the pair: %+v", preview)
	}
	for _, module := range preview.Targets[0].Modules {
		if module.ConnectionStatus != "composition_build_required" || module.Ready {
			t.Fatalf("unexpected paired module preview: %+v", module)
		}
	}
}

func writeSyntheticComposition(t *testing.T, root, game string, payloads map[string][]byte) {
	t.Helper()
	looseRelative := ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
	looseData := []byte("{\"status\":\"ok\"}\n")
	testWrite(t, filepath.Join(root, filepath.FromSlash(looseRelative)), looseData)

	profilePayloadRelative := ".local/build/quartet_restoration/synthetic/runtime-profile/Data/PACK11.PAK"
	profilePayload := []byte("runtime-profile-payload")
	testWrite(t, filepath.Join(root, filepath.FromSlash(profilePayloadRelative)), profilePayload)
	pack11Game := filepath.Join(game, "Data/PACK11.PAK")
	pack11Baseline, err := os.ReadFile(pack11Game)
	if err != nil {
		t.Fatal(err)
	}
	profileManifestRelative := ".local/build/quartet_restoration/core_profiles/runtime-profile.json"
	profileManifest := currentProfileManifest{
		SchemaVersion: 1, ProfileID: "runtime-profile", TargetRelativePath: "Data/PACK11.PAK",
		BaselineSHA256: digest(pack11Baseline), BaselineSize: int64(len(pack11Baseline)),
		ProfileSHA256: digest(profilePayload), ProfileSize: int64(len(profilePayload)),
		LocalProfilePath: profilePayloadRelative, RuntimeValidated: true, WorkstreamID: "quartet_restoration",
	}
	profileManifestData, err := json.MarshalIndent(profileManifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	profileManifestData = append(profileManifestData, byte('\n'))
	testWrite(t, filepath.Join(root, filepath.FromSlash(profileManifestRelative)), profileManifestData)

	archives := make([]compositionBuildArchive, 0, len(payloads))
	composed := 0
	passthrough := 0
	for relative, data := range payloads {
		outputRelative := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(relative)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), data)
		mode := "verified_translation_passthrough"
		status := "published_verified_translation_passthrough"
		full := false
		profiles := []string{}
		baseSourceKind := "verified_translation_archive"
		rawPath := filepath.Join(root, ".local/build/translation/archives", quartetTargetID, filepath.FromSlash(relative))
		rawData, rawErr := os.ReadFile(rawPath)
		baseHash := ""
		baseBytes := int64(0)
		if rawErr == nil {
			baseHash, baseBytes = digest(rawData), int64(len(rawData))
		}
		installedPath := filepath.Join(game, filepath.FromSlash(relative))
		installedData, installedErr := os.ReadFile(installedPath)
		if installedErr != nil {
			installedData = []byte("synthetic-installed-baseline-" + relative)
			testWrite(t, installedPath, installedData)
		}
		if relative == "Data/PACK11.PAK" || relative == "Data/PACK10_01.PAK" {
			mode = "member_overlay"
			status = "published_member_overlay_verified"
			full = true
			profiles = []string{"runtime-profile"}
			composed++
			if rawErr != nil {
				baseSourceKind = "installed_baseline_archive"
				baseHash, baseBytes = digest(installedData), int64(len(installedData))
			}
		} else {
			passthrough++
		}
		archives = append(archives, compositionBuildArchive{
			ArchiveRelativePath: relative, Mode: mode, BaseSourceKind: baseSourceKind,
			BaseSourcePath: filepath.ToSlash(filepath.Join(".local/build/translation/archives", quartetTargetID, filepath.FromSlash(relative))),
			BaseSHA256:     baseHash, BaseBytes: baseBytes,
			InstalledBaselineSHA256: digest(installedData), InstalledBaselineBytes: int64(len(installedData)),
			OutputPath: outputRelative, OutputSHA256: digest(data), OutputBytes: int64(len(data)), FullReextractVerified: full,
			ManifestDeclarationChecked: true, Status: status, ProfileIDs: profiles,
		})
	}
	repackPath := filepath.Join(root, filepath.FromSlash(repackReportRelative))
	repackData, err := os.ReadFile(repackPath)
	if err != nil {
		t.Fatal(err)
	}
	report := compositionBuildReport{
		Type: compositionReportType, FormatVersion: 2, Status: "ok",
		ProjectRoot: root, GameRoot: game, TargetID: quartetTargetID, CommitEnabled: false,
		PreflightStatus: "ready_for_composition_build", OutputRoot: compositionOutputRelative,
		EmbeddedReportPath:         compositionEmbeddedReportRelative,
		TranslationLooseReportPath: looseRelative, TranslationLooseReportSHA256: digest(looseData), TranslationLooseReportBytes: int64(len(looseData)),
		TranslationRepackReportPath: repackReportRelative, TranslationRepackReportSHA256: digest(repackData), TranslationRepackReportBytes: int64(len(repackData)),
		ProductionProfileIDs: []string{"runtime-profile"},
		ProfileInputs: []compositionBuildProfileInput{{
			ProfileID: "runtime-profile", ManifestPath: profileManifestRelative, ManifestSHA256: digest(profileManifestData), ManifestBytes: int64(len(profileManifestData)),
			PayloadPath: profilePayloadRelative, PayloadSHA256: digest(profilePayload), PayloadBytes: int64(len(profilePayload)),
			TargetRelativePath: "Data/PACK11.PAK", BaselineSHA256: digest(pack11Baseline), BaselineBytes: int64(len(pack11Baseline)), RuntimeValidated: true,
		}},
		Archives: archives, PublishedArchiveCount: len(archives), ComposedArchiveCount: composed,
		PassthroughArchiveCount: passthrough, FullReextractCount: composed, Errors: []string{},
	}
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, byte('\n'))
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionReportRelative)), data)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionEmbeddedReportRelative)), data)
}

func TestVerifiedCompositionReplacesBlindWholePakPreview(t *testing.T) {
	raw := map[string][]byte{
		"Data/PACK11.PAK":       []byte("raw-translation-event"),
		"Data/PACK12.PAK":       []byte("raw-translation-text"),
		"Data/PACK00_04_01.PAK": []byte("raw-title-marker"),
	}
	root, game := syntheticProject(t, quartetTargetID, raw)
	composed := map[string][]byte{
		"Data/PACK11.PAK":       []byte("composed-event"),
		"Data/PACK12.PAK":       []byte("composed-text"),
		"Data/PACK00_04_01.PAK": []byte("composed-title"),
		"Data/PACK10_01.PAK":    []byte("composed-restoration-only"),
	}
	writeSyntheticComposition(t, root, game, composed)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, DisplayName: "Quartet", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_restoration"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready" || preview.Targets[0].Status != "ready" || preview.Targets[0].PendingModuleCount != 0 || preview.Targets[0].ReadyArtifactCount != 4 {
		t.Fatalf("verified composition did not become transaction-preview ready: %+v", preview)
	}
	translation := preview.Targets[0].Modules[0]
	restoration := preview.Targets[0].Modules[1]
	if !translation.Ready || len(translation.Artifacts) != 4 || !restoration.Ready || len(restoration.Artifacts) != 0 {
		t.Fatalf("composition modules are wrong: translation=%+v restoration=%+v", translation, restoration)
	}
	for _, artifact := range translation.Artifacts {
		if !artifact.ReportVerified || !artifact.CompositionVerified || !artifact.TransactionReady {
			t.Fatalf("unverified composition artifact entered preview: %+v", artifact)
		}
		if filepath.Dir(artifact.SourcePath) == filepath.Dir(filepath.Join(root, ".local/build/translation/archives/blue_reflection_quartet/Data/PACK11.PAK")) {
			t.Fatalf("raw translation artifact was used instead of composition output: %+v", artifact)
		}
	}
}

func TestTamperedCompositionArtifactBlocksBothModules(t *testing.T) {
	raw := map[string][]byte{
		"Data/PACK11.PAK": []byte("raw-event"), "Data/PACK12.PAK": []byte("raw-text"), "Data/PACK00_04_01.PAK": []byte("raw-title"),
	}
	root, game := syntheticProject(t, quartetTargetID, raw)
	composed := map[string][]byte{
		"Data/PACK11.PAK": []byte("composed-event"), "Data/PACK12.PAK": []byte("composed-text"), "Data/PACK00_04_01.PAK": []byte("composed-title"),
	}
	writeSyntheticComposition(t, root, game, composed)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionOutputRelative), "Data/PACK11.PAK"), []byte("tampered"))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: quartetTargetID, Root: game, SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_restoration"}}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "partial" || preview.Targets[0].Modules[0].Ready || preview.Targets[0].Modules[1].Ready {
		t.Fatalf("tampered composition did not block both paired modules: %+v", preview)
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

func TestChangedTranslationReportInvalidatesComposition(t *testing.T) {
	raw := map[string][]byte{
		"Data/PACK11.PAK": []byte("raw-event"), "Data/PACK12.PAK": []byte("raw-text"), "Data/PACK00_04_01.PAK": []byte("raw-title"),
	}
	root, game := syntheticProject(t, quartetTargetID, raw)
	writeSyntheticComposition(t, root, game, map[string][]byte{
		"Data/PACK11.PAK": []byte("composed-event"), "Data/PACK12.PAK": []byte("composed-text"), "Data/PACK00_04_01.PAK": []byte("composed-title"),
	})
	repackPath := filepath.Join(root, filepath.FromSlash(repackReportRelative))
	data, err := os.ReadFile(repackPath)
	if err != nil {
		t.Fatal(err)
	}
	testWrite(t, repackPath, append(data, byte('\n')))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: quartetTargetID, Root: game, SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_restoration"}}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "not_ready" || preview.Targets[0].PendingModuleCount != 2 {
		t.Fatalf("stale translation report did not invalidate composition: %+v", preview)
	}
}

func TestExternallyChangedOverlayTargetIsBlocked(t *testing.T) {
	raw := map[string][]byte{
		"Data/PACK11.PAK": []byte("raw-event"), "Data/PACK12.PAK": []byte("raw-text"), "Data/PACK00_04_01.PAK": []byte("raw-title"),
	}
	root, game := syntheticProject(t, quartetTargetID, raw)
	writeSyntheticComposition(t, root, game, map[string][]byte{
		"Data/PACK11.PAK": []byte("composed-event"), "Data/PACK12.PAK": []byte("composed-text"), "Data/PACK00_04_01.PAK": []byte("composed-title"),
	})
	testWrite(t, filepath.Join(game, "Data/PACK11.PAK"), []byte("external-modification"))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: quartetTargetID, Root: game, SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_restoration"}}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "partial" || preview.Targets[0].Modules[0].Ready || preview.Targets[0].Modules[1].Ready {
		t.Fatalf("external target modification was not blocked: %+v", preview)
	}
}
