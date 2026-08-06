package payloadpreview

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
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
	testWrite(t, filepath.Join(root, "workstreams/translation/VERSION"), []byte("0.0.113\n"))
	testWrite(t, filepath.Join(root, "workstreams/translation_tooling/VERSION"), []byte("0.0.54\n"))
	testWrite(t, filepath.Join(root, "Blue_Reflection_Patcher/go.mod"), []byte("module test\n"))
	looseRelative := ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
	looseData := []byte("{\"type\":\"br_translation_loose_build_report\",\"format_version\":2,\"status\":\"ok\"}\n")
	testWrite(t, filepath.Join(root, filepath.FromSlash(looseRelative)), looseData)
	var archives []repackArchiveEntry
	if targetID == quartetTargetID {
		for _, relative := range []string{
			"Data/PACK11.PAK", "Data/PACK12.PAK", "Data/PACK01_01.PAK", "Data/PACK02_01.PAK",
			"Data/PACK01_02.PAK", "Data/PACK02_02.PAK", "Data/PACK01_03.PAK", "Data/PACK02_03.PAK",
			"Data/PACK00_04_01.PAK",
		} {
			if _, ok := artifacts[relative]; !ok {
				artifacts[relative] = []byte("translated-" + relative)
			}
		}
	}
	for relative, data := range artifacts {
		buildTargetID := targetID
		if targetID == quartetTargetID {
			switch relative {
			case "Data/PACK01_01.PAK", "Data/PACK02_01.PAK":
				buildTargetID = "blue_reflection_ray_quartet"
			case "Data/PACK01_02.PAK", "Data/PACK02_02.PAK":
				buildTargetID = "blue_reflection_sun_quartet"
			case "Data/PACK01_03.PAK", "Data/PACK02_03.PAK":
				buildTargetID = "second_light_quartet"
			}
		}
		outputRelative := filepath.ToSlash(filepath.Join(".local/build/translation/archives", buildTargetID, filepath.FromSlash(relative)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), data)
		testWrite(t, filepath.Join(game, filepath.FromSlash(relative)), []byte("stock-"+relative))
		sourcePolicy := "current_installation_baseline_extraction"
		if relative == "DATA/PACK00_04_1.PAK" || relative == "Data/PACK00_04_01.PAK" {
			sourcePolicy = "current_installation_baseline_extraction_plus_verified_marker_overlay"
		}
		archives = append(archives, repackArchiveEntry{
			TargetID: buildTargetID, ArchiveRelativePath: relative, OutputPath: outputRelative,
			OutputSHA256: digest(data), OutputBytes: int64(len(data)), Failures: []string{},
			SourcePolicy: sourcePolicy, SourceArchiveSHA256: digest([]byte("baseline-" + relative)), SourceArchiveBytes: 1,
			FullReextractVerified: true,
		})
	}
	reportData, err := json.Marshal(repackReport{
		Type: translationRepackReportType, FormatVersion: 2, Status: "ok",
		TranslationVersion: "0.0.113", TranslationToolingVersion: "0.0.54", MinimumTranslationVersion: "0.0.113",
		CanonicalInputFingerprint: digest([]byte("inputs")), LooseReportPath: looseRelative,
		LooseReportSHA256: digest(looseData), LooseReportBytes: int64(len(looseData)), Archives: archives,
	})
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
	looseData, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(looseRelative)))
	if err != nil {
		t.Fatal(err)
	}
	for _, relative := range []string{
		"Data/PACK11.PAK", "Data/PACK12.PAK", "Data/PACK01_01.PAK", "Data/PACK02_01.PAK",
		"Data/PACK01_02.PAK", "Data/PACK02_02.PAK", "Data/PACK01_03.PAK", "Data/PACK02_03.PAK",
		"Data/PACK00_04_01.PAK",
	} {
		if _, ok := payloads[relative]; ok {
			continue
		}
		var buildTargetID = quartetTargetID
		switch relative {
		case "Data/PACK01_01.PAK", "Data/PACK02_01.PAK":
			buildTargetID = "blue_reflection_ray_quartet"
		case "Data/PACK01_02.PAK", "Data/PACK02_02.PAK":
			buildTargetID = "blue_reflection_sun_quartet"
		case "Data/PACK01_03.PAK", "Data/PACK02_03.PAK":
			buildTargetID = "second_light_quartet"
		}
		path := filepath.Join(root, ".local/build/translation/archives", buildTargetID, filepath.FromSlash(relative))
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			t.Fatal(readErr)
		}
		payloads[relative] = data
	}

	profileInputs := []compositionBuildProfileInput{}
	profileIDs := []string{}
	profileByTarget := map[string]string{}
	addProfile := func(profileID, targetRelative string) {
		profilePayloadRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/synthetic", profileID, filepath.FromSlash(targetRelative)))
		profilePayload := []byte("profile-payload-" + profileID)
		testWrite(t, filepath.Join(root, filepath.FromSlash(profilePayloadRelative)), profilePayload)
		gamePath := filepath.Join(game, filepath.FromSlash(targetRelative))
		baseline, readErr := os.ReadFile(gamePath)
		if readErr != nil {
			baseline = []byte("synthetic-installed-baseline-" + targetRelative)
			testWrite(t, gamePath, baseline)
		}
		profileManifestRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/core_profiles", profileID+".json"))
		profileManifest := currentProfileManifest{
			SchemaVersion: 1, ProfileID: profileID, TargetRelativePath: targetRelative,
			BaselineSHA256: digest(baseline), BaselineSize: int64(len(baseline)),
			ProfileSHA256: digest(profilePayload), ProfileSize: int64(len(profilePayload)),
			LocalProfilePath: profilePayloadRelative, RuntimeValidated: true, WorkstreamID: "quartet_restoration",
		}
		profileManifestData, marshalErr := json.MarshalIndent(profileManifest, "", "  ")
		if marshalErr != nil {
			t.Fatal(marshalErr)
		}
		profileManifestData = append(profileManifestData, byte('\n'))
		testWrite(t, filepath.Join(root, filepath.FromSlash(profileManifestRelative)), profileManifestData)
		profileIDs = append(profileIDs, profileID)
		profileByTarget[targetRelative] = profileID
		profileInputs = append(profileInputs, compositionBuildProfileInput{
			ProfileID: profileID, ManifestPath: profileManifestRelative, ManifestSHA256: digest(profileManifestData), ManifestBytes: int64(len(profileManifestData)),
			PayloadPath: profilePayloadRelative, PayloadSHA256: digest(profilePayload), PayloadBytes: int64(len(profilePayload)),
			TargetRelativePath: targetRelative, BaselineSHA256: digest(baseline), BaselineBytes: int64(len(baseline)), RuntimeValidated: true,
		})
	}
	addProfile("runtime-profile", "Data/PACK11.PAK")
	if _, ok := payloads["Data/PACK10_01.PAK"]; ok {
		addProfile("runtime-profile-pack10", "Data/PACK10_01.PAK")
	}
	sort.Strings(profileIDs)
	sort.Slice(profileInputs, func(i, j int) bool { return profileInputs[i].ProfileID < profileInputs[j].ProfileID })

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
		buildTargetID := quartetTargetID
		switch relative {
		case "Data/PACK01_01.PAK", "Data/PACK02_01.PAK":
			buildTargetID = "blue_reflection_ray_quartet"
		case "Data/PACK01_02.PAK", "Data/PACK02_02.PAK":
			buildTargetID = "blue_reflection_sun_quartet"
		case "Data/PACK01_03.PAK", "Data/PACK02_03.PAK":
			buildTargetID = "second_light_quartet"
		}
		rawPath := filepath.Join(root, ".local/build/translation/archives", buildTargetID, filepath.FromSlash(relative))
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
		if profileID, ok := profileByTarget[relative]; ok {
			mode = "member_overlay"
			status = "published_member_overlay_verified"
			full = true
			profiles = []string{profileID}
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
			BaseSourcePath: filepath.ToSlash(filepath.Join(".local/build/translation/archives", buildTargetID, filepath.FromSlash(relative))),
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
		Type: compositionReportType, FormatVersion: 4, Status: "ok",
		SelectedModules: []string{"blue_reflection_translation", "quartet_restoration"},
		ProjectRoot:     root, GameRoot: game, TargetID: quartetTargetID, CommitEnabled: false,
		PreflightStatus: "ready_for_composition_build", OutputRoot: compositionOutputRelative,
		EmbeddedReportPath:         compositionEmbeddedReportRelative,
		TranslationLooseReportPath: looseRelative, TranslationLooseReportSHA256: digest(looseData), TranslationLooseReportBytes: int64(len(looseData)),
		TranslationRepackReportPath: repackReportRelative, TranslationRepackReportSHA256: digest(repackData), TranslationRepackReportBytes: int64(len(repackData)),
		ProductionProfileIDs: profileIDs,
		ProfileInputs:        profileInputs,
		Archives:             archives, PublishedArchiveCount: len(archives), ComposedArchiveCount: composed,
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
	if preview.Status != "ready" || preview.Targets[0].Status != "ready" || preview.Targets[0].PendingModuleCount != 0 || preview.Targets[0].ReadyArtifactCount != 10 {
		t.Fatalf("verified composition did not become transaction-preview ready: %+v", preview)
	}
	translation := preview.Targets[0].Modules[0]
	restoration := preview.Targets[0].Modules[1]
	if !translation.Ready || len(translation.Artifacts) != 10 || !restoration.Ready || len(restoration.Artifacts) != 0 {
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

func addSyntheticLegacyDLCContract(t *testing.T, root, game string) LegacyDLCCompositionContract {
	t.Helper()
	policy, err := loadLegacyDLCPolicy()
	if err != nil {
		t.Fatal(err)
	}
	family, ok := legacyDLCFamily(policy, "bkn_dry")
	if !ok {
		t.Fatal("missing bkn_dry policy")
	}
	members := []string{"costume_pc00_bkn"}
	evidenceRelative := ".local/reports/quartet_legacy_dlc/evidence/synthetic.json"
	evidence := []byte(`{"type":"synthetic"}` + "\n")
	testWrite(t, filepath.Join(root, filepath.FromSlash(evidenceRelative)), evidence)
	manifest := legacyDLCManifest{
		Type: legacyDLCManifestType, FormatVersion: legacyDLCManifestFormatVersion,
		FamilyID: "bkn_dry", Generation: 1, Members: members,
		SourceKind: legacyDLCSourceKind, TargetID: quartetTargetID,
		Transaction:   legacyDLCManifestTransaction{Group: family.TransactionGroup, AllOrNone: true},
		Provenance:    legacyDLCManifestProvenance{WorkstreamID: "quartet_legacy_dlc", WorkstreamVersion: "fixture", EvidenceRelativePath: evidenceRelative, EvidenceSHA256: digest(evidence)},
		Authorization: legacyDLCManifestAuthorization{CoreHandoffReady: true},
	}
	candidateData := map[string][]byte{
		"Data/PACK10_02.PAK": []byte("legacy-candidate-pack10"),
		"Data/PACK12.PAK":    []byte("legacy-candidate-pack12"),
	}
	for _, policyArtifact := range family.Artifacts {
		relative := policyArtifact.TargetPath
		candidate := candidateData[relative]
		candidateRelative := filepath.ToSlash(filepath.Join(policy.CandidateRoot, "synthetic", filepath.Base(relative)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(candidateRelative)), candidate)
		baselinePath := filepath.Join(game, filepath.FromSlash(relative))
		baseline, readErr := os.ReadFile(baselinePath)
		if readErr != nil {
			baseline = []byte("stock-" + relative)
			testWrite(t, baselinePath, baseline)
		}
		added, changed, removed, deltaErr := expectedLegacyDLCMemberDelta(family, policyArtifact, members)
		if deltaErr != nil {
			t.Fatal(deltaErr)
		}
		manifest.Artifacts = append(manifest.Artifacts, legacyDLCManifestArtifact{
			TargetPath: relative, Operation: policyArtifact.Operation,
			CandidateRelativePath: candidateRelative, CandidateSize: int64(len(candidate)), CandidateSHA256: digest(candidate),
			BaselineSize: int64(len(baseline)), BaselineSHA256: digest(baseline),
			MemberDelta: legacyDLCManifestMemberDelta{Added: added, Changed: changed, Removed: removed},
		})
	}
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	testWrite(t, filepath.Join(root, filepath.FromSlash(policy.ManifestRelativePath)), append(data, '\n'))
	contract, err := LoadLegacyDLCCompositionContract(root, game)
	if err != nil {
		t.Fatal(err)
	}
	return contract
}

func writeSyntheticTranslationLegacyComposition(t *testing.T, root, game string) {
	t.Helper()
	contract := addSyntheticLegacyDLCContract(t, root, game)
	looseRelative := ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
	looseData, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(looseRelative)))
	if err != nil {
		t.Fatal(err)
	}
	repackData, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(repackReportRelative)))
	if err != nil {
		t.Fatal(err)
	}
	var repack repackReport
	if err := json.Unmarshal(repackData, &repack); err != nil {
		t.Fatal(err)
	}
	archives := []compositionBuildArchive{}
	composed := 0
	passthrough := 0
	for _, relative := range quartetTranslationArchives() {
		entry, ok := findReportEntry(repack, quartetTranslationBuildTarget(relative), relative)
		if !ok {
			t.Fatalf("missing synthetic translation entry: %s", relative)
		}
		baseData, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(entry.OutputPath)))
		if err != nil {
			t.Fatal(err)
		}
		outputData := baseData
		mode := "verified_translation_passthrough"
		status := "published_verified_translation_passthrough"
		full := false
		if relative == "Data/PACK12.PAK" {
			outputData = []byte("composed-translation-plus-legacy-pack12")
			mode = "member_overlay"
			status = "published_member_overlay_verified"
			full = true
			composed++
		} else {
			passthrough++
		}
		outputRelative := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(relative)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), outputData)
		installedData, err := os.ReadFile(filepath.Join(game, filepath.FromSlash(relative)))
		if err != nil {
			t.Fatal(err)
		}
		archives = append(archives, compositionBuildArchive{
			ArchiveRelativePath: relative, Mode: mode, BaseSourceKind: "verified_translation_archive",
			BaseSourcePath: entry.OutputPath, BaseSHA256: digest(baseData), BaseBytes: int64(len(baseData)),
			InstalledBaselineSHA256: digest(installedData), InstalledBaselineBytes: int64(len(installedData)),
			OutputPath: outputRelative, OutputSHA256: digest(outputData), OutputBytes: int64(len(outputData)),
			FullReextractVerified: full, ManifestDeclarationChecked: true, Status: status, ProfileIDs: []string{},
		})
	}
	legacyInputs := []compositionBuildLegacyDLCInput{}
	for _, item := range contract.Artifacts {
		legacyInputs = append(legacyInputs, compositionBuildLegacyDLCInput{
			ManifestPath: contract.ManifestPath, ManifestSHA256: contract.ManifestSHA256, ManifestBytes: contract.ManifestBytes,
			FamilyID: contract.FamilyID, Generation: contract.Generation, Members: append([]string{}, contract.Members...), TransactionGroup: contract.TransactionGroup,
			WorkstreamVersion: contract.WorkstreamVersion, ProvenanceEvidencePath: contract.ProvenanceEvidencePath, ProvenanceEvidenceHash: contract.ProvenanceEvidenceHash,
			ArchiveRelativePath: item.RelativePath, CandidatePath: item.CandidateRelativePath,
			CandidateSHA256: item.CandidateSHA256, CandidateBytes: item.CandidateSize,
			BaselinePath: item.BaselinePath, BaselineSHA256: item.BaselineSHA256, BaselineBytes: item.BaselineSize,
			AddedMembers: append([]string{}, item.AddedMembers...), ChangedMembers: append([]string{}, item.ChangedMembers...), RemovedMembers: append([]string{}, item.RemovedMembers...),
		})
		if item.RelativePath != "Data/PACK10_02.PAK" {
			continue
		}
		candidateData, err := os.ReadFile(item.CandidatePath)
		if err != nil {
			t.Fatal(err)
		}
		outputRelative := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(item.RelativePath)))
		testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), candidateData)
		archives = append(archives, compositionBuildArchive{
			ArchiveRelativePath: item.RelativePath, Mode: "verified_legacy_dlc_passthrough", BaseSourceKind: "verified_legacy_dlc_candidate",
			BaseSourcePath: item.CandidateRelativePath, BaseSHA256: item.CandidateSHA256, BaseBytes: item.CandidateSize,
			InstalledBaselineSHA256: item.BaselineSHA256, InstalledBaselineBytes: item.BaselineSize,
			OutputPath: outputRelative, OutputSHA256: item.CandidateSHA256, OutputBytes: item.CandidateSize,
			FullReextractVerified: false, ManifestDeclarationChecked: true, Status: "published_verified_legacy_dlc_passthrough", ProfileIDs: []string{},
		})
		passthrough++
	}
	sort.Slice(archives, func(i, j int) bool { return archives[i].ArchiveRelativePath < archives[j].ArchiveRelativePath })
	report := compositionBuildReport{
		Type: compositionReportType, FormatVersion: 4, Status: "ok",
		ProjectRoot: root, GameRoot: game, TargetID: quartetTargetID, CommitEnabled: false,
		SelectedModules: []string{"blue_reflection_translation", "quartet_legacy_dlc"},
		PreflightStatus: "ready_for_composition_build", OutputRoot: compositionOutputRelative,
		EmbeddedReportPath:         compositionEmbeddedReportRelative,
		TranslationLooseReportPath: looseRelative, TranslationLooseReportSHA256: digest(looseData), TranslationLooseReportBytes: int64(len(looseData)),
		TranslationRepackReportPath: repackReportRelative, TranslationRepackReportSHA256: digest(repackData), TranslationRepackReportBytes: int64(len(repackData)),
		ProductionProfileIDs: []string{}, ProfileInputs: []compositionBuildProfileInput{}, LegacyDLCInputs: legacyInputs,
		Archives: archives, PublishedArchiveCount: len(archives), ComposedArchiveCount: composed,
		PassthroughArchiveCount: passthrough, FullReextractCount: composed, Errors: []string{},
	}
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionReportRelative)), data)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionEmbeddedReportRelative)), data)
}

