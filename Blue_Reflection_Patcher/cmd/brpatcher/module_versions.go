package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var moduleVersionSources = map[string]string{
	quartetTranslationModule: "workstreams/translation/VERSION",
	quartetRestorationModule: "workstreams/quartet_restoration/VERSION",
	quartetLegacyDLCModule:   "workstreams/quartet_legacy_dlc/VERSION",
}

var moduleVersionTSVKeys = map[string]string{
	quartetTranslationModule: "translation",
	quartetRestorationModule: "quartet_restoration",
	quartetLegacyDLCModule:   "quartet_legacy_dlc",
}

func selectedVersionedContentIndicators(projectRoot, targetID string, modules []string) ([]string, error) {
	if targetID != "blue_reflection_quartet" {
		return nil, nil
	}
	versions, err := loadModuleVersions(projectRoot)
	if err != nil {
		return nil, err
	}
	out := []string{}
	if contains(modules, quartetTranslationModule) {
		version, err := requireModuleVersion(versions, quartetTranslationModule)
		if err != nil {
			return nil, err
		}
		out = append(out, fmt.Sprintf("UNBURGER (v%s)", version))
	}
	if contains(modules, quartetRestorationModule) {
		version, err := requireModuleVersion(versions, quartetRestorationModule)
		if err != nil {
			return nil, err
		}
		out = append(out, fmt.Sprintf("UNCENSOR (v%s)", version))
	}
	if contains(modules, quartetLegacyDLCModule) {
		version, err := requireModuleVersion(versions, quartetLegacyDLCModule)
		if err != nil {
			return nil, err
		}
		out = append(out, fmt.Sprintf("DLC (v%s)", version))
	}
	return out, nil
}

func loadModuleVersions(projectRoot string) (map[string]string, error) {
	versions := map[string]string{}
	metadataPath := filepath.Join(projectRoot, "meta", "MODULE_VERSIONS.tsv")
	if file, err := os.Open(metadataPath); err == nil {
		defer file.Close()
		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			fields := strings.SplitN(line, "\t", 2)
			if len(fields) != 2 {
				return nil, fmt.Errorf("invalid module version metadata line in %s: %q", metadataPath, line)
			}
			key := strings.TrimSpace(fields[0])
			value := strings.TrimSpace(fields[1])
			if key != "" && value != "" {
				versions[key] = value
			}
		}
		if err := scanner.Err(); err != nil {
			return nil, fmt.Errorf("read module version metadata: %w", err)
		}
	} else if !os.IsNotExist(err) {
		return nil, fmt.Errorf("open module version metadata: %w", err)
	}

	result := map[string]string{}
	for moduleID, key := range moduleVersionTSVKeys {
		if value := strings.TrimSpace(versions[key]); value != "" {
			result[moduleID] = value
			continue
		}
		relative := moduleVersionSources[moduleID]
		data, err := os.ReadFile(filepath.Join(projectRoot, filepath.FromSlash(relative)))
		if err != nil {
			if os.IsNotExist(err) {
				continue
			}
			return nil, fmt.Errorf("read %s version: %w", moduleID, err)
		}
		if value := strings.TrimSpace(string(data)); value != "" {
			result[moduleID] = value
		}
	}
	return result, nil
}

func requireModuleVersion(versions map[string]string, moduleID string) (string, error) {
	version := strings.TrimSpace(versions[moduleID])
	if version == "" {
		return "", fmt.Errorf("missing version metadata for selected module %s", moduleID)
	}
	for _, char := range version {
		if (char < '0' || char > '9') && char != '.' {
			return "", fmt.Errorf("unsupported display version %q for selected module %s", version, moduleID)
		}
	}
	return version, nil
}
