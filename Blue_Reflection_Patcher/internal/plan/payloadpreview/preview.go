package payloadpreview

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/model"
)

const (
	PreviewType          = "br_local_payload_transaction_preview"
	PreviewFormatVersion = 1
	repackReportRelative = ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
)

type ArtifactPreview struct {
	ModuleID         string `json:"module_id"`
	RelativePath     string `json:"relative_path"`
	SourcePath       string `json:"source_path"`
	SourceSHA256     string `json:"source_sha256,omitempty"`
	SourceBytes      int64  `json:"source_bytes,omitempty"`
	ReportSHA256     string `json:"report_sha256,omitempty"`
	ReportBytes      int64  `json:"report_bytes,omitempty"`
	ReportVerified   bool   `json:"report_verified"`
	TargetPath       string `json:"target_path"`
	TargetExists     bool   `json:"target_exists"`
	TargetSHA256     string `json:"target_sha256,omitempty"`
	TargetBytes      int64  `json:"target_bytes,omitempty"`
	DesiredAction    string `json:"desired_action"`
	TransactionReady bool   `json:"transaction_ready"`
	Status           string `json:"status"`
	Error            string `json:"error,omitempty"`
}

type ModulePreview struct {
	ModuleID         string            `json:"module_id"`
	SourceKind       string            `json:"source_kind"`
	ConnectionStatus string            `json:"connection_status"`
	Ready            bool              `json:"ready"`
	Reason           string            `json:"reason,omitempty"`
	Artifacts        []ArtifactPreview `json:"artifacts"`
}

type TargetPreview struct {
	TargetID           string          `json:"target_id"`
	DisplayName        string          `json:"display_name"`
	GameRoot           string          `json:"game_root"`
	DetectionSource    string          `json:"detection_source"`
	SelectedModules    []string        `json:"selected_modules"`
	StateDirectory     string          `json:"state_directory"`
	Status             string          `json:"status"`
	ReadyArtifactCount int             `json:"ready_artifact_count"`
	PendingModuleCount int             `json:"pending_module_count"`
	Modules            []ModulePreview `json:"modules"`
	Warnings           []string        `json:"warnings"`
}

type Preview struct {
	Type               string          `json:"type"`
	FormatVersion      int             `json:"format_version"`
	Status             string          `json:"status"`
	GeneratedUTC       time.Time       `json:"generated_utc"`
	ProjectRoot        string          `json:"project_root"`
	RepackReport       string          `json:"repack_report"`
	CommitEnabled      bool            `json:"commit_enabled"`
	TransactionPolicy  string          `json:"transaction_policy"`
	DistributionPolicy string          `json:"distribution_policy"`
	Targets            []TargetPreview `json:"targets"`
	Warnings           []string        `json:"warnings"`
}

type repackReport struct {
	Status   string               `json:"status"`
	Archives []repackArchiveEntry `json:"archives"`
}

type repackArchiveEntry struct {
	TargetID            string   `json:"target_id"`
	ArchiveRelativePath string   `json:"archive_relative_path"`
	OutputPath          string   `json:"output_path"`
	OutputSHA256        string   `json:"output_sha256"`
	OutputBytes         int64    `json:"output_bytes"`
	Failures            []string `json:"failures"`
}

func ResolveProjectRoot(explicit string) (string, error) {
	var candidates []string
	if strings.TrimSpace(explicit) != "" {
		candidates = append(candidates, explicit)
	} else {
		if value := strings.TrimSpace(os.Getenv("BR_PROJECT_ROOT")); value != "" {
			candidates = append(candidates, value)
		}
		if executable, err := os.Executable(); err == nil {
			candidates = append(candidates, filepath.Dir(executable))
		}
		if cwd, err := os.Getwd(); err == nil {
			candidates = append(candidates, cwd)
		}
	}
	seen := map[string]bool{}
	for _, candidate := range candidates {
		absolute, err := filepath.Abs(candidate)
		if err != nil {
			continue
		}
		current := filepath.Clean(absolute)
		for {
			if !seen[current] {
				seen[current] = true
				if validProjectRoot(current) {
					return current, nil
				}
			}
			parent := filepath.Dir(current)
			if parent == current {
				break
			}
			current = parent
		}
	}
	if strings.TrimSpace(explicit) != "" {
		return "", fmt.Errorf("not a Blue Reflection project root: %s", explicit)
	}
	return "", fmt.Errorf("project root was not found; pass --project-root PATH or set BR_PROJECT_ROOT")
}

func validProjectRoot(root string) bool {
	for _, relative := range []string{
		"workstreams/core/VERSION",
		"Blue_Reflection_Patcher/go.mod",
		repackReportRelative,
	} {
		info, err := os.Stat(filepath.Join(root, filepath.FromSlash(relative)))
		if err != nil || !info.Mode().IsRegular() {
			return false
		}
	}
	return true
}