func TestTranslationPlusLegacyDLCUsesOneVerifiedCompositionSet(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{})
	writeSyntheticTranslationLegacyComposition(t, root, game)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, DisplayName: "Quartet", Root: game, DetectionSource: "test",
		SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_legacy_dlc"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.CommitEnabled || preview.Status != "ready" || len(preview.Targets) != 1 {
		t.Fatalf("unexpected T+D preview: %+v", preview)
	}
	target := preview.Targets[0]
	if target.ReadyArtifactCount != 10 || target.PendingModuleCount != 0 || len(target.Modules) != 2 {
		t.Fatalf("unexpected T+D target: %+v", target)
	}
	if !target.Modules[0].Ready || len(target.Modules[0].Artifacts) != 10 || !target.Modules[1].Ready || len(target.Modules[1].Artifacts) != 0 {
		t.Fatalf("shared artifacts were not assigned once: %+v", target.Modules)
	}
	seen := map[string]bool{}
	for _, artifact := range target.Modules[0].Artifacts {
		key := strings.ToLower(artifact.RelativePath)
		if seen[key] {
			t.Fatalf("duplicate transaction path: %s", artifact.RelativePath)
		}
		seen[key] = true
		if !artifact.TransactionReady || !artifact.CompositionVerified {
			t.Fatalf("unverified T+D artifact: %+v", artifact)
		}
	}
	if !seen[strings.ToLower("Data/PACK12.PAK")] || !seen[strings.ToLower("Data/PACK10_02.PAK")] {
		t.Fatalf("shared DLC paths missing: %v", seen)
	}
}

