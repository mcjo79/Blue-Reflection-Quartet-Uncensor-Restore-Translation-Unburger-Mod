package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

const quartetMovieManifestRelative = "content/restoration/movies/MANIFEST.json"

var quartetMovieNames = []string{
	"CNG_PC00_00.webm",
	"CNG_PC01_00.webm",
	"CNG_PC02_00.webm",
}

type quartetMovieManifestFile struct {
	Name   string `json:"name"`
	SHA256 string `json:"sha256"`
}

type quartetMovieManifest struct {
	Type              string                     `json:"type"`
	FormatVersion     int                        `json:"format_version"`
	TargetRelativeDir string                     `json:"target_relative_dir"`
	Files             []quartetMovieManifestFile `json:"files"`
}

func quartetMovieRestorationArtifacts(projectRoot string) ([]br1rebuild.OutputArtifact, error) {
	manifestPath := filepath.Join(projectRoot, filepath.FromSlash(quartetMovieManifestRelative))
	data, err := os.ReadFile(manifestPath)
	if err != nil {
		return nil, fmt.Errorf("UNCENSOR movie restoration payload is unavailable: %w", err)
	}
	var manifest quartetMovieManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return nil, fmt.Errorf("decode UNCENSOR movie manifest: %w", err)
	}
	if manifest.Type != "unburger_quartet_movie_restoration" || manifest.FormatVersion != 1 || filepath.ToSlash(manifest.TargetRelativeDir) != "Data/B1/x64/Movie" {
		return nil, fmt.Errorf("unsupported UNCENSOR movie restoration manifest")
	}
	if len(manifest.Files) != len(quartetMovieNames) {
		return nil, fmt.Errorf("UNCENSOR movie restoration manifest contains %d files, expected %d", len(manifest.Files), len(quartetMovieNames))
	}
	want := map[string]bool{}
	for _, name := range quartetMovieNames {
		want[name] = true
	}
	seen := map[string]bool{}
	artifacts := make([]br1rebuild.OutputArtifact, 0, len(manifest.Files))
	for _, item := range manifest.Files {
		if !want[item.Name] || seen[item.Name] || len(item.SHA256) != 64 {
			return nil, fmt.Errorf("invalid UNCENSOR movie restoration entry %q", item.Name)
		}
		seen[item.Name] = true
		path := filepath.Join(projectRoot, "content", "restoration", "movies", item.Name)
		hash, _, err := checkedFile(path)
		if err != nil {
			return nil, fmt.Errorf("verify UNCENSOR movie %s: %w", item.Name, err)
		}
		if !strings.EqualFold(hash, item.SHA256) {
			return nil, fmt.Errorf("UNCENSOR movie payload checksum mismatch for %s", item.Name)
		}
		artifacts = append(artifacts, br1rebuild.OutputArtifact{
			RelativePath: filepath.ToSlash(filepath.Join(manifest.TargetRelativeDir, item.Name)),
			Path:         path,
		})
	}
	sort.Slice(artifacts, func(i, j int) bool { return artifacts[i].RelativePath < artifacts[j].RelativePath })
	return artifacts, nil
}