func Build(projectRoot, stateBase string, selection model.SelectionResult) (Preview, error) {
	projectRoot, err := ResolveProjectRoot(projectRoot)
	if err != nil {
		return Preview{}, err
	}
	reportPath := filepath.Join(projectRoot, filepath.FromSlash(repackReportRelative))
	report, err := loadRepackReport(reportPath)
	if err != nil {
		return Preview{}, err
	}
	catalog, err := LoadCatalog()
	if err != nil {
		return Preview{}, err
	}
	mapping := map[string]ModuleTargetSpec{}
	for _, spec := range catalog {
		mapping[spec.TargetID+"\x00"+spec.ModuleID] = spec
	}
	preview := Preview{
		Type: PreviewType, FormatVersion: PreviewFormatVersion, Status: "ready",
		GeneratedUTC: time.Now().UTC(), ProjectRoot: projectRoot,
		RepackReport: filepath.ToSlash(repackReportRelative), CommitEnabled: false,
		TransactionPolicy:  "preview verified local artifacts only; no transaction is prepared or committed",
		DistributionPolicy: "development bridge only; final releases use content-aware composition rather than blind whole-PAK replacement",
		Warnings:           []string{},
	}
	for _, selectedTarget := range selection.Targets {
		target := TargetPreview{
			TargetID: selectedTarget.TargetID, DisplayName: selectedTarget.DisplayName,
			GameRoot: selectedTarget.Root, DetectionSource: selectedTarget.DetectionSource,
			SelectedModules: append([]string{}, selectedTarget.SelectedModuleIDs...),
			StateDirectory:  installationStateDirectory(stateBase, selectedTarget.TargetID, selectedTarget.Root),
			Status:          "ready", Warnings: []string{},
		}
		for _, moduleID := range selectedTarget.SelectedModuleIDs {
			spec, ok := mapping[selectedTarget.TargetID+"\x00"+moduleID]
			if !ok {
				module := ModulePreview{ModuleID: moduleID, ConnectionStatus: "unmapped", Ready: false, Reason: "No local payload mapping exists for this module/target pair."}
				target.Modules = append(target.Modules, module)
				target.PendingModuleCount++
				target.Warnings = append(target.Warnings, fmt.Sprintf("%s is selected but has no local payload mapping", moduleID))
				continue
			}
			module := ModulePreview{
				ModuleID: moduleID, SourceKind: spec.SourceKind,
				ConnectionStatus: spec.ConnectionStatus, Reason: spec.Reason,
				Ready: spec.ConnectionStatus == "connected_preview_only",
			}
			if !module.Ready {
				target.PendingModuleCount++
				target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, spec.Reason))
			} else {
				for _, artifactSpec := range spec.Artifacts {
					artifact := inspectArtifact(projectRoot, selectedTarget.Root, selectedTarget.TargetID, moduleID, artifactSpec.RelativePath, report)
					module.Artifacts = append(module.Artifacts, artifact)
					if artifact.TransactionReady {
						target.ReadyArtifactCount++
					} else {
						module.Ready = false
					}
				}
				if !module.Ready {
					target.PendingModuleCount++
					target.Warnings = append(target.Warnings, fmt.Sprintf("%s has missing or unverified local build artifacts", moduleID))
				}
			}
			target.Modules = append(target.Modules, module)
		}
		switch {
		case len(target.SelectedModules) == 0:
			target.Status = "no_modules_selected"
		case target.PendingModuleCount == 0:
			target.Status = "ready"
		case target.ReadyArtifactCount > 0:
			target.Status = "partial"
		default:
			target.Status = "not_ready"
		}
		preview.Targets = append(preview.Targets, target)
	}
	for _, target := range preview.Targets {
		switch target.Status {
		case "not_ready":
			preview.Status = "not_ready"
		case "partial":
			if preview.Status == "ready" {
				preview.Status = "partial"
			}
		}
		preview.Warnings = append(preview.Warnings, target.Warnings...)
	}
	if len(preview.Targets) == 0 {
		preview.Status = "not_ready"
		preview.Warnings = append(preview.Warnings, "no selected target was supplied")
	}
	return preview, nil
}

func loadRepackReport(path string) (repackReport, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return repackReport{}, fmt.Errorf("read translation repack report: %w", err)
	}
	var report repackReport
	if err := json.Unmarshal(data, &report); err != nil {
		return repackReport{}, fmt.Errorf("decode translation repack report: %w", err)
	}
	if report.Status != "ok" {
		return repackReport{}, fmt.Errorf("translation repack report status is %q, expected ok", report.Status)
	}
	return report, nil
}