func TestTranslationPlusLegacyDLCWithoutCompositionNeverReturnsRawDuplicatePaths(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{})
	addSyntheticLegacyDLCContract(t, root, game)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, Root: game,
		SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_legacy_dlc"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "not_ready" || preview.Targets[0].ReadyArtifactCount != 0 || preview.Targets[0].PendingModuleCount != 2 {
		t.Fatalf("raw overlapping payloads escaped without composition: %+v", preview)
	}
	for _, module := range preview.Targets[0].Modules {
		if len(module.Artifacts) != 0 || module.Ready {
			t.Fatalf("raw artifact escaped composition gate: %+v", module)
		}
	}
}

func TestCompositionReportForDifferentModuleSelectionIsRejected(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{})
	writeSyntheticTranslationLegacyComposition(t, root, game)
	reportPath := filepath.Join(root, filepath.FromSlash(compositionReportRelative))
	data, err := os.ReadFile(reportPath)
	if err != nil {
		t.Fatal(err)
	}
	var report compositionBuildReport
	if err := json.Unmarshal(data, &report); err != nil {
		t.Fatal(err)
	}
	report.SelectedModules = []string{"blue_reflection_translation", "quartet_restoration"}
	data, _ = json.MarshalIndent(report, "", "  ")
	data = append(data, '\n')
	testWrite(t, reportPath, data)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionEmbeddedReportRelative)), data)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, Root: game,
		SelectedModuleIDs: []string{"blue_reflection_translation", "quartet_legacy_dlc"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "not_ready" || preview.Targets[0].ReadyArtifactCount != 0 {
		t.Fatalf("stale module selection was accepted: %+v", preview)
	}
}

