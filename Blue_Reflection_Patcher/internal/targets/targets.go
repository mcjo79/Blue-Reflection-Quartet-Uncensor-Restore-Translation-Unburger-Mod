package targets

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

//go:embed targets.json
var rawTargets []byte

func Load() ([]model.TargetSpec, error) {
	var specs []model.TargetSpec
	if err := json.Unmarshal(rawTargets, &specs); err != nil {
		return nil, fmt.Errorf("decode embedded targets: %w", err)
	}
	seen := map[string]bool{}
	for _, spec := range specs {
		if strings.TrimSpace(spec.TargetID) == "" || strings.TrimSpace(spec.DisplayName) == "" || len(spec.RequiredFiles) == 0 {
			return nil, fmt.Errorf("invalid embedded target: %+v", spec)
		}
		if seen[spec.TargetID] {
			return nil, fmt.Errorf("duplicate target id: %s", spec.TargetID)
		}
		seen[spec.TargetID] = true
		paths := map[string]bool{}
		for _, required := range spec.RequiredFiles {
			clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(required)))
			if required == "" || filepath.IsAbs(required) || clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
				return nil, fmt.Errorf("invalid required file for %s: %q", spec.TargetID, required)
			}
			folded := strings.ToLower(clean)
			if paths[folded] {
				return nil, fmt.Errorf("duplicate required file for %s: %q", spec.TargetID, required)
			}
			paths[folded] = true
		}
	}
	return specs, nil
}
