package catalog

import (
	_ "embed"
	"encoding/json"
	"fmt"

	"local/blue-reflection-patcher/internal/model"
)

//go:embed catalog.json
var rawCatalog []byte

type document struct {
	Type          string               `json:"type"`
	FormatVersion int                  `json:"format_version"`
	Modules       []model.BundleModule `json:"modules"`
}

func Load() ([]model.BundleModule, error) {
	var doc document
	if err := json.Unmarshal(rawCatalog, &doc); err != nil {
		return nil, fmt.Errorf("decode embedded module catalog: %w", err)
	}
	if doc.Type != "br_module_catalog" || doc.FormatVersion != 1 {
		return nil, fmt.Errorf("unsupported embedded module catalog type/version")
	}
	seen := map[string]bool{}
	for _, module := range doc.Modules {
		if module.ModuleID == "" || seen[module.ModuleID] {
			return nil, fmt.Errorf("invalid or duplicate module id: %s", module.ModuleID)
		}
		seen[module.ModuleID] = true
		if !module.Selectable {
			return nil, fmt.Errorf("embedded module %s is not selectable", module.ModuleID)
		}
		if len(module.SupportedTargets) == 0 {
			return nil, fmt.Errorf("embedded module %s has no supported targets", module.ModuleID)
		}
	}
	return doc.Modules, nil
}
