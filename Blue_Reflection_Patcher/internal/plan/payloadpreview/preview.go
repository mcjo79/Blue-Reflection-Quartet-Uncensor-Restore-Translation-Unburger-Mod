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
	"reflect"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/model"
)

const (
	PreviewType                       = "br_local_payload_transaction_preview"
	PreviewFormatVersion              = 2
	repackReportRelative              = ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
	compositionReportRelative         = ".local/reports/core/BR_QUARTET_COMPOSITION_BUILD_REPORT.json"
	compositionOutputRelative         = ".local/build/composition/blue_reflection_quartet"
	compositionEmbeddedReportRelative = ".local/build/composition/blue_reflection_quartet/BR_QUARTET_COMPOSITION_BUILD_REPORT.json"
	compositionReportType             = "br_quartet_translation_restoration_composition_build"
	quartetTargetID                   = "blue_reflection_quartet"
)

type ArtifactPreview struct {
	ModuleID            string `json:"module_id"`
	RelativePath        string `json:"relative_path"`
	SourcePath          string `json:"source_path"`
	SourceSHA256        string `json:"source_sha256,omitempty"`
	SourceBytes         int64  `json:"source_bytes,omitempty"`
	ReportSHA256        string `json:"report_sha256,omitempty"`
	ReportBytes         int64  `json:"report_bytes,omitempty"`
	ReportVerified      bool   `json:"report_verified"`
	CompositionVerified bool   `json:"composition_verified,omitempty"`
	SourceReport        string `json:"source_report,omitempty"`
	TargetPath          string `json:"target_path"`
	TargetExists        bool   `json:"target_exists"`
	TargetSHA256        string `json:"target_sha256,omitempty"`
	TargetBytes         int64  `json:"target_bytes,omitempty"`
	DesiredAction       string `json:"desired_action"`
	TransactionReady    bool   `json:"transaction_ready"`
	Status              string `json:"status"`
	Error               string `json:"error,omitempty"`
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
	CompositionReport  string          `json:"composition_report,omitempty"`
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

type compositionBuildReport struct {
	Type                          string                         `json:"type"`
	FormatVersion                 int                            `json:"format_version"`
	Status                        string                         `json:"status"`
	ProjectRoot                   string                         `json:"project_root"`
	GameRoot                      string                         `json:"game_root"`
	TargetID                      string                         `json:"target_id"`
	CommitEnabled                 bool                           `json:"commit_enabled"`
	PreflightStatus               string                         `json:"preflight_status"`
	OutputRoot                    string                         `json:"output_root"`
	EmbeddedReportPath            string                         `json:"embedded_report_path"`
	TranslationLooseReportPath    string                         `json:"translation_loose_report_path"`
	TranslationLooseReportSHA256  string                         `json:"translation_loose_report_sha256"`
	TranslationLooseReportBytes   int64                          `json:"translation_loose_report_bytes"`
	TranslationRepackReportPath   string                         `json:"translation_repack_report_path"`
	TranslationRepackReportSHA256 string                         `json:"translation_repack_report_sha256"`
	TranslationRepackReportBytes  int64                          `json:"translation_repack_report_bytes"`
	ProductionProfileIDs          []string                       `json:"production_profile_ids"`
	ProfileInputs                 []compositionBuildProfileInput `json:"profile_inputs"`
	Archives                      []compositionBuildArchive      `json:"archives"`
	PublishedArchiveCount         int                            `json:"published_archive_count"`
	ComposedArchiveCount          int                            `json:"composed_archive_count"`
	PassthroughArchiveCount       int                            `json:"passthrough_archive_count"`
	FullReextractCount            int                            `json:"full_reextract_count"`
	Errors                        []string                       `json:"errors"`
}

type compositionBuildProfileInput struct {
	ProfileID          string `json:"profile_id"`
	ManifestPath       string `json:"manifest_path"`
	ManifestSHA256     string `json:"manifest_sha256"`
	ManifestBytes      int64  `json:"manifest_bytes"`
	PayloadPath        string `json:"payload_path"`
	PayloadSHA256      string `json:"payload_sha256"`
	PayloadBytes       int64  `json:"payload_bytes"`
	TargetRelativePath string `json:"target_relative_path"`
	BaselineSHA256     string `json:"baseline_sha256"`
	BaselineBytes      int64  `json:"baseline_bytes"`
	RuntimeValidated   bool   `json:"runtime_validated"`
}

type currentProfileManifest struct {
	SchemaVersion      int    `json:"schema_version"`
	ProfileID          string `json:"profile_id"`
	TargetRelativePath string `json:"target_relative_path"`
	BaselineSHA256     string `json:"baseline_sha256"`
	BaselineSize       int64  `json:"baseline_size"`
	ProfileSHA256      string `json:"profile_sha256"`
	ProfileSize        int64  `json:"profile_size"`
	LocalProfilePath   string `json:"local_profile_path"`
	RuntimeValidated   bool   `json:"runtime_validated"`
	WorkstreamID       string `json:"workstream_id"`
}

type compositionBuildArchive struct {
	ArchiveRelativePath        string   `json:"archive_relative_path"`
	Mode                       string   `json:"mode"`
	BaseSourceKind             string   `json:"base_source_kind"`
	BaseSourcePath             string   `json:"base_source_path"`
	BaseSHA256                 string   `json:"base_sha256"`
	BaseBytes                  int64    `json:"base_bytes"`
	InstalledBaselineSHA256    string   `json:"installed_baseline_sha256"`
	InstalledBaselineBytes     int64    `json:"installed_baseline_bytes"`
	OutputPath                 string   `json:"output_path"`
	OutputSHA256               string   `json:"output_sha256"`
	OutputBytes                int64    `json:"output_bytes"`
	FullReextractVerified      bool     `json:"full_reextract_verified"`
	ManifestDeclarationChecked bool     `json:"manifest_declaration_checked"`
	Status                     string   `json:"status"`
	ProfileIDs                 []string `json:"profile_ids"`
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
		RepackReport: filepath.ToSlash(repackReportRelative), CompositionReport: filepath.ToSlash(compositionReportRelative), CommitEnabled: false,
		TransactionPolicy:  "preview verified local artifacts only; no transaction is prepared or committed",
		DistributionPolicy: "translation-only uses verified translation archives; Quartet translation+restoration requires the fully verified content-aware composition set",
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
		selectedSet := map[string]bool{}
		for _, moduleID := range selectedTarget.SelectedModuleIDs {
			selectedSet[moduleID] = true
		}
		compositionPair := selectedTarget.TargetID == quartetTargetID && selectedSet["blue_reflection_translation"] && selectedSet["quartet_restoration"]
		compositionModules := map[string]ModulePreview{}
		if compositionPair {
			compositionModules, target.Warnings = buildQuartetCompositionModulePreview(projectRoot, selectedTarget.Root, report)
		}
		for _, moduleID := range selectedTarget.SelectedModuleIDs {
			if module, ok := compositionModules[moduleID]; ok {
				target.Modules = append(target.Modules, module)
				if !module.Ready {
					target.PendingModuleCount++
				}
				for _, artifact := range module.Artifacts {
					if artifact.TransactionReady {
						target.ReadyArtifactCount++
					}
				}
				continue
			}
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

func buildQuartetCompositionModulePreview(projectRoot, gameRoot string, repack repackReport) (map[string]ModulePreview, []string) {
	translation := ModulePreview{
		ModuleID: "blue_reflection_translation", SourceKind: "verified_content_aware_composition",
		ConnectionStatus: "composition_build_required", Ready: false,
		Reason:    "Quartet translation and restoration were selected together; a matching verified composition build is required before transaction preview.",
		Artifacts: []ArtifactPreview{},
	}
	restoration := ModulePreview{
		ModuleID: "quartet_restoration", SourceKind: "verified_content_aware_composition",
		ConnectionStatus: "composition_build_required", Ready: false,
		Reason:    "Quartet translation and restoration were selected together; a matching verified composition build is required before transaction preview.",
		Artifacts: []ArtifactPreview{},
	}
	result := map[string]ModulePreview{
		translation.ModuleID: translation,
		restoration.ModuleID: restoration,
	}
	archives, err := loadVerifiedCompositionArtifacts(projectRoot, gameRoot, repack)
	if err != nil {
		message := fmt.Sprintf("Quartet composition payloads are unavailable: %v", err)
		translation.Reason = message
		restoration.Reason = message
		result[translation.ModuleID] = translation
		result[restoration.ModuleID] = restoration
		return result, []string{message}
	}
	translation.ConnectionStatus = "connected_composition_preview_only"
	translation.Ready = true
	translation.Reason = "Artifacts come from the verified content-aware Quartet translation+restoration composition set."
	translation.Artifacts = archives
	for _, artifact := range archives {
		if !artifact.TransactionReady {
			translation.Ready = false
		}
	}
	restoration.ConnectionStatus = "connected_composition_preview_only"
	restoration.Ready = translation.Ready
	restoration.Reason = "Included in the shared verified composition set; artifacts are listed once under Translation to prevent duplicate transaction paths."
	result[translation.ModuleID] = translation
	result[restoration.ModuleID] = restoration
	if !translation.Ready {
		return result, []string{"one or more verified composition artifacts could not enter the transaction preview"}
	}
	return result, []string{}
}

func loadVerifiedCompositionArtifacts(projectRoot, gameRoot string, repack repackReport) ([]ArtifactPreview, error) {
	reportPath := filepath.Join(projectRoot, filepath.FromSlash(compositionReportRelative))
	canonicalBytes, err := os.ReadFile(reportPath)
	if err != nil {
		return nil, fmt.Errorf("read composition build report: %w", err)
	}
	var report compositionBuildReport
	if err := json.Unmarshal(canonicalBytes, &report); err != nil {
		return nil, fmt.Errorf("decode composition build report: %w", err)
	}
	if report.Type != compositionReportType || report.FormatVersion != 2 {
		return nil, fmt.Errorf("unsupported composition report type/version")
	}
	if report.Status != "ok" || report.CommitEnabled {
		return nil, fmt.Errorf("composition report is not a completed preview-only build")
	}
	if report.TargetID != quartetTargetID || report.PreflightStatus != "ready_for_composition_build" {
		return nil, fmt.Errorf("composition report target/preflight mismatch")
	}
	if len(report.ProductionProfileIDs) == 0 {
		return nil, fmt.Errorf("composition report contains no production-eligible restoration profiles")
	}
	if len(report.Errors) != 0 {
		return nil, fmt.Errorf("composition report contains errors")
	}
	if err := verifyProjectFileFingerprint(projectRoot, report.TranslationLooseReportPath, report.TranslationLooseReportSHA256, report.TranslationLooseReportBytes); err != nil {
		return nil, fmt.Errorf("stale composition input: %w", err)
	}
	if err := verifyProjectFileFingerprint(projectRoot, report.TranslationRepackReportPath, report.TranslationRepackReportSHA256, report.TranslationRepackReportBytes); err != nil {
		return nil, fmt.Errorf("stale composition input: %w", err)
	}
	if err := verifyCurrentProfileInputs(projectRoot, report); err != nil {
		return nil, fmt.Errorf("stale composition profile inputs: %w", err)
	}
	if !sameFilesystemPath(report.ProjectRoot, projectRoot) {
		return nil, fmt.Errorf("composition report belongs to a different project root")
	}
	if !sameFilesystemPath(report.GameRoot, gameRoot) {
		return nil, fmt.Errorf("composition report belongs to a different Quartet installation")
	}
	if filepath.ToSlash(filepath.Clean(filepath.FromSlash(report.OutputRoot))) != compositionOutputRelative {
		return nil, fmt.Errorf("unexpected composition output root: %s", report.OutputRoot)
	}
	if filepath.ToSlash(filepath.Clean(filepath.FromSlash(report.EmbeddedReportPath))) != compositionEmbeddedReportRelative {
		return nil, fmt.Errorf("unexpected embedded composition report path: %s", report.EmbeddedReportPath)
	}
	if report.PublishedArchiveCount != len(report.Archives) || report.ComposedArchiveCount+report.PassthroughArchiveCount != len(report.Archives) || report.FullReextractCount != report.ComposedArchiveCount {
		return nil, fmt.Errorf("composition report archive counters are inconsistent")
	}
	embeddedPath, err := secureProjectPath(projectRoot, compositionEmbeddedReportRelative)
	if err != nil {
		return nil, err
	}
	embeddedBytes, err := os.ReadFile(embeddedPath)
	if err != nil {
		return nil, fmt.Errorf("read embedded composition report: %w", err)
	}
	var canonicalJSON, embeddedJSON any
	if err := json.Unmarshal(canonicalBytes, &canonicalJSON); err != nil {
		return nil, err
	}
	if err := json.Unmarshal(embeddedBytes, &embeddedJSON); err != nil {
		return nil, fmt.Errorf("decode embedded composition report: %w", err)
	}
	if !reflect.DeepEqual(canonicalJSON, embeddedJSON) {
		return nil, fmt.Errorf("embedded composition report differs from the canonical report")
	}
	required := map[string]bool{
		strings.ToLower("Data/PACK11.PAK"):       false,
		strings.ToLower("Data/PACK12.PAK"):       false,
		strings.ToLower("Data/PACK00_04_01.PAK"): false,
	}
	seen := map[string]bool{}
	artifacts := make([]ArtifactPreview, 0, len(report.Archives))
	for _, archive := range report.Archives {
		relative, err := cleanArtifactRelative(archive.ArchiveRelativePath)
		if err != nil {
			return nil, err
		}
		key := strings.ToLower(filepath.ToSlash(relative))
		if seen[key] {
			return nil, fmt.Errorf("duplicate composition archive: %s", archive.ArchiveRelativePath)
		}
		seen[key] = true
		if _, ok := required[key]; ok {
			required[key] = true
		}
		expectedOutput := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(relative)))
		actualOutput := filepath.ToSlash(filepath.Clean(filepath.FromSlash(archive.OutputPath)))
		if actualOutput != expectedOutput {
			return nil, fmt.Errorf("composition archive output path mismatch for %s", relative)
		}
		if archive.BaseSourceKind == "verified_translation_archive" || archive.Mode == "verified_translation_passthrough" {
			entry, ok := findReportEntry(repack, quartetTargetID, relative)
			if !ok || len(entry.Failures) != 0 || entry.OutputSHA256 != archive.BaseSHA256 || entry.OutputBytes != archive.BaseBytes {
				return nil, fmt.Errorf("composition translation base is stale for %s", relative)
			}
			if err := verifyProjectFileFingerprint(projectRoot, entry.OutputPath, entry.OutputSHA256, entry.OutputBytes); err != nil {
				return nil, fmt.Errorf("composition translation base is stale for %s: %w", relative, err)
			}
		}
		switch archive.Mode {
		case "verified_translation_passthrough":
			if archive.Status != "published_verified_translation_passthrough" || !archive.ManifestDeclarationChecked {
				return nil, fmt.Errorf("unverified translation passthrough archive: %s", relative)
			}
		case "member_overlay":
			if archive.Status != "published_member_overlay_verified" || !archive.ManifestDeclarationChecked || !archive.FullReextractVerified {
				return nil, fmt.Errorf("unverified member-overlay archive: %s", relative)
			}
		default:
			return nil, fmt.Errorf("unsupported composition archive mode %q for %s", archive.Mode, relative)
		}
		artifact := inspectCompositionArtifact(projectRoot, gameRoot, relative, archive)
		artifacts = append(artifacts, artifact)
	}
	for relative, present := range required {
		if !present {
			return nil, fmt.Errorf("composition set is missing required translation archive: %s", relative)
		}
	}
	sort.Slice(artifacts, func(i, j int) bool { return artifacts[i].RelativePath < artifacts[j].RelativePath })
	return artifacts, nil
}

func inspectCompositionArtifact(projectRoot, gameRoot, relative string, archive compositionBuildArchive) ArtifactPreview {
	result := ArtifactPreview{
		ModuleID: "blue_reflection_translation", RelativePath: filepath.ToSlash(relative),
		Status: "invalid", DesiredAction: "blocked", SourceReport: filepath.ToSlash(compositionReportRelative),
		ReportSHA256: archive.OutputSHA256, ReportBytes: archive.OutputBytes,
	}
	source, err := secureProjectPath(projectRoot, archive.OutputPath)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	result.SourcePath = source
	info, err := os.Lstat(source)
	if err != nil {
		result.Error = fmt.Sprintf("inspect composition artifact: %v", err)
		return result
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		result.Error = "composition artifact is not a regular file"
		return result
	}
	result.SourceBytes = info.Size()
	result.SourceSHA256, err = hashFile(source)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	if result.SourceSHA256 != archive.OutputSHA256 || result.SourceBytes != archive.OutputBytes {
		result.Error = "composition artifact does not match the verified composition report"
		return result
	}
	result.ReportVerified = true
	result.CompositionVerified = true
	targetPath, exists, err := resolveTargetPath(gameRoot, relative)
	result.TargetPath = targetPath
	if err != nil {
		result.Error = err.Error()
		return result
	}
	result.TargetExists = exists
	if !exists {
		result.Error = "game archive disappeared after the composition build"
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
	if archive.Mode == "member_overlay" && result.TargetSHA256 != result.SourceSHA256 {
		allowed := result.TargetSHA256 == archive.InstalledBaselineSHA256 || result.TargetSHA256 == archive.BaseSHA256
		if !allowed {
			result.Error = "game archive changed after the composition build and no longer matches its verified baseline/base"
			return result
		}
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

func verifyProjectFileFingerprint(projectRoot, relative, expectedHash string, expectedBytes int64) error {
	if strings.TrimSpace(relative) == "" || strings.TrimSpace(expectedHash) == "" || expectedBytes < 0 {
		return fmt.Errorf("missing file fingerprint metadata for %q", relative)
	}
	path, err := secureProjectPath(projectRoot, relative)
	if err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return fmt.Errorf("fingerprinted path is not a regular file: %s", relative)
	}
	hash, err := hashFile(path)
	if err != nil {
		return err
	}
	if hash != expectedHash || info.Size() != expectedBytes {
		return fmt.Errorf("fingerprint mismatch for %s", relative)
	}
	return nil
}

func verifyCurrentProfileInputs(projectRoot string, report compositionBuildReport) error {
	if len(report.ProfileInputs) != len(report.ProductionProfileIDs) {
		return fmt.Errorf("profile input count does not match production profile count")
	}
	expected := map[string]bool{}
	for _, id := range report.ProductionProfileIDs {
		if strings.TrimSpace(id) == "" || expected[id] {
			return fmt.Errorf("invalid or duplicate production profile id: %q", id)
		}
		expected[id] = true
	}
	for _, input := range report.ProfileInputs {
		if !expected[input.ProfileID] || !input.RuntimeValidated {
			return fmt.Errorf("unexpected or non-runtime profile input: %s", input.ProfileID)
		}
		if err := verifyProjectFileFingerprint(projectRoot, input.ManifestPath, input.ManifestSHA256, input.ManifestBytes); err != nil {
			return fmt.Errorf("profile %s manifest: %w", input.ProfileID, err)
		}
		if err := verifyProjectFileFingerprint(projectRoot, input.PayloadPath, input.PayloadSHA256, input.PayloadBytes); err != nil {
			return fmt.Errorf("profile %s payload: %w", input.ProfileID, err)
		}
		manifestPath, _ := secureProjectPath(projectRoot, input.ManifestPath)
		data, err := os.ReadFile(manifestPath)
		if err != nil {
			return err
		}
		var manifest currentProfileManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			return fmt.Errorf("decode profile %s manifest: %w", input.ProfileID, err)
		}
		if manifest.SchemaVersion != 1 || manifest.WorkstreamID != "quartet_restoration" || !manifest.RuntimeValidated || manifest.ProfileID != input.ProfileID || manifest.TargetRelativePath != input.TargetRelativePath || manifest.BaselineSHA256 != input.BaselineSHA256 || manifest.BaselineSize != input.BaselineBytes || manifest.ProfileSHA256 != input.PayloadSHA256 || manifest.ProfileSize != input.PayloadBytes {
			return fmt.Errorf("profile %s manifest no longer matches the composition input", input.ProfileID)
		}
	}
	manifestRoot, err := secureProjectPath(projectRoot, ".local/build/quartet_restoration/core_profiles")
	if err != nil {
		return err
	}
	current := map[string]bool{}
	entries, err := os.ReadDir(manifestRoot)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			continue
		}
		path := filepath.Join(manifestRoot, entry.Name())
		info, err := os.Lstat(path)
		if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return fmt.Errorf("invalid profile manifest entry: %s", entry.Name())
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var manifest currentProfileManifest
		if json.Unmarshal(data, &manifest) == nil && manifest.SchemaVersion == 1 && manifest.WorkstreamID == "quartet_restoration" && manifest.RuntimeValidated {
			current[manifest.ProfileID] = true
		}
	}
	if !reflect.DeepEqual(current, expected) {
		return fmt.Errorf("runtime-validated profile set changed after composition build")
	}
	return nil
}

func cleanArtifactRelative(raw string) (string, error) {
	clean := filepath.Clean(filepath.FromSlash(raw))
	if strings.TrimSpace(raw) == "" || filepath.IsAbs(clean) || clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("unsafe composition archive path: %q", raw)
	}
	return filepath.ToSlash(clean), nil
}

func sameFilesystemPath(left, right string) bool {
	canonical := func(value string) string {
		absolute, err := filepath.Abs(value)
		if err != nil {
			return filepath.Clean(value)
		}
		if evaluated, err := filepath.EvalSymlinks(absolute); err == nil {
			absolute = evaluated
		}
		return filepath.Clean(absolute)
	}
	left = canonical(left)
	right = canonical(right)
	if filepath.Separator == '\\' {
		return strings.EqualFold(left, right)
	}
	return left == right
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
