package payloadpreview

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
)

//go:embed catalog.json
var rawCatalog []byte

type ArtifactSpec struct {
	RelativePath  string `json:"relative_path"`
	BuildTargetID string `json:"build_target_id"`
}

type ModuleTargetSpec struct {
	ModuleID         string         `json:"module_id"`
	TargetID         string         `json:"target_id"`
	SourceKind       string         `json:"source_kind"`
	ConnectionStatus string         `json:"connection_status"`
	Reason           string         `json:"reason,omitempty"`
	Artifacts        []ArtifactSpec `json:"artifacts"`
}

type catalogDocument struct {
	Type          string             `json:"type"`
	FormatVersion int                `json:"format_version"`
	ModuleTargets []ModuleTargetSpec `json:"module_targets"`
}

func LoadCatalog() ([]ModuleTargetSpec, error) {
	var doc catalogDocument
	if err := json.Unmarshal(rawCatalog, &doc); err != nil {
		return nil, fmt.Errorf("decode embedded local payload catalog: %w", err)
	}
	if doc.Type != "br_local_payload_catalog" || doc.FormatVersion != 1 {
		return nil, fmt.Errorf("unsupported local payload catalog type/version")
	}
	seen := map[string]bool{}
	for _, spec := range doc.ModuleTargets {
		key := spec.ModuleID + "\x00" + spec.TargetID
		if strings.TrimSpace(spec.ModuleID) == "" || strings.TrimSpace(spec.TargetID) == "" || seen[key] {
			return nil, fmt.Errorf("invalid or duplicate local payload mapping: %s/%s", spec.ModuleID, spec.TargetID)
		}
		seen[key] = true
		paths := map[string]bool{}
		for _, artifact := range spec.Artifacts {
			clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(artifact.RelativePath)))
			if artifact.RelativePath == "" || filepath.IsAbs(artifact.RelativePath) || clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
				return nil, fmt.Errorf("invalid artifact path for %s/%s: %q", spec.ModuleID, spec.TargetID, artifact.RelativePath)
			}
			folded := strings.ToLower(clean)
			if paths[folded] {
				return nil, fmt.Errorf("duplicate artifact path for %s/%s: %s", spec.ModuleID, spec.TargetID, artifact.RelativePath)
			}
			paths[folded] = true
			if spec.SourceKind != legacyDLCSourceKind && strings.TrimSpace(artifact.BuildTargetID) == "" {
				return nil, fmt.Errorf("artifact build target is missing for %s/%s: %s", spec.ModuleID, spec.TargetID, artifact.RelativePath)
			}
		}
		if spec.ConnectionStatus == "connected_preview_only" && len(spec.Artifacts) == 0 {
			return nil, fmt.Errorf("connected mapping has no artifacts: %s/%s", spec.ModuleID, spec.TargetID)
		}
	}
	return doc.ModuleTargets, nil
}
