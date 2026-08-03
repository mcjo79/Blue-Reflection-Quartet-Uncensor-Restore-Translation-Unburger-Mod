package selection

import (
	"fmt"
	"sort"

	"local/blue-reflection-patcher/internal/model"
)

func Available(modules []model.BundleModule, targetID string) []model.BundleModule {
	var result []model.BundleModule
	for _, module := range modules {
		if module.Selectable && supports(module.SupportedTargets, targetID) {
			result = append(result, module)
		}
	}
	return result
}

func Build(
	detections []model.Detection,
	modules []model.BundleModule,
	requested []string,
	perTarget map[string][]string,
	mode string,
) (model.SelectionResult, error) {
	moduleByID := map[string]model.BundleModule{}
	for _, module := range modules {
		moduleByID[module.ModuleID] = module
	}
	for _, id := range requested {
		if _, ok := moduleByID[id]; !ok {
			return model.SelectionResult{}, fmt.Errorf("unknown module: %s", id)
		}
	}
	result := model.SelectionResult{
		Type: model.SelectionType, FormatVersion: model.SelectionFormatVersion, Mode: mode,
		Warnings: []string{},
	}
	matchedRequested := map[string]bool{}
	for _, detection := range detections {
		available := Available(modules, detection.TargetID)
		selected := requested
		if values, ok := perTarget[detection.TargetID]; ok {
			selected = values
		}
		if selected == nil {
			for _, module := range available {
				if supports(module.DefaultTargets, detection.TargetID) {
					selected = append(selected, module.ModuleID)
				}
			}
		}
		selectedSet := map[string]bool{}
		for _, id := range selected {
			module, ok := moduleByID[id]
			if !ok {
				return model.SelectionResult{}, fmt.Errorf("unknown module: %s", id)
			}
			if !supports(module.SupportedTargets, detection.TargetID) {
				continue
			}
			selectedSet[id] = true
			matchedRequested[id] = true
		}
		if err := validateRelations(moduleByID, selectedSet, detection.TargetID); err != nil {
			return model.SelectionResult{}, err
		}
		selectedIDs := make([]string, 0, len(selectedSet))
		for id := range selectedSet {
			selectedIDs = append(selectedIDs, id)
		}
		sort.Strings(selectedIDs)
		target := model.TargetSelection{
			TargetID: detection.TargetID, DisplayName: detection.DisplayName,
			Root: detection.Root, DetectionSource: detection.Source,
			SelectedModuleIDs: selectedIDs,
		}
		for _, module := range available {
			state := "disabled"
			if selectedSet[module.ModuleID] {
				state = "enabled"
			}
			target.AvailableModules = append(target.AvailableModules, model.ModuleChoice{
				ModuleID: module.ModuleID, DisplayName: module.DisplayName,
				Description: module.Description, ModuleType: module.ModuleType,
				DefaultEnabled: supports(module.DefaultTargets, detection.TargetID),
				DesiredState:   state, SourceTargets: append([]string{}, module.SourceTargets...),
			})
		}
		result.Targets = append(result.Targets, target)
	}
	for _, id := range requested {
		if !matchedRequested[id] {
			return model.SelectionResult{}, fmt.Errorf("module %s does not support any detected installation", id)
		}
	}
	if len(result.Targets) == 0 {
		result.Warnings = append(result.Warnings, "no supported installation was detected")
	}
	return result, nil
}

func validateRelations(modules map[string]model.BundleModule, selected map[string]bool, targetID string) error {
	for id := range selected {
		module := modules[id]
		for _, dependency := range module.Dependencies {
			dep, ok := modules[dependency]
			if !ok || !supports(dep.SupportedTargets, targetID) {
				return fmt.Errorf("module %s has unavailable dependency %s for target %s", id, dependency, targetID)
			}
			if !selected[dependency] {
				return fmt.Errorf("module %s requires module %s", id, dependency)
			}
		}
		for _, conflict := range module.Conflicts {
			if selected[conflict] {
				return fmt.Errorf("modules %s and %s conflict", id, conflict)
			}
		}
	}
	return nil
}

func supports(values []string, targetID string) bool {
	for _, value := range values {
		if value == targetID {
			return true
		}
	}
	return false
}
