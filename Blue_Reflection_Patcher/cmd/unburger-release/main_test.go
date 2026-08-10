package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func writeFixtureFile(t *testing.T, root, rel string, data []byte) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

func writeFixtureJSON(t *testing.T, root, rel string, value any) {
	t.Helper()
	blob, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	writeFixtureFile(t, root, rel, append(blob, '\n'))
}

func minimalProject(t *testing.T) string {
	project := t.TempDir()
	writeFixtureFile(t, project, "workstreams/core/VERSION", []byte("0.0.74\n"))
	writeFixtureFile(t, project, "workstreams/translation/VERSION", []byte("0.0.203\n"))
	writeFixtureJSON(t, project, "workstreams/translation_tooling/config/quartet_target_adaptations.json", map[string]any{"type": "br_quartet_target_adaptation_policy", "format_version": 1, "target_id": "blue_reflection_quartet", "policy": map[string]any{"allow_redacted_target_import": true, "redacted_target_marker": "-"}, "records": []any{}})
	for _, p := range []string{"blue_reflection", "second_light", "blue_reflection_ray", "blue_reflection_sun"} {
		if err := os.MkdirAll(filepath.Join(project, "titles", p, "translation"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	idx := 0
	writeFixtureJSON(t, project, "titles/blue_reflection/translation/system/test.xml.json", map[string]any{
		"type":    "br_system_translation_unit",
		"records": []any{map[string]any{"index": 0, "logical_id": "blue_reflection:system:str_test.xml:String_No:10", "string_no": "10", "string_id": "STR_TEST", "jp": "試験", "en_original": "Test", "en_auxiliary": "Test", "en": "Translation", "alignment": map[string]any{"target_indices": map[string]any{"blue_reflection_original": idx, "blue_reflection_quartet": idx}, "target_mapping": map[string]any{"blue_reflection_original": "exact_string_no", "blue_reflection_quartet": "exact_string_no"}}}},
	})
	return project
}

func TestStageReleaseBuildsCanonicalRecordBundle(t *testing.T) {
	project := minimalProject(t)
	stage := filepath.Join(t.TempDir(), "stage")
	if err := stageRelease(project, stage); err != nil {
		t.Fatalf("stageRelease: %v", err)
	}
	for _, rel := range []string{"content/translation/records.v1.json", "content/translation/build-report.json", "RELEASE_MANIFEST.json"} {
		if info, err := os.Stat(filepath.Join(stage, filepath.FromSlash(rel))); err != nil || !info.Mode().IsRegular() {
			t.Fatalf("staged file missing: %s (%v)", rel, err)
		}
	}
	var manifest releaseManifest
	blob, err := os.ReadFile(filepath.Join(stage, "RELEASE_MANIFEST.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(blob, &manifest); err != nil {
		t.Fatal(err)
	}
	if manifest.FormatVersion != 3 || manifest.TranslationVersion != "0.0.203" || manifest.LargeGameArchives || !manifest.RuntimeMaterialization {
		t.Fatalf("unexpected manifest: %+v", manifest)
	}
	if manifest.TranslationRecords["blue_reflection_original"] != 1 || manifest.TranslationRecords["blue_reflection_quartet"] != 1 {
		t.Fatalf("unexpected record counts: %+v", manifest.TranslationRecords)
	}
}

func TestStageReleaseDoesNotRequireLooseOrRepackedArchives(t *testing.T) {
	project := minimalProject(t)
	stage := filepath.Join(t.TempDir(), "stage")
	if _, err := os.Stat(filepath.Join(project, ".local")); !os.IsNotExist(err) {
		t.Fatalf("fixture unexpectedly has .local")
	}
	if err := stageRelease(project, stage); err != nil {
		t.Fatalf("record-only release should not require developer repacks: %v", err)
	}
}
