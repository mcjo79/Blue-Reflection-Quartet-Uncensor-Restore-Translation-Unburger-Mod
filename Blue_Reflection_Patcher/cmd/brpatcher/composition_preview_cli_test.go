package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type compositionFixture struct {
	project string
	game    string
}

func writeJSONFixture(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func digestFixture(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

func newCompositionFixture(t *testing.T, runtimeValidated bool, conflict bool) compositionFixture {
	t.Helper()
	root := t.TempDir()
	project := filepath.Join(root, "project")
	game := filepath.Join(root, "game")
	for _, path := range []string{
		filepath.Join(project, "workstreams/core"),
		filepath.Join(project, "Blue_Reflection_Patcher"),
		filepath.Join(game, "Data"),
	} {
		if err := os.MkdirAll(path, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(project, "workstreams/core/VERSION"), []byte("0.0.23\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	for relative, value := range map[string]string{
		"workstreams/translation/VERSION":         "0.0.113\n",
		"workstreams/translation_tooling/VERSION": "0.0.54\n",
	} {
		path := filepath.Join(project, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(value), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(project, "Blue_Reflection_Patcher/go.mod"), []byte("module synthetic/composition\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	baseline11 := []byte("stock PACK11 baseline\n")
	baseline10 := []byte("stock PACK10 baseline\n")
	if err := os.WriteFile(filepath.Join(game, "Data/PACK11.PAK"), baseline11, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "Data/PACK10_01.PAK"), baseline10, 0o644); err != nil {
		t.Fatal(err)
	}

	translationPayloads := map[string][]byte{
		"Data/PACK11.PAK":       []byte("translation PACK11\n"),
		"Data/PACK12.PAK":       []byte("translation PACK12\n"),
		"Data/PACK01_01.PAK":    []byte("translation RAY events\n"),
		"Data/PACK02_01.PAK":    []byte("translation RAY system\n"),
		"Data/PACK01_02.PAK":    []byte("translation SUN events\n"),
		"Data/PACK02_02.PAK":    []byte("translation SUN system\n"),
		"Data/PACK01_03.PAK":    []byte("translation SL b4 events\n"),
		"Data/PACK02_03.PAK":    []byte("translation SL b4 system\n"),
		"Data/PACK00_04_01.PAK": []byte("translation title\n"),
	}
	var archives []map[string]any
	for relative, data := range translationPayloads {
		buildTargetID := quartetTargetID
		switch relative {
		case "Data/PACK01_01.PAK", "Data/PACK02_01.PAK":
			buildTargetID = "blue_reflection_ray_quartet"
		case "Data/PACK01_02.PAK", "Data/PACK02_02.PAK":
			buildTargetID = "blue_reflection_sun_quartet"
		case "Data/PACK01_03.PAK", "Data/PACK02_03.PAK":
			buildTargetID = "second_light_quartet"
		}
		path := filepath.Join(project, ".local/build/translation/archives", buildTargetID, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0o644); err != nil {
			t.Fatal(err)
		}
		archives = append(archives, map[string]any{
			"target_id": buildTargetID, "archive_relative_path": relative,
			"output_path":   filepath.ToSlash(mustRelativeFixture(t, project, path)),
			"output_sha256": digestFixture(data), "output_bytes": len(data), "failures": []string{},
		})
	}
	writeJSONFixture(t, filepath.Join(project, filepath.FromSlash(translationRepackReportRelative)), map[string]any{
		"type": "br_translation_pak_repack_report", "format_version": 2, "status": "ok",
		"translation_version": "0.0.113", "translation_tooling_version": "0.0.54",
		"canonical_input_fingerprint": digestFixture([]byte("inputs")), "archives": archives,
	})
	translationMember := "event/b1/event_en/test.ebm"
	writeJSONFixture(t, filepath.Join(project, filepath.FromSlash(translationLooseReportRelative)), map[string]any{
		"type": "br_translation_loose_build_report", "format_version": 2, "status": "ok",
		"translation_version": "0.0.113", "translation_tooling_version": "0.0.54",
		"canonical_input_fingerprint": digestFixture([]byte("inputs")),
		"targets": map[string]any{
			quartetTargetID: map[string]any{"files": []map[string]any{{
				"archive_relative_path": "Data/PACK11.PAK", "internal_path": translationMember, "changed": true,
			}}},
			"blue_reflection_ray_quartet": map[string]any{"files": []map[string]any{}},
			"blue_reflection_sun_quartet": map[string]any{"files": []map[string]any{}},
			"second_light_quartet":        map[string]any{"files": []map[string]any{}},
		},
	})

	profilePayload := []byte("restoration profile PACK11\n")
	profileRelative := filepath.ToSlash(filepath.Join(localProfilePayloadRoot, "synthetic", "profile.PAK"))
	profilePath := filepath.Join(project, filepath.FromSlash(profileRelative))
	if err := os.MkdirAll(filepath.Dir(profilePath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(profilePath, profilePayload, 0o644); err != nil {
		t.Fatal(err)
	}
	changedMember := "event/b1/event_jp/test.ebd"
	if conflict {
		changedMember = translationMember
	}
	manifest := localProfileManifest{
		SchemaVersion: localProfileSchemaVersion, ProfileID: "synthetic_runtime_profile",
		TargetRelativePath: "Data/PACK11.PAK",
		BaselineSHA256:     digestFixture(baseline11), BaselineSize: int64(len(baseline11)),
		ProfileSHA256: digestFixture(profilePayload), ProfileSize: int64(len(profilePayload)),
		LocalProfilePath: profileRelative, ChangedMemberCount: 1, ChangedMembers: []string{changedMember},
		RuntimeValidated: runtimeValidated, WorkstreamID: localProfileWorkstreamID, WorkstreamVersion: "0.0.76-test",
	}
	writeJSONFixture(t, filepath.Join(project, filepath.FromSlash(localProfileManifestRoot), "synthetic_runtime_profile.json"), manifest)
	return compositionFixture{project: project, game: game}
}

func mustRelativeFixture(t *testing.T, root, path string) string {
	t.Helper()
	relative, err := filepath.Rel(root, path)
	if err != nil {
		t.Fatal(err)
	}
	return relative
}

func TestQuartetCompositionPreviewAcceptsDisjointRuntimeValidatedOverlay(t *testing.T) {
	fixture := newCompositionFixture(t, true, false)
	preview, err := buildQuartetCompositionPreview(fixture.project, fixture.game)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready_for_composition_build" || preview.ProductionEligibleCount != 1 {
		t.Fatalf("unexpected preview: %+v", preview)
	}
	if len(preview.Profiles) != 1 || !preview.Profiles[0].ProductionEligible {
		t.Fatalf("profile was not eligible: %+v", preview.Profiles)
	}
	if preview.Archives[0].ArchiveRelativePath != "Data/PACK11.PAK" || preview.Archives[0].Status != "ready_for_member_overlay" {
		t.Fatalf("PACK11 overlay plan is not ready: %+v", preview.Archives)
	}
	if preview.CommitEnabled {
		t.Fatal("composition preflight unexpectedly enabled commit")
	}
}

func TestQuartetCompositionPreviewBlocksExactTranslationMemberConflict(t *testing.T) {
	fixture := newCompositionFixture(t, true, true)
	preview, err := buildQuartetCompositionPreview(fixture.project, fixture.game)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "blocked_member_conflict" || preview.ProductionEligibleCount != 0 {
		t.Fatalf("exact member conflict was not blocked: %+v", preview)
	}
	if preview.Profiles[0].Status != "blocked_translation_member_conflict" || len(preview.Profiles[0].TranslationConflicts) != 1 {
		t.Fatalf("missing translation conflict detail: %+v", preview.Profiles[0])
	}
}

func TestQuartetCompositionPreviewExcludesUnvalidatedCandidate(t *testing.T) {
	fixture := newCompositionFixture(t, false, false)
	preview, err := buildQuartetCompositionPreview(fixture.project, fixture.game)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "awaiting_runtime_validated_profiles" || preview.ProductionEligibleCount != 0 {
		t.Fatalf("unvalidated profile entered production composition: %+v", preview)
	}
	if preview.Profiles[0].Status != "candidate_awaiting_runtime_validation" {
		t.Fatalf("unexpected candidate status: %+v", preview.Profiles[0])
	}
}

func addCompositionLegacyDLCFixture(t *testing.T, fixture compositionFixture) {
	t.Helper()
	baseline10 := []byte("stock PACK10_02 baseline\n")
	baseline12 := []byte("stock PACK12 baseline\n")
	candidate10 := []byte("stock PACK10_02 baseline plus exact dry BKN members\n")
	candidate12 := []byte("stock PACK12 baseline with charabase dry BKN edit\n")
	for relative, data := range map[string][]byte{
		"Data/PACK10_02.PAK": baseline10,
		"Data/PACK12.PAK":    baseline12,
	} {
		path := filepath.Join(fixture.game, filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	candidateRelatives := []string{
		".local/build/quartet_legacy_dlc/fixture/PACK10_02.PAK",
		".local/build/quartet_legacy_dlc/fixture/PACK12.PAK",
	}
	candidates := [][]byte{candidate10, candidate12}
	baselines := [][]byte{baseline10, baseline12}
	relatives := []string{"Data/PACK10_02.PAK", "Data/PACK12.PAK"}
	deltas := []map[string]any{
		{"added": []string{"data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz", "data/b1/x64/character/pc00/pc00_dlc_bkn.g1t"}, "changed": []string{}, "removed": []string{}},
		{"added": []string{}, "changed": []string{"saves/b1/chara/charabase.xml"}, "removed": []string{}},
	}
	artifacts := make([]map[string]any, 0, 2)
	for index := range relatives {
		path := filepath.Join(fixture.project, filepath.FromSlash(candidateRelatives[index]))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, candidates[index], 0o644); err != nil {
			t.Fatal(err)
		}
		artifacts = append(artifacts, map[string]any{
			"target_path": relatives[index], "operation": "replace", "candidate_relative_path": candidateRelatives[index],
			"baseline_size": len(baselines[index]), "baseline_sha256": digestFixture(baselines[index]),
			"candidate_size": len(candidates[index]), "candidate_sha256": digestFixture(candidates[index]),
			"member_delta": deltas[index],
		})
	}
	evidenceRelative := ".local/reports/quartet_legacy_dlc/evidence/fixture.json"
	evidenceData := []byte(`{"type":"fixture"}` + "\n")
	evidencePath := filepath.Join(fixture.project, filepath.FromSlash(evidenceRelative))
	if err := os.MkdirAll(filepath.Dir(evidencePath), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(evidencePath, evidenceData, 0o644); err != nil {
		t.Fatal(err)
	}
	writeJSONFixture(t, filepath.Join(fixture.project, filepath.FromSlash(".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json")), map[string]any{
		"type": "validated_quartet_legacy_dlc_payload", "format_version": 1,
		"family_id": "bkn_dry", "generation": 1, "members": []string{"costume_pc00_bkn"},
		"source_kind": "validated_quartet_legacy_dlc_handoff", "target_id": quartetTargetID,
		"artifacts":     artifacts,
		"transaction":   map[string]any{"group": "quartet_legacy_dlc_bkn_dry", "all_or_none": true, "commit_enabled": false},
		"provenance":    map[string]any{"workstream_id": "quartet_legacy_dlc", "workstream_version": "fixture", "evidence_relative_path": evidenceRelative, "evidence_sha256": digestFixture(evidenceData)},
		"authorization": map[string]any{"core_handoff_ready": true, "real_transaction_prepare_enabled": false, "real_transaction_commit_enabled": false, "candidate_installed": false, "profile_registered": false, "runtime_validated": false, "wet_variant_included": false, "game_modified": false},
	})
}

func TestQuartetModuleCompositionPreviewTranslationPlusLegacyDLCReadyWithoutRestorationProfiles(t *testing.T) {
	fixture := newCompositionFixture(t, false, false)
	addCompositionLegacyDLCFixture(t, fixture)
	preview, err := buildQuartetModuleCompositionPreview(fixture.project, fixture.game, []string{quartetTranslationModule, quartetLegacyDLCModule})
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready_for_composition_build" || preview.CommitEnabled || len(preview.LegacyDLCInputs) != 2 {
		t.Fatalf("unexpected Translation+DLC preview: %+v", preview)
	}
	if !sameQuartetCompositionModules(preview.SelectedModules, []string{quartetTranslationModule, quartetLegacyDLCModule}) {
		t.Fatalf("selected modules were not retained: %#v", preview.SelectedModules)
	}
	var pack12 *compositionArchivePreview
	for index := range preview.Archives {
		if preview.Archives[index].ArchiveRelativePath == "Data/PACK12.PAK" {
			pack12 = &preview.Archives[index]
		}
	}
	if pack12 == nil || pack12.Status != "ready_for_member_overlay" {
		t.Fatalf("PACK12 was not planned as a shared member overlay: %+v", pack12)
	}
}

func TestQuartetModuleCompositionPreviewAllThreeRemainsBlockedWithoutRuntimeProfile(t *testing.T) {
	fixture := newCompositionFixture(t, false, false)
	addCompositionLegacyDLCFixture(t, fixture)
	preview, err := buildQuartetModuleCompositionPreview(fixture.project, fixture.game, []string{quartetTranslationModule, quartetRestorationModule, quartetLegacyDLCModule})
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "awaiting_runtime_validated_profiles" || preview.CommitEnabled {
		t.Fatalf("all-three preview was not fail-closed: %+v", preview)
	}
}

func TestHumanQuartetCompositionPreviewUsesModuleNeutralHeading(t *testing.T) {
	preview := quartetCompositionPreview{
		Status:          "ready_for_composition_build",
		SelectedModules: []string{quartetTranslationModule, quartetLegacyDLCModule},
		LegacyDLCInputs: []compositionLegacyDLCInput{{Verified: true}, {Verified: true}},
	}
	var output bytes.Buffer
	printHumanQuartetCompositionPreview(&output, preview)
	text := output.String()
	if !strings.Contains(text, "Quartet module composition preflight") {
		t.Fatalf("module-neutral heading is missing: %q", text)
	}
	if strings.Contains(text, "translation + restoration") || strings.Contains(text, "Restoration profiles:") {
		t.Fatalf("Translation+DLC output incorrectly describes Restoration: %q", text)
	}
	if !strings.Contains(text, "Legacy DLC inputs: 2 verified of 2") {
		t.Fatalf("Legacy DLC verification summary is missing: %q", text)
	}
}

func TestHumanQuartetCompositionPreviewShowsProfilesOnlyWhenSelected(t *testing.T) {
	preview := quartetCompositionPreview{
		Status:                       "awaiting_runtime_validated_profiles",
		SelectedModules:              []string{quartetTranslationModule, quartetRestorationModule},
		ValidProfileCount:            3,
		RuntimeValidatedProfileCount: 1,
		ProductionEligibleCount:      1,
	}
	var output bytes.Buffer
	printHumanQuartetCompositionPreview(&output, preview)
	if !strings.Contains(output.String(), "Restoration profiles: 3 valid, 1 runtime validated, 1 production eligible") {
		t.Fatalf("Restoration profile summary is missing: %q", output.String())
	}
}

func TestQuartetRestorationRuntimeTestPreviewSelectsAllCurrentCandidates(t *testing.T) {
	fixture := newCompositionFixture(t, false, false)
	preview, err := buildQuartetModuleCompositionPreviewWithPolicy(
		fixture.project,
		fixture.game,
		[]string{quartetRestorationModule},
		restorationProfilePolicyAllCandidatesRuntimeTest,
	)
	if err != nil {
		t.Fatal(err)
	}
	if preview.Status != "ready_for_runtime_test_composition_build" || !preview.RuntimeTestOnly {
		t.Fatalf("runtime-test preview was not ready: %+v", preview)
	}
	if preview.ProfileSelectionPolicy != restorationProfilePolicyAllCandidatesRuntimeTest || preview.SelectedProfileCount != 1 || preview.RuntimeTestCandidateCount != 1 {
		t.Fatalf("runtime-test profile selection is wrong: %+v", preview)
	}
	if preview.ProductionEligibleCount != 0 || len(preview.Profiles) != 1 || !preview.Profiles[0].RuntimeTestEligible || !preview.Profiles[0].SelectedForComposition {
		t.Fatalf("unvalidated candidate was not isolated as a runtime-test input: %+v", preview.Profiles)
	}
	if len(preview.Archives) != 1 || preview.Archives[0].ArchiveRelativePath != "Data/PACK11.PAK" || preview.Archives[0].Status != "ready_for_member_overlay" {
		t.Fatalf("unexpected runtime-test archive plan: %+v", preview.Archives)
	}
	if preview.CommitEnabled {
		t.Fatal("runtime-test preflight unexpectedly enabled commit")
	}
}

func TestQuartetRestorationRuntimeTestPolicyRejectsMixedModules(t *testing.T) {
	fixture := newCompositionFixture(t, false, false)
	_, err := buildQuartetModuleCompositionPreviewWithPolicy(
		fixture.project,
		fixture.game,
		[]string{quartetTranslationModule, quartetRestorationModule},
		restorationProfilePolicyAllCandidatesRuntimeTest,
	)
	if err == nil || !strings.Contains(err.Error(), "isolated Restoration-only") {
		t.Fatalf("mixed-module runtime-test policy was not rejected: %v", err)
	}
}
