package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func writeModuleVersionFixture(t *testing.T, root, relative, value string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(value+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestSelectedVersionedContentIndicatorsFromReleaseMetadata(t *testing.T) {
	root := t.TempDir()
	writeModuleVersionFixture(t, root, "meta/MODULE_VERSIONS.tsv", "core\t0.0.96\ntranslation\t0.0.203\nquartet_restoration\t0.1.78\nquartet_legacy_dlc\t0.1.0")
	got, err := selectedVersionedContentIndicators(root, "blue_reflection_quartet", []string{
		quartetTranslationModule, quartetRestorationModule, quartetLegacyDLCModule,
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"UNBURGER (v0.0.203)", "UNCENSOR (v0.1.78)", "DLC (v0.1.0)"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("labels=%q want=%q", got, want)
	}
}

func TestSelectedVersionedContentIndicatorsFallsBackToWorkstreamVersions(t *testing.T) {
	root := t.TempDir()
	writeModuleVersionFixture(t, root, "workstreams/translation/VERSION", "0.0.203")
	writeModuleVersionFixture(t, root, "workstreams/quartet_restoration/VERSION", "0.1.78")
	writeModuleVersionFixture(t, root, "workstreams/quartet_legacy_dlc/VERSION", "0.1.0")
	got, err := selectedVersionedContentIndicators(root, "blue_reflection_quartet", []string{
		quartetTranslationModule, quartetRestorationModule,
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"UNBURGER (v0.0.203)", "UNCENSOR (v0.1.78)"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("labels=%q want=%q", got, want)
	}
}

func TestSelectedVersionedContentIndicatorsRejectsMissingSelectedVersion(t *testing.T) {
	root := t.TempDir()
	writeModuleVersionFixture(t, root, "meta/MODULE_VERSIONS.tsv", "translation\t0.0.203")
	if _, err := selectedVersionedContentIndicators(root, "blue_reflection_quartet", []string{quartetRestorationModule}); err == nil {
		t.Fatal("expected missing restoration version to fail")
	}
}
