package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/translationbundle"
)

type releaseManifest struct {
	Type                   string         `json:"type"`
	FormatVersion          int            `json:"format_version"`
	CoreVersion            string         `json:"core_version"`
	TranslationVersion     string         `json:"translation_version"`
	TranslationTargets     []string       `json:"translation_targets"`
	TranslationMembers     map[string]int `json:"translation_members"`
	TranslationRecords     map[string]int `json:"translation_records"`
	ModuleOrder            []string       `json:"quartet_module_order"`
	LargeGameArchives      bool           `json:"large_game_archives_included"`
	RuntimeMaterialization bool           `json:"runtime_materialization"`
}

func main() {
	fs := flag.NewFlagSet("unburger-release", flag.ExitOnError)
	project := fs.String("project-root", "", "project root")
	stage := fs.String("stage-root", "", "release staging root")
	_ = fs.Parse(os.Args[1:])
	if *project == "" || *stage == "" {
		fatal("--project-root and --stage-root are required")
	}
	if err := stageRelease(*project, *stage); err != nil {
		fatal(err.Error())
	}
}
func fatal(v string) { fmt.Fprintln(os.Stderr, "ERROR:", v); os.Exit(1) }
func readVersion(path string) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	v := strings.TrimSpace(string(b))
	if v == "" {
		return "", fmt.Errorf("empty version: %s", path)
	}
	return v, nil
}

func stageRelease(project, stage string) error {
	project, _ = filepath.Abs(project)
	stage, _ = filepath.Abs(stage)
	if err := os.RemoveAll(stage); err != nil {
		return err
	}
	if err := os.MkdirAll(stage, 0o755); err != nil {
		return err
	}
	coreVersion, err := readVersion(filepath.Join(project, "workstreams", "core", "VERSION"))
	if err != nil {
		return err
	}
	translationVersion, err := readVersion(filepath.Join(project, "workstreams", "translation", "VERSION"))
	if err != nil {
		return err
	}
	packPath := filepath.Join(stage, "content", "translation", "records.v1.json")
	reportPath := filepath.Join(stage, "content", "translation", "build-report.json")
	stats, err := translationbundle.Write(project, packPath)
	if err != nil {
		return fmt.Errorf("build canonical Translation record bundle: %w", err)
	}
	if stats.TranslationVersion != translationVersion {
		return fmt.Errorf("Translation version drift while building release")
	}
	reportData, _ := json.MarshalIndent(struct {
		Type          string `json:"type"`
		FormatVersion int    `json:"format_version"`
		Status        string `json:"status"`
		translationbundle.BuildStats
	}{"unburger_translation_record_pack_build", 1, "pass", stats}, "", "  ")
	if err := os.WriteFile(reportPath, append(reportData, '\n'), 0o644); err != nil {
		return err
	}
	targets := make([]string, 0, len(stats.TargetMembers))
	for id := range stats.TargetMembers {
		targets = append(targets, id)
	}
	sort.Strings(targets)
	manifest := releaseManifest{Type: "unburger_release_manifest", FormatVersion: 2, CoreVersion: coreVersion, TranslationVersion: translationVersion, TranslationTargets: targets, TranslationMembers: stats.TargetMembers, TranslationRecords: stats.TargetRecords, ModuleOrder: []string{"quartet_legacy_dlc", "quartet_restoration", "blue_reflection_translation"}, LargeGameArchives: false, RuntimeMaterialization: true}
	data, _ := json.MarshalIndent(manifest, "", "  ")
	return os.WriteFile(filepath.Join(stage, "RELEASE_MANIFEST.json"), append(data, '\n'), 0o644)
}