func TestQuartetSevenCombinationPreviewMatrix(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{})
	writeSyntheticTranslationLegacyComposition(t, root, game)
	cases := []struct {
		name      string
		modules   []string
		status    string
		artifacts int
		pending   int
	}{
		{"translation", []string{"blue_reflection_translation"}, "ready", 9, 0},
		{"restoration", []string{"quartet_restoration"}, "not_ready", 0, 1},
		{"legacy_dlc", []string{"quartet_legacy_dlc"}, "ready", 2, 0},
		{"translation_restoration", []string{"blue_reflection_translation", "quartet_restoration"}, "not_ready", 0, 2},
		{"translation_legacy_dlc", []string{"blue_reflection_translation", "quartet_legacy_dlc"}, "ready", 10, 0},
		{"restoration_legacy_dlc", []string{"quartet_restoration", "quartet_legacy_dlc"}, "not_ready", 0, 2},
		{"all_three", []string{"blue_reflection_translation", "quartet_restoration", "quartet_legacy_dlc"}, "not_ready", 0, 3},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			selection := model.SelectionResult{Targets: []model.TargetSelection{{
				TargetID: quartetTargetID, Root: game, SelectedModuleIDs: tc.modules,
			}}}
			preview, err := Build(root, filepath.Join(root, "state"), selection)
			if err != nil {
				t.Fatal(err)
			}
			if preview.CommitEnabled || preview.Status != tc.status || len(preview.Targets) != 1 {
				t.Fatalf("unexpected matrix preview: %+v", preview)
			}
			target := preview.Targets[0]
			if target.ReadyArtifactCount != tc.artifacts || target.PendingModuleCount != tc.pending {
				t.Fatalf("unexpected matrix target: %+v", target)
			}
		})
	}
}

