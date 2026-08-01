package targets

import (
	_ "embed"
	"encoding/json"
	"fmt"

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
		if spec.TargetID == "" || spec.SteamAppID == 0 || len(spec.Markers) == 0 {
			return nil, fmt.Errorf("invalid embedded target: %+v", spec)
		}
		if seen[spec.TargetID] {
			return nil, fmt.Errorf("duplicate target id: %s", spec.TargetID)
		}
		seen[spec.TargetID] = true
	}
	return specs, nil
}
