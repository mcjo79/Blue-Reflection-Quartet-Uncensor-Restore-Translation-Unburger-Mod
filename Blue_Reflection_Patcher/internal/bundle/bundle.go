package bundle

import (
	"archive/zip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

func Load(path string) (model.BundleManifest, error) {
	if strings.EqualFold(filepath.Ext(path), ".json") {
		data, err := os.ReadFile(path)
		if err != nil {
			return model.BundleManifest{}, err
		}
		return decode(data)
	}
	reader, err := zip.OpenReader(path)
	if err != nil {
		return model.BundleManifest{}, fmt.Errorf("open patch bundle: %w", err)
	}
	defer reader.Close()
	for _, file := range reader.File {
		if filepath.ToSlash(file.Name) != "manifest.json" {
			continue
		}
		handle, err := file.Open()
		if err != nil {
			return model.BundleManifest{}, err
		}
		data, readErr := io.ReadAll(handle)
		closeErr := handle.Close()
		if readErr != nil {
			return model.BundleManifest{}, readErr
		}
		if closeErr != nil {
			return model.BundleManifest{}, closeErr
		}
		return decode(data)
	}
	return model.BundleManifest{}, fmt.Errorf("patch bundle has no manifest.json")
}

func decode(data []byte) (model.BundleManifest, error) {
	var manifest model.BundleManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return manifest, fmt.Errorf("decode bundle manifest: %w", err)
	}
	if err := Validate(manifest); err != nil {
		return manifest, err
	}
	return manifest, nil
}

func Validate(manifest model.BundleManifest) error {
	if manifest.Type != model.BundleType || manifest.FormatVersion != model.BundleFormatVersion {
		return fmt.Errorf("unsupported bundle type/version")
	}
	if manifest.BundleID == "" || manifest.BundleVersion == "" {
		return fmt.Errorf("bundle id and version are required")
	}
	if manifest.Compatibility.Mode != "content_aware_rebuild" {
		return fmt.Errorf("unsupported compatibility mode: %s", manifest.Compatibility.Mode)
	}
	if manifest.Compatibility.RequireWholeArchiveHash {
		return fmt.Errorf("whole-archive hash dependence is forbidden")
	}
	if !manifest.Compatibility.PreserveUnknownEntries {
		return fmt.Errorf("bundle must preserve unknown archive entries")
	}

	targets := map[string]bool{}
	for _, target := range manifest.Targets {
		if target.TargetID == "" || targets[target.TargetID] {
			return fmt.Errorf("invalid or duplicate target id: %s", target.TargetID)
		}
		targets[target.TargetID] = true
	}
	modules := map[string]model.BundleModule{}
	for _, module := range manifest.Modules {
		if module.ModuleID == "" {
			return fmt.Errorf("module id is required")
		}
		if _, exists := modules[module.ModuleID]; exists {
			return fmt.Errorf("duplicate module id: %s", module.ModuleID)
		}
		for _, targetID := range module.SupportedTargets {
			if !targets[targetID] {
				return fmt.Errorf("module %s references unknown target %s", module.ModuleID, targetID)
			}
		}
		modules[module.ModuleID] = module
	}
	for _, module := range manifest.Modules {
		for _, dependency := range module.Dependencies {
			if _, ok := modules[dependency]; !ok {
				return fmt.Errorf("module %s has unknown dependency %s", module.ModuleID, dependency)
			}
		}
	}
	operations := map[string]bool{}
	for _, operation := range manifest.Operations {
		if operation.OperationID == "" || operations[operation.OperationID] {
			return fmt.Errorf("invalid or duplicate operation id: %s", operation.OperationID)
		}
		operations[operation.OperationID] = true
		if _, ok := modules[operation.ModuleID]; !ok {
			return fmt.Errorf("operation %s references unknown module %s", operation.OperationID, operation.ModuleID)
		}
		if !targets[operation.TargetID] {
			return fmt.Errorf("operation %s references unknown target %s", operation.OperationID, operation.TargetID)
		}
		if !validOperationKind(operation.Kind) {
			return fmt.Errorf("operation %s has unsupported kind %s", operation.OperationID, operation.Kind)
		}
		if !validConflictPolicy(operation.ConflictPolicy) {
			return fmt.Errorf("operation %s has unsupported conflict policy %s", operation.OperationID, operation.ConflictPolicy)
		}
		if operation.ArchivePath == "" || operation.EntryPath == "" {
			return fmt.Errorf("operation %s lacks archive/entry path", operation.OperationID)
		}
	}
	return nil
}

func validOperationKind(kind string) bool {
	switch kind {
	case "merge_ebm_records", "merge_xml_records", "replace_entry", "copy_owned_entry", "add_entry", "delete_entry", "edit_table_records":
		return true
	default:
		return false
	}
}

func validConflictPolicy(policy string) bool {
	switch policy {
	case "structured_merge", "known_base_or_prompt", "backup_and_replace", "skip_unknown", "user_choice":
		return true
	default:
		return false
	}
}