func writeSyntheticRestorationRuntimeTestComposition(t *testing.T, root, game string) {
	t.Helper()
	const targetRelative = "Data/PACK10_01.PAK"
	const profileID = "candidate_runtime_test_profile"
	baseline := []byte("stock PACK10_01 baseline\n")
	output := []byte("stock PACK10_01 baseline plus candidate overlay\n")
	profilePayload := []byte("candidate profile payload\n")
	testWrite(t, filepath.Join(game, filepath.FromSlash(targetRelative)), baseline)

	profilePayloadRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/runtime_test", profileID, filepath.FromSlash(targetRelative)))
	testWrite(t, filepath.Join(root, filepath.FromSlash(profilePayloadRelative)), profilePayload)
	profileManifestRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/core_profiles/generated", profileID+".json"))
	profileManifest := currentProfileManifest{
		SchemaVersion: 1, ProfileID: profileID, TargetRelativePath: targetRelative,
		BaselineSHA256: digest(baseline), BaselineSize: int64(len(baseline)),
		ProfileSHA256: digest(profilePayload), ProfileSize: int64(len(profilePayload)),
		LocalProfilePath: profilePayloadRelative, RuntimeValidated: false, WorkstreamID: "quartet_restoration",
	}
	profileManifestData, err := json.MarshalIndent(profileManifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	profileManifestData = append(profileManifestData, byte('\n'))
	testWrite(t, filepath.Join(root, filepath.FromSlash(profileManifestRelative)), profileManifestData)

	outputRelative := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(targetRelative)))
	testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), output)
	report := compositionBuildReport{
		Type: compositionReportType, FormatVersion: 4, Status: "ok",
		ProjectRoot: root, GameRoot: game, TargetID: quartetTargetID, CommitEnabled: false,
		SelectedModules:          []string{"quartet_restoration"},
		PreflightStatus:          "ready_for_runtime_test_composition_build",
		OutputRoot:               compositionOutputRelative,
		EmbeddedReportPath:       compositionEmbeddedReportRelative,
		RuntimeTestProfileIDs:    []string{profileID},
		SelectedProfileIDs:       []string{profileID},
		RestorationProfilePolicy: "all-current-candidates-for-runtime-test",
		RuntimeTestOnly:          true,
		ProfileInputs: []compositionBuildProfileInput{{
			ProfileID: profileID, ManifestPath: profileManifestRelative,
			ManifestSHA256: digest(profileManifestData), ManifestBytes: int64(len(profileManifestData)),
			PayloadPath: profilePayloadRelative, PayloadSHA256: digest(profilePayload), PayloadBytes: int64(len(profilePayload)),
			TargetRelativePath: targetRelative, BaselineSHA256: digest(baseline), BaselineBytes: int64(len(baseline)), RuntimeValidated: false,
		}},
		Archives: []compositionBuildArchive{{
			ArchiveRelativePath: targetRelative, Mode: "member_overlay", BaseSourceKind: "installed_game_baseline",
			BaseSourcePath: targetRelative, BaseSHA256: digest(baseline), BaseBytes: int64(len(baseline)),
			InstalledBaselineSHA256: digest(baseline), InstalledBaselineBytes: int64(len(baseline)),
			OutputPath: outputRelative, OutputSHA256: digest(output), OutputBytes: int64(len(output)),
			FullReextractVerified: true, ManifestDeclarationChecked: true,
			Status: "published_member_overlay_verified", ProfileIDs: []string{profileID},
		}},
		PublishedArchiveCount: 1, ComposedArchiveCount: 1, PassthroughArchiveCount: 0, FullReextractCount: 1,
		Errors: []string{},
	}
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, byte('\n'))
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionReportRelative)), data)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionEmbeddedReportRelative)), data)
}