func inspectArtifact(projectRoot, gameRoot, targetID, moduleID, relative string, report repackReport) ArtifactPreview {
	result := ArtifactPreview{ModuleID: moduleID, RelativePath: filepath.ToSlash(relative), Status: "invalid", DesiredAction: "blocked"}
	entry, ok := findReportEntry(report, targetID, relative)
	if !ok {
		result.Error = "archive is absent from the verified translation repack report"
		return result
	}
	if len(entry.Failures) != 0 {
		result.Error = "archive verification report contains failures"
		return result
	}
	source, err := secureProjectPath(projectRoot, entry.OutputPath)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	result.SourcePath = source
	result.ReportSHA256 = entry.OutputSHA256
	result.ReportBytes = entry.OutputBytes
	info, err := os.Lstat(source)
	if err != nil {
		result.Error = fmt.Sprintf("inspect local build artifact: %v", err)
		return result
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		result.Error = "local build artifact is not a regular file"
		return result
	}
	result.SourceBytes = info.Size()
	result.SourceSHA256, err = hashFile(source)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	if result.SourceSHA256 != entry.OutputSHA256 || result.SourceBytes != entry.OutputBytes {
		result.Error = "local build artifact does not match the verified repack report"
		return result
	}
	result.ReportVerified = true
	targetPath, exists, err := resolveTargetPath(gameRoot, relative)
	result.TargetPath = targetPath
	if err != nil {
		result.Error = err.Error()
		return result
	}
	result.TargetExists = exists
	if !exists {
		result.DesiredAction = "add"
		result.TransactionReady = true
		result.Status = "ready"
		return result
	}
	targetInfo, err := os.Lstat(targetPath)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	if targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() {
		result.Error = "game target is not a regular file"
		return result
	}
	result.TargetBytes = targetInfo.Size()
	result.TargetSHA256, err = hashFile(targetPath)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	if result.TargetSHA256 == result.SourceSHA256 {
		result.DesiredAction = "noop"
	} else {
		result.DesiredAction = "replace"
	}
	result.TransactionReady = true
	result.Status = "ready"
	return result
}

func findReportEntry(report repackReport, targetID, relative string) (repackArchiveEntry, bool) {
	folded := strings.ToLower(filepath.ToSlash(filepath.Clean(filepath.FromSlash(relative))))
	for _, entry := range report.Archives {
		if entry.TargetID == targetID && strings.ToLower(filepath.ToSlash(filepath.Clean(filepath.FromSlash(entry.ArchiveRelativePath)))) == folded {
			return entry, true
		}
	}
	return repackArchiveEntry{}, false
}

func secureProjectPath(projectRoot, raw string) (string, error) {
	if strings.TrimSpace(raw) == "" || filepath.IsAbs(raw) {
		return "", fmt.Errorf("repack report output path must be project-relative: %q", raw)
	}
	clean := filepath.Clean(filepath.FromSlash(raw))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("repack report output path escapes project root: %q", raw)
	}
	joined := filepath.Join(projectRoot, clean)
	relative, err := filepath.Rel(projectRoot, joined)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("repack report output path escapes project root: %q", raw)
	}
	return joined, nil
}

func resolveTargetPath(root, relative string) (string, bool, error) {
	absolute, err := filepath.Abs(root)
	if err != nil {
		return "", false, err
	}
	clean := filepath.Clean(filepath.FromSlash(relative))
	if filepath.IsAbs(clean) || clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", false, fmt.Errorf("unsafe game-relative artifact path: %s", relative)
	}
	current := absolute
	parts := strings.Split(clean, string(filepath.Separator))
	for index, part := range parts {
		entries, readErr := os.ReadDir(current)
		if errors.Is(readErr, os.ErrNotExist) {
			return filepath.Join(current, filepath.Join(parts[index:]...)), false, nil
		}
		if readErr != nil {
			return "", false, readErr
		}
		matched := ""
		for _, entry := range entries {
			if strings.EqualFold(entry.Name(), part) {
				if matched != "" && matched != entry.Name() {
					return "", false, fmt.Errorf("ambiguous case-insensitive path under %s: %s", current, part)
				}
				matched = entry.Name()
			}
		}
		if matched == "" {
			return filepath.Join(current, filepath.Join(parts[index:]...)), false, nil
		}
		current = filepath.Join(current, matched)
	}
	return current, true, nil
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func installationStateDirectory(base, targetID, gameRoot string) string {
	absolute, err := filepath.Abs(gameRoot)
	if err != nil {
		absolute = filepath.Clean(gameRoot)
	}
	hash := sha256.Sum256([]byte(filepath.Clean(absolute)))
	key := hex.EncodeToString(hash[:8])
	return filepath.Join(base, "unburger-patcher", "blue-reflection", "installations", targetID+"-"+key)
}

func SortedArtifactPaths(preview Preview) []string {
	var result []string
	for _, target := range preview.Targets {
		for _, module := range target.Modules {
			for _, artifact := range module.Artifacts {
				result = append(result, target.TargetID+":"+artifact.RelativePath)
			}
		}
	}
	sort.Strings(result)
	return result
}
