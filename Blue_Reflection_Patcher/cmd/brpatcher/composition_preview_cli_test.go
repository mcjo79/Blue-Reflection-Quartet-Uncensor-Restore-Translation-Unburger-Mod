package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
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
		"Data/PACK00_04_01.PAK": []byte("translation title\n"),
	}
	var archives []map[string]any
	for relative, data := range translationPayloads {
		path := filepath.Join(project, ".local/build/translation/archives/blue_reflection_quartet", filepath.FromSlash(relative))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, 0o644); err != nil {
			t.Fatal(err)
		}
		archives = append(archives, map[string]any{
			"target_id": quartetTargetID, "archive_relative_path": relative,
			"output_path":   filepath.ToSlash(mustRelativeFixture(t, project, path)),
			"output_sha256": digestFixture(data), "output_bytes": len(data), "failures": []string{},
		})
	}
	writeJSONFixture(t, filepath.Join(project, filepath.FromSlash(translationRepackReportRelative)), map[string]any{
		"status": "ok", "archives": archives,
	})
	translationMember := "event/b1/event_en/test.ebm"
	writeJSONFixture(t, filepath.Join(project, filepath.FromSlash(translationLooseReportRelative)), map[string]any{
		"status": "ok",
		"targets": map[string]any{
			quartetTargetID: map[string]any{"files": []map[string]any{{
				"archive_relative_path": "Data/PACK11.PAK", "internal_path": translationMember, "changed": true,
			}}},
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