func TestRestorationOnlyRuntimeTestCompositionBecomesCanonicalPreviewReady(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{"Data/PACK10_01.PAK": []byte("unused translation fixture")})
	writeSyntheticRestorationRuntimeTestComposition(t, root, game)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, DisplayName: "Quartet", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"quartet_restoration"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready" || preview.Targets[0].Status != "ready" || preview.Targets[0].ReadyArtifactCount != 1 || preview.Targets[0].PendingModuleCount != 0 {
		t.Fatalf("runtime-test Restoration-only preview is not ready: %+v", preview)
	}
	if len(preview.Targets[0].Modules) != 1 || preview.Targets[0].Modules[0].ModuleID != "quartet_restoration" || !preview.Targets[0].Modules[0].Ready || len(preview.Targets[0].Modules[0].Artifacts) != 1 {
		t.Fatalf("runtime-test module preview is wrong: %+v", preview.Targets[0].Modules)
	}
	artifact := preview.Targets[0].Modules[0].Artifacts[0]
	if artifact.RelativePath != "Data/PACK10_01.PAK" || !artifact.CompositionVerified || !artifact.TransactionReady || artifact.DesiredAction != "replace" {
		t.Fatalf("runtime-test artifact is not transaction-preview ready: %+v", artifact)
	}
	if preview.CommitEnabled {
		t.Fatal("runtime-test payload preview unexpectedly enabled commit")
	}
}

