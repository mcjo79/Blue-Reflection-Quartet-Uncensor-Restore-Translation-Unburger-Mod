package plan

import (
	"fmt"
	"sort"
	"time"

	"local/blue-reflection-patcher/internal/model"
)

func Build(manifest model.BundleManifest, detections []model.Detection, requested []string) (model.PatchPlan, error) {
	moduleByID := map[string]model.BundleModule{}
	for _, module := range manifest.Modules {
		moduleByID[module.ModuleID] = module
	}

	requestedSet := map[string]bool{}
	for _, moduleID := range requested {
		if moduleID == "" {
			continue
		}
		if _, ok := moduleByID[moduleID]; !ok {
			return model.PatchPlan{}, fmt.Errorf("unknown module: %s", moduleID)
		}
		requestedSet[moduleID] = true
	}

	result := model.PatchPlan{
		Type: "br_patch_plan", FormatVersion: 1, GeneratedUTC: time.Now().UTC(),
		BundleID: manifest.BundleID, BundleVersion: manifest.BundleVersion,
		StateStrategy:    "per-user operation journal plus local backups of affected internal entries",
		TransactionModel: "stage current archive, modify selected entries, verify, atomically replace",
	}

	for _, detection := range detections {
		selected := selectModules(manifest.Modules, detection.TargetID, requestedSet)
		if len(selected) == 0 {
			continue
		}
		selected = includeDependencies(moduleByID, selected)
		sort.Strings(selected)

		selectedSet := map[string]bool{}
		for _, moduleID := range selected {
			module := moduleByID[moduleID]
			if !supports(module.SupportedTargets, detection.TargetID) {
				return model.PatchPlan{}, fmt.Errorf("module %s does not support target %s", moduleID, detection.TargetID)
			}
			selectedSet[moduleID] = true
		}

		var operations []model.PatchOperation
		archiveSet := map[string]bool{}
		for _, operation := range manifest.Operations {
			if operation.TargetID != detection.TargetID || !selectedSet[operation.ModuleID] {
				continue
			}
			operations = append(operations, operation)
			archiveSet[operation.ArchivePath] = true
		}
		sort.Slice(operations, func(i, j int) bool { return operations[i].OperationID < operations[j].OperationID })
		archives := make([]string, 0, len(archiveSet))
		for archive := range archiveSet {
			archives = append(archives, archive)
		}
		sort.Strings(archives)
		warnings := []string{}
		if len(operations) == 0 {
			warnings = append(warnings, "selected modules currently contain no generated operations")
		}
		result.Targets = append(result.Targets, model.TargetPlan{
			TargetID: detection.TargetID, DisplayName: detection.DisplayName,
			Root: detection.Root, Modules: selected, Archives: archives,
			Operations: operations, Warnings: warnings,
		})
	}
	if len(result.Targets) == 0 {
		result.Warnings = append(result.Warnings, "no detected installation has selected/default modules")
	}
	return result, nil
}

func selectModules(modules []model.BundleModule, targetID string, requested map[string]bool) []string {
	var selected []string
	if len(requested) > 0 {
		for moduleID := range requested {
			module := findModule(modules, moduleID)
			if module != nil && supports(module.SupportedTargets, targetID) {
				selected = append(selected, moduleID)
			}
		}
		return selected
	}
	for _, module := range modules {
		if supports(module.DefaultTargets, targetID) {
			selected = append(selected, module.ModuleID)
		}
	}
	return selected
}

func includeDependencies(modules map[string]model.BundleModule, selected []string) []string {
	set := map[string]bool{}
	queue := append([]string(nil), selected...)
	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		if set[id] {
			continue
		}
		set[id] = true
		for _, dependency := range modules[id].Dependencies {
			queue = append(queue, dependency)
		}
	}
	result := make([]string, 0, len(set))
	for id := range set {
		result = append(result, id)
	}
	return result
}

func findModule(modules []model.BundleModule, id string) *model.BundleModule {
	for index := range modules {
		if modules[index].ModuleID == id {
			return &modules[index]
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
