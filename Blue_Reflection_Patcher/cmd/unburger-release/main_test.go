package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func writeFixtureFile(t *testing.T, root, rel string, data []byte) (string, int64) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), int64(len(data))
}

func writeFixtureJSON(t *testing.T, path string, value any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	blob, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, append(blob, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestStageReleaseWithVerifiedLooseContent(t *testing.T) {
	project := t.TempDir()
	stage := filepath.Join(t.TempDir(), "stage")
	for rel, value := range map[string]string{
		"workstreams/core/VERSION":                "0.0.67\n",
		"workstreams/translation/VERSION":         "0.0.159\n",
		"workstreams/translation_tooling/VERSION": "0.0.54\n",
	} {
		writeFixtureFile(t, project, rel, []byte(value))
	}

	outputRel := ".local/build/translation/loose/blue_reflection_quartet/PACK12/str_costume.xml"
	templateRel := ".local/build/translation/templates/blue_reflection_quartet/PACK12/str_costume.xml"
	outputHash, outputBytes := writeFixtureFile(t, project, outputRel, []byte("<strings>\r\n<str String_No=\"10\" Text=\"Translated\"/>\r\n</strings>\r\n"))
	templateHash, _ := writeFixtureFile(t, project, templateRel, []byte("<strings>\r\n<str String_No=\"10\" Text=\"Base\"/>\r\n</strings>\r\n"))

	loose := looseReport{
		Type:                      "br_translation_loose_build_report",
		Status:                    "ok",
		TranslationVersion:        "0.0.159",
		TranslationToolingVersion: "0.0.54",
		Targets: map[string]looseTarget{
			"blue_reflection_quartet": {Files: []looseFile{{
				ArchiveRelativePath: "Data/PACK12.PAK",
				InternalPath:        `\saves\b1\text_en\str_costume.xml`,
				TemplatePath:        templateRel,
				TemplateSHA256:      templateHash,
				OutputPath:          outputRel,
				OutputSHA256:        outputHash,
				OutputBytes:         outputBytes,
				Changed:             true,
			}}},
		},
	}
	repack := repackReport{Type: "br_translation_pak_repack_report", Status: "ok", TranslationVersion: "0.0.159", TranslationToolingVersion: "0.0.54"}
	writeFixtureJSON(t, filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"), loose)
	writeFixtureJSON(t, filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"), repack)

	if err := stageRelease(project, stage); err != nil {
		t.Fatalf("stageRelease: %v", err)
	}
	for _, rel := range []string{
		outputRel,
		templateRel,
		".local/reports/translation/BR_TRANSLATION_STANDALONE_MEMBER_REPORT.json",
		"RELEASE_MANIFEST.json",
	} {
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
	if manifest.TranslationChangedFiles != 1 || manifest.LargeGameArchivesIncluded {
		t.Fatalf("unexpected release manifest: %+v", manifest)
	}
}

func TestStageReleaseRejectsStaleLooseContent(t *testing.T) {
	project := t.TempDir()
	stage := filepath.Join(t.TempDir(), "stage")
	for rel, value := range map[string]string{
		"workstreams/core/VERSION":                "0.0.67\n",
		"workstreams/translation/VERSION":         "0.0.159\n",
		"workstreams/translation_tooling/VERSION": "0.0.54\n",
	} {
		writeFixtureFile(t, project, rel, []byte(value))
	}
	writeFixtureJSON(t, filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"), looseReport{Status: "ok", TranslationVersion: "0.0.158", TranslationToolingVersion: "0.0.54"})
	writeFixtureJSON(t, filepath.Join(project, ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"), repackReport{Status: "ok", TranslationVersion: "0.0.159", TranslationToolingVersion: "0.0.54"})
	if err := stageRelease(project, stage); err == nil {
		t.Fatal("expected stale Translation loose build to be rejected")
	}
}