func TestRuntimeTestCompositionRejectsProfileSetDrift(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{"Data/PACK10_01.PAK": []byte("unused translation fixture")})
	writeSyntheticRestorationRuntimeTestComposition(t, root, game)
	extraManifest := currentProfileManifest{
		SchemaVersion: 1, ProfileID: "late_candidate", TargetRelativePath: "Data/PACK10_01.PAK",
		BaselineSHA256: digest([]byte("stock PACK10_01 baseline\n")), BaselineSize: int64(len([]byte("stock PACK10_01 baseline\n"))),
		ProfileSHA256: digest([]byte("late payload")), ProfileSize: int64(len([]byte("late payload"))),
		LocalProfilePath: ".local/build/quartet_restoration/runtime_test/late_candidate/Data/PACK10_01.PAK",
		RuntimeValidated: false, WorkstreamID: "quartet_restoration",
	}
	extraData, err := json.MarshalIndent(extraManifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	extraData = append(extraData, byte('\n'))
	testWrite(t, filepath.Join(root, ".local/build/quartet_restoration/core_profiles/generated/late_candidate.json"), extraData)
	testWrite(t, filepath.Join(root, filepath.FromSlash(extraManifest.LocalProfilePath)), []byte("late payload"))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, DisplayName: "Quartet", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"quartet_restoration"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "not_ready" || len(preview.Warnings) == 0 || !strings.Contains(strings.Join(preview.Warnings, " "), "all-candidate profile set changed") {
		t.Fatalf("profile-set drift did not invalidate runtime-test composition: %+v", preview)
	}
}

func writeSyntheticProductionRestorationPassthrough(t *testing.T, root, game string) {
	t.Helper()
	const profileID = "candidate-bathroom-b"
	const targetRelative = "Data/PACK10_03.PAK"
	baseline := []byte("stock-" + targetRelative)
	profilePayload := []byte("runtime-validated-bathroom-profile")
	profilePayloadRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/runtime_validated", profileID, filepath.FromSlash(targetRelative)))
	testWrite(t, filepath.Join(root, filepath.FromSlash(profilePayloadRelative)), profilePayload)
	profileManifestRelative := filepath.ToSlash(filepath.Join(".local/build/quartet_restoration/core_profiles/generated", profileID+".json"))
	profileManifest := currentProfileManifest{
		SchemaVersion: 1, ProfileID: profileID, TargetRelativePath: targetRelative,
		BaselineSHA256: digest(baseline), BaselineSize: int64(len(baseline)),
		ProfileSHA256: digest(profilePayload), ProfileSize: int64(len(profilePayload)),
		LocalProfilePath: profilePayloadRelative, RuntimeValidated: true, WorkstreamID: "quartet_restoration",
	}
	profileManifestData, err := json.MarshalIndent(profileManifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	profileManifestData = append(profileManifestData, '\n')
	testWrite(t, filepath.Join(root, filepath.FromSlash(profileManifestRelative)), profileManifestData)
	outputRelative := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(targetRelative)))
	testWrite(t, filepath.Join(root, filepath.FromSlash(outputRelative)), profilePayload)
	report := compositionBuildReport{
		Type: compositionReportType, FormatVersion: 4, Status: "ok",
		ProjectRoot: root, GameRoot: game, TargetID: quartetTargetID, CommitEnabled: false,
		SelectedModules: []string{"quartet_restoration"},
		PreflightStatus: "ready_for_composition_build", OutputRoot: compositionOutputRelative,
		EmbeddedReportPath:   compositionEmbeddedReportRelative,
		ProductionProfileIDs: []string{profileID}, SelectedProfileIDs: []string{profileID},
		RestorationProfilePolicy: "runtime-validated", RuntimeTestOnly: false,
		ProfileInputs: []compositionBuildProfileInput{{
			ProfileID: profileID, ManifestPath: profileManifestRelative,
			ManifestSHA256: digest(profileManifestData), ManifestBytes: int64(len(profileManifestData)),
			PayloadPath: profilePayloadRelative, PayloadSHA256: digest(profilePayload), PayloadBytes: int64(len(profilePayload)),
			TargetRelativePath: targetRelative, BaselineSHA256: digest(baseline), BaselineBytes: int64(len(baseline)), RuntimeValidated: true,
		}},
		Archives: []compositionBuildArchive{{
			ArchiveRelativePath: targetRelative, Mode: "verified_restoration_profile_passthrough",
			BaseSourceKind: "verified_runtime_validated_restoration_profile", BaseSourcePath: profilePayloadRelative,
			BaseSHA256: digest(profilePayload), BaseBytes: int64(len(profilePayload)),
			InstalledBaselineSHA256: digest(baseline), InstalledBaselineBytes: int64(len(baseline)),
			OutputPath: outputRelative, OutputSHA256: digest(profilePayload), OutputBytes: int64(len(profilePayload)),
			FullReextractVerified: false, ManifestDeclarationChecked: true,
			Status: "published_verified_restoration_profile_passthrough", ProfileIDs: []string{profileID},
		}},
		PublishedArchiveCount: 1, ComposedArchiveCount: 0, PassthroughArchiveCount: 1, FullReextractCount: 0,
		Errors: []string{},
	}
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionReportRelative)), data)
	testWrite(t, filepath.Join(root, filepath.FromSlash(compositionEmbeddedReportRelative)), data)
}

func TestRuntimeValidatedRestorationProfilePassthroughBecomesCanonicalPreviewReady(t *testing.T) {
	root, game := syntheticProject(t, quartetTargetID, map[string][]byte{"Data/PACK10_03.PAK": []byte("unused translation fixture")})
	writeSyntheticProductionRestorationPassthrough(t, root, game)
	selection := model.SelectionResult{Targets: []model.TargetSelection{{
		TargetID: quartetTargetID, DisplayName: "Quartet", Root: game,
		DetectionSource: "test", SelectedModuleIDs: []string{"quartet_restoration"},
	}}}
	preview, err := Build(root, filepath.Join(root, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready" || preview.Targets[0].Status != "ready" || preview.Targets[0].ReadyArtifactCount != 1 || preview.Targets[0].PendingModuleCount != 0 {
		t.Fatalf("runtime-validated passthrough preview is not ready: %+v", preview)
	}
	artifact := preview.Targets[0].Modules[0].Artifacts[0]
	if artifact.RelativePath != "Data/PACK10_03.PAK" || !artifact.CompositionVerified || !artifact.TransactionReady || artifact.DesiredAction != "replace" {
		t.Fatalf("runtime-validated passthrough artifact is not transaction ready: %+v", artifact)
	}
	if preview.CommitEnabled {
		t.Fatal("preview unexpectedly enabled commit")
	}
}
