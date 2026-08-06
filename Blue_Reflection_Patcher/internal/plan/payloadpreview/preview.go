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
	translationRepackReportType       = "br_translation_pak_repack_report"
	minimumTranslationVersion         = "0.0.113"
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
	Type                      string               `json:"type"`
	FormatVersion             int                  `json:"format_version"`
	Status                    string               `json:"status"`
	TranslationVersion        string               `json:"translation_version"`
	TranslationToolingVersion string               `json:"translation_tooling_version"`
	MinimumTranslationVersion string               `json:"minimum_translation_version"`
	CanonicalInputFingerprint string               `json:"canonical_input_fingerprint"`
	LooseReportPath           string               `json:"loose_report_path"`
	LooseReportSHA256         string               `json:"loose_report_sha256"`
	LooseReportBytes          int64                `json:"loose_report_bytes"`
	SelectedTargets           []string             `json:"selected_targets"`
	Archives                  []repackArchiveEntry `json:"archives"`
}

type repackArchiveEntry struct {
	TargetID              string   `json:"target_id"`
	ArchiveRelativePath   string   `json:"archive_relative_path"`
	OutputPath            string   `json:"output_path"`
	OutputSHA256          string   `json:"output_sha256"`
	OutputBytes           int64    `json:"output_bytes"`
	SourcePolicy          string   `json:"source_policy"`
	SourceArchiveSHA256   string   `json:"source_archive_sha256"`
	SourceArchiveBytes    int64    `json:"source_archive_bytes"`
	ChangedMembers        []string `json:"changed_members"`
	FullReextractVerified bool     `json:"full_reextract_verified"`
	Failures              []string `json:"failures"`
}

type compositionBuildReport struct {
	Type                          string                           `json:"type"`
	FormatVersion                 int                              `json:"format_version"`
	Status                        string                           `json:"status"`
	ProjectRoot                   string                           `json:"project_root"`
	GameRoot                      string                           `json:"game_root"`
	TargetID                      string                           `json:"target_id"`
	CommitEnabled                 bool                             `json:"commit_enabled"`
	SelectedModules               []string                         `json:"selected_modules"`
	PreflightStatus               string                           `json:"preflight_status"`
	OutputRoot                    string                           `json:"output_root"`
	EmbeddedReportPath            string                           `json:"embedded_report_path"`
	TranslationLooseReportPath    string                           `json:"translation_loose_report_path"`
	TranslationLooseReportSHA256  string                           `json:"translation_loose_report_sha256"`
	TranslationLooseReportBytes   int64                            `json:"translation_loose_report_bytes"`
	TranslationRepackReportPath   string                           `json:"translation_repack_report_path"`
	TranslationRepackReportSHA256 string                           `json:"translation_repack_report_sha256"`
	TranslationRepackReportBytes  int64                            `json:"translation_repack_report_bytes"`
	ProductionProfileIDs          []string                         `json:"production_profile_ids"`
	RuntimeTestProfileIDs         []string                         `json:"runtime_test_profile_ids"`
	SelectedProfileIDs            []string                         `json:"selected_profile_ids"`
	RestorationProfilePolicy      string                           `json:"restoration_profile_policy"`
	RuntimeTestOnly               bool                             `json:"runtime_test_only"`
	ProfileInputs                 []compositionBuildProfileInput   `json:"profile_inputs"`
	LegacyDLCInputs               []compositionBuildLegacyDLCInput `json:"legacy_dlc_inputs"`
	Archives                      []compositionBuildArchive        `json:"archives"`
	PublishedArchiveCount         int                              `json:"published_archive_count"`
	ComposedArchiveCount          int                              `json:"composed_archive_count"`
	PassthroughArchiveCount       int                              `json:"passthrough_archive_count"`
	FullReextractCount            int                              `json:"full_reextract_count"`
	Errors                        []string                         `json:"errors"`
}

type compositionBuildLegacyDLCInput struct {
	ManifestPath           string   `json:"manifest_path"`
	ManifestSHA256         string   `json:"manifest_sha256"`
	ManifestBytes          int64    `json:"manifest_bytes"`
	FamilyID               string   `json:"family_id"`
	Generation             int      `json:"generation"`
	Members                []string `json:"members"`
	TransactionGroup       string   `json:"transaction_group"`
	WorkstreamVersion      string   `json:"workstream_version"`
	ProvenanceEvidencePath string   `json:"provenance_evidence_path"`
	ProvenanceEvidenceHash string   `json:"provenance_evidence_sha256"`
	ArchiveRelativePath    string   `json:"archive_relative_path"`
	CandidatePath          string   `json:"candidate_path"`
	CandidateSHA256        string   `json:"candidate_sha256"`
	CandidateBytes         int64    `json:"candidate_bytes"`
	BaselinePath           string   `json:"baseline_path"`
	BaselineSHA256         string   `json:"baseline_sha256"`
	BaselineBytes          int64    `json:"baseline_bytes"`
	AddedMembers           []string `json:"added_members"`
	ChangedMembers         []string `json:"changed_members"`
	RemovedMembers         []string `json:"removed_members"`
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
	catalog, err := LoadCatalog()
	if err != nil {
		return Preview{}, err
	}
	mapping := map[string]ModuleTargetSpec{}
	for _, spec := range catalog {
		mapping[spec.TargetID+"\x00"+spec.ModuleID] = spec
	}
	needsTranslationReport := false
	for _, selectedTarget := range selection.Targets {
		for _, moduleID := range selectedTarget.SelectedModuleIDs {
			_, ok := mapping[selectedTarget.TargetID+"\x00"+moduleID]
			if ok && (moduleID == "blue_reflection_translation" || moduleID == "second_light_translation") {
				needsTranslationReport = true
			}
		}
	}
	var report repackReport
	if needsTranslationReport {
		reportPath := filepath.Join(projectRoot, filepath.FromSlash(repackReportRelative))
		report, err = loadRepackReport(reportPath, projectRoot)
		if err != nil {
			return Preview{}, err
		}
	}
	preview := Preview{
		Type: PreviewType, FormatVersion: PreviewFormatVersion, Status: "ready",
		GeneratedUTC: time.Now().UTC(), ProjectRoot: projectRoot,
		RepackReport: filepath.ToSlash(repackReportRelative), CompositionReport: filepath.ToSlash(compositionReportRelative), CommitEnabled: false,
		TransactionPolicy:  "preview verified local artifacts only; no transaction is prepared or committed",
		DistributionPolicy: "single modules use their verified payload contracts; overlapping Quartet module selections require the fully verified content-aware composition set",
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
		compositionPair := selectedTarget.TargetID == quartetTargetID && quartetModulesNeedComposition(selectedSet)
		compositionModules := map[string]ModulePreview{}
		if compositionPair {
			compositionModules, target.Warnings = buildQuartetCompositionModulePreview(projectRoot, selectedTarget.Root, report, selectedTarget.SelectedModuleIDs)
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
			if spec.SourceKind == legacyDLCSourceKind && module.Ready {
				module.Artifacts, module.Ready, module.Reason = inspectLegacyDLCModule(projectRoot, selectedTarget.Root, moduleID)
				for _, artifact := range module.Artifacts {
					if artifact.TransactionReady {
						target.ReadyArtifactCount++
					}
				}
				if !module.Ready {
					target.PendingModuleCount++
					target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, module.Reason))
				}
				target.Modules = append(target.Modules, module)
				continue
			}
			if !module.Ready {
				target.PendingModuleCount++
				target.Warnings = append(target.Warnings, fmt.Sprintf("%s: %s", moduleID, spec.Reason))
			} else {
				for _, artifactSpec := range spec.Artifacts {
					artifact := inspectArtifact(projectRoot, selectedTarget.Root, artifactSpec.BuildTargetID, moduleID, artifactSpec.RelativePath, report)
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

func buildQuartetCompositionModulePreview(projectRoot, gameRoot string, repack repackReport, selectedModules []string) (map[string]ModulePreview, []string) {
	normalized, err := normalizeQuartetCompositionSelection(selectedModules)
	if err != nil {
		message := fmt.Sprintf("Quartet composition selection is invalid: %v", err)
		return pendingCompositionModules(selectedModules, message), []string{message}
	}
	result := pendingCompositionModules(normalized, "A matching verified shared Quartet composition build is required before transaction preview.")
	owner := compositionArtifactOwner(normalized)
	archives, err := loadVerifiedCompositionArtifacts(projectRoot, gameRoot, repack, normalized, owner)
	if err != nil {
		message := fmt.Sprintf("Quartet composition payloads are unavailable: %v", err)
		return pendingCompositionModules(normalized, message), []string{message}
	}
	ready := true
	for _, artifact := range archives {
		if !artifact.TransactionReady {
			ready = false
		}
	}
	for _, moduleID := range normalized {
		module := result[moduleID]
		module.ConnectionStatus = "connected_composition_preview_only"
		module.Ready = ready
		if moduleID == owner {
			module.Reason = "Artifacts come from the verified shared Quartet composition set and are listed once under this module to prevent duplicate transaction paths."
			module.Artifacts = archives
		} else {
			module.Reason = fmt.Sprintf("Included in the shared verified composition set; artifacts are listed once under %s to prevent duplicate transaction paths.", owner)
			module.Artifacts = []ArtifactPreview{}
		}
		result[moduleID] = module
	}
	if !ready {
		return result, []string{"one or more verified composition artifacts could not enter the transaction preview"}
	}
	return result, []string{}
}

func pendingCompositionModules(selectedModules []string, reason string) map[string]ModulePreview {
	result := map[string]ModulePreview{}
	for _, moduleID := range selectedModules {
		if strings.TrimSpace(moduleID) == "" {
			continue
		}
		result[moduleID] = ModulePreview{
			ModuleID: moduleID, SourceKind: "verified_content_aware_composition",
			ConnectionStatus: "composition_build_required", Ready: false,
			Reason: reason, Artifacts: []ArtifactPreview{},
		}
	}
	return result
}

func normalizeQuartetCompositionSelection(selectedModules []string) ([]string, error) {
	allowed := map[string]bool{
		"blue_reflection_translation": true,
		"quartet_restoration":         true,
		"quartet_legacy_dlc":          true,
	}
	seen := map[string]bool{}
	for _, moduleID := range selectedModules {
		moduleID = strings.TrimSpace(moduleID)
		if !allowed[moduleID] {
			return nil, fmt.Errorf("unsupported module %q", moduleID)
		}
		if seen[moduleID] {
			return nil, fmt.Errorf("duplicate module %q", moduleID)
		}
		seen[moduleID] = true
	}
	order := []string{"blue_reflection_translation", "quartet_restoration", "quartet_legacy_dlc"}
	result := []string{}
	for _, moduleID := range order {
		if seen[moduleID] {
			result = append(result, moduleID)
		}
	}
	if len(result) == 1 && seen["quartet_restoration"] {
		return result, nil
	}
	if len(result) < 2 {
		return nil, fmt.Errorf("shared composition requires at least two selected modules unless the selection is isolated Restoration-only")
	}
	if !seen["quartet_restoration"] && !(seen["blue_reflection_translation"] && seen["quartet_legacy_dlc"]) {
		return nil, fmt.Errorf("selected modules do not require shared composition")
	}
	return result, nil
}

func compositionArtifactOwner(selectedModules []string) string {
	for _, candidate := range []string{"blue_reflection_translation", "quartet_restoration", "quartet_legacy_dlc"} {
		for _, moduleID := range selectedModules {
			if moduleID == candidate {
				return candidate
			}
		}
	}
	return "blue_reflection_translation"
}

func sameCompositionSelection(left, right []string) bool {
	a, err := normalizeQuartetCompositionSelection(left)
	if err != nil {
		return false
	}
	b, err := normalizeQuartetCompositionSelection(right)
	if err != nil {
		return false
	}
	return reflect.DeepEqual(a, b)
}

func loadVerifiedCompositionArtifacts(projectRoot, gameRoot string, repack repackReport, selectedModules []string, ownerModuleID string) ([]ArtifactPreview, error) {
	reportPath := filepath.Join(projectRoot, filepath.FromSlash(compositionReportRelative))
	canonicalBytes, err := os.ReadFile(reportPath)
	if err != nil {
		return nil, fmt.Errorf("read composition build report: %w", err)
	}
	var report compositionBuildReport
	if err := json.Unmarshal(canonicalBytes, &report); err != nil {
		return nil, fmt.Errorf("decode composition build report: %w", err)
	}
	if report.Type != compositionReportType || report.FormatVersion != 4 {
		return nil, fmt.Errorf("unsupported composition report type/version")
	}
	if !sameCompositionSelection(report.SelectedModules, selectedModules) {
		return nil, fmt.Errorf("composition report module selection is stale: report=%v current=%v", report.SelectedModules, selectedModules)
	}
	selected := map[string]bool{}
	for _, moduleID := range selectedModules {
		selected[moduleID] = true
	}
	if report.Status != "ok" || report.CommitEnabled {
		return nil, fmt.Errorf("composition report is not a completed preview-only build")
	}
	profilePolicy := strings.TrimSpace(report.RestorationProfilePolicy)
	if profilePolicy == "" {
		profilePolicy = "runtime-validated"
	}
	runtimeTest := report.RuntimeTestOnly
	expectedPreflight := "ready_for_composition_build"
	if runtimeTest {
		expectedPreflight = "ready_for_runtime_test_composition_build"
		if profilePolicy != "all-current-candidates-for-runtime-test" || !reflect.DeepEqual(report.SelectedModules, []string{"quartet_restoration"}) {
			return nil, fmt.Errorf("runtime-test composition must be isolated Restoration-only with the explicit all-current-candidates policy")
		}
	} else if profilePolicy != "runtime-validated" {
		return nil, fmt.Errorf("unsupported production Restoration profile policy: %s", profilePolicy)
	}
	if report.TargetID != quartetTargetID || report.PreflightStatus != expectedPreflight {
		return nil, fmt.Errorf("composition report target/preflight mismatch")
	}
	if len(report.Errors) != 0 {
		return nil, fmt.Errorf("composition report contains errors")
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

	if selected["blue_reflection_translation"] {
		if err := verifyProjectFileFingerprint(projectRoot, report.TranslationLooseReportPath, report.TranslationLooseReportSHA256, report.TranslationLooseReportBytes); err != nil {
			return nil, fmt.Errorf("stale composition translation input: %w", err)
		}
		if err := verifyProjectFileFingerprint(projectRoot, report.TranslationRepackReportPath, report.TranslationRepackReportSHA256, report.TranslationRepackReportBytes); err != nil {
			return nil, fmt.Errorf("stale composition translation input: %w", err)
		}
	} else if report.TranslationLooseReportPath != "" || report.TranslationLooseReportSHA256 != "" || report.TranslationLooseReportBytes != 0 || report.TranslationRepackReportPath != "" || report.TranslationRepackReportSHA256 != "" || report.TranslationRepackReportBytes != 0 {
		return nil, fmt.Errorf("composition report contains Translation inputs although Translation was not selected")
	}

	if selected["quartet_restoration"] {
		selectedProfileIDs := report.SelectedProfileIDs
		if len(selectedProfileIDs) == 0 {
			selectedProfileIDs = report.ProductionProfileIDs
		}
		if len(selectedProfileIDs) == 0 {
			return nil, fmt.Errorf("composition report contains no selected restoration profiles")
		}
		if runtimeTest {
			if len(report.ProductionProfileIDs) != 0 || !sameStringSet(selectedProfileIDs, report.RuntimeTestProfileIDs) {
				return nil, fmt.Errorf("runtime-test composition profile classifications are inconsistent")
			}
		} else if len(report.RuntimeTestProfileIDs) != 0 || !sameStringSet(selectedProfileIDs, report.ProductionProfileIDs) {
			return nil, fmt.Errorf("production composition profile classifications are inconsistent")
		}
		if err := verifyCurrentProfileInputs(projectRoot, report, selectedProfileIDs, runtimeTest); err != nil {
			return nil, fmt.Errorf("stale composition profile inputs: %w", err)
		}
	} else if len(report.ProductionProfileIDs) != 0 || len(report.RuntimeTestProfileIDs) != 0 || len(report.SelectedProfileIDs) != 0 || len(report.ProfileInputs) != 0 || report.RuntimeTestOnly {
		return nil, fmt.Errorf("composition report contains Restoration inputs although Restoration was not selected")
	}

	var legacyContract LegacyDLCCompositionContract
	if selected["quartet_legacy_dlc"] {
		legacyContract, err = LoadLegacyDLCCompositionContract(projectRoot, gameRoot)
		if err != nil {
			return nil, fmt.Errorf("stale composition Legacy DLC inputs: %w", err)
		}
		if err := verifyLegacyDLCCompositionInputs(projectRoot, report.LegacyDLCInputs, legacyContract); err != nil {
			return nil, fmt.Errorf("stale composition Legacy DLC inputs: %w", err)
		}
	} else if len(report.LegacyDLCInputs) != 0 {
		return nil, fmt.Errorf("composition report contains Legacy DLC inputs although Legacy DLC was not selected")
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

	required := map[string]bool{}
	if selected["blue_reflection_translation"] {
		for _, relative := range quartetTranslationArchives() {
			required[strings.ToLower(relative)] = false
		}
	}
	if selected["quartet_legacy_dlc"] {
		for _, item := range legacyContract.Artifacts {
			required[strings.ToLower(filepath.ToSlash(item.RelativePath))] = false
		}
	}
	if selected["quartet_restoration"] {
		for _, input := range report.ProfileInputs {
			required[strings.ToLower(filepath.ToSlash(input.TargetRelativePath))] = false
		}
	}

	legacyByArchive := map[string]LegacyDLCCompositionArtifact{}
	for _, item := range legacyContract.Artifacts {
		legacyByArchive[strings.ToLower(filepath.ToSlash(item.RelativePath))] = item
	}
	profilesByArchive := map[string][]compositionBuildProfileInput{}
	for _, input := range report.ProfileInputs {
		key := strings.ToLower(filepath.ToSlash(input.TargetRelativePath))
		profilesByArchive[key] = append(profilesByArchive[key], input)
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
		if _, ok := required[key]; !ok {
			return nil, fmt.Errorf("composition set contains undeclared archive: %s", relative)
		}
		required[key] = true
		expectedOutput := filepath.ToSlash(filepath.Join(compositionOutputRelative, filepath.FromSlash(relative)))
		actualOutput := filepath.ToSlash(filepath.Clean(filepath.FromSlash(archive.OutputPath)))
		if actualOutput != expectedOutput {
			return nil, fmt.Errorf("composition archive output path mismatch for %s", relative)
		}

		switch archive.BaseSourceKind {
		case "verified_translation_archive":
			if !selected["blue_reflection_translation"] {
				return nil, fmt.Errorf("Translation base used while Translation is not selected: %s", relative)
			}
			entry, ok := findReportEntry(repack, quartetTranslationBuildTarget(relative), relative)
			if !ok || len(entry.Failures) != 0 || entry.OutputSHA256 != archive.BaseSHA256 || entry.OutputBytes != archive.BaseBytes {
				return nil, fmt.Errorf("composition translation base is stale for %s", relative)
			}
			if err := verifyProjectFileFingerprint(projectRoot, entry.OutputPath, entry.OutputSHA256, entry.OutputBytes); err != nil {
				return nil, fmt.Errorf("composition translation base is stale for %s: %w", relative, err)
			}
		case "verified_legacy_dlc_candidate":
			item, ok := legacyByArchive[key]
			if !ok || archive.BaseSHA256 != item.CandidateSHA256 || archive.BaseBytes != item.CandidateSize {
				return nil, fmt.Errorf("composition Legacy DLC base is stale for %s", relative)
			}
		case "verified_runtime_validated_restoration_profile":
			inputs := profilesByArchive[key]
			if !selected["quartet_restoration"] || len(inputs) != 1 || !inputs[0].RuntimeValidated || len(archive.ProfileIDs) != 1 || archive.ProfileIDs[0] != inputs[0].ProfileID || archive.BaseSHA256 != inputs[0].PayloadSHA256 || archive.BaseBytes != inputs[0].PayloadBytes {
				return nil, fmt.Errorf("composition Restoration profile passthrough is stale for %s", relative)
			}
		case "installed_game_baseline", "installed_baseline_archive":
			if archive.BaseSHA256 == "" || archive.BaseBytes <= 0 {
				return nil, fmt.Errorf("composition installed baseline metadata is missing for %s", relative)
			}
			target, exists, err := resolveTargetPath(gameRoot, relative)
			if err != nil || !exists {
				return nil, fmt.Errorf("composition installed baseline disappeared for %s", relative)
			}
			hash, err := hashFile(target)
			if err != nil {
				return nil, err
			}
			info, err := os.Lstat(target)
			if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() || hash != archive.BaseSHA256 || info.Size() != archive.BaseBytes {
				return nil, fmt.Errorf("composition installed baseline is stale for %s", relative)
			}
		default:
			return nil, fmt.Errorf("unsupported composition base source %q for %s", archive.BaseSourceKind, relative)
		}

		switch archive.Mode {
		case "verified_translation_passthrough":
			if archive.Status != "published_verified_translation_passthrough" || !archive.ManifestDeclarationChecked || archive.FullReextractVerified {
				return nil, fmt.Errorf("unverified translation passthrough archive: %s", relative)
			}
		case "verified_legacy_dlc_passthrough":
			if archive.Status != "published_verified_legacy_dlc_passthrough" || !archive.ManifestDeclarationChecked || archive.FullReextractVerified {
				return nil, fmt.Errorf("unverified Legacy DLC passthrough archive: %s", relative)
			}
		case "verified_restoration_profile_passthrough":
			if archive.Status != "published_verified_restoration_profile_passthrough" || !archive.ManifestDeclarationChecked || archive.FullReextractVerified || len(archive.ProfileIDs) != 1 {
				return nil, fmt.Errorf("unverified Restoration profile passthrough archive: %s", relative)
			}
		case "member_overlay":
			if archive.Status != "published_member_overlay_verified" || !archive.ManifestDeclarationChecked || !archive.FullReextractVerified {
				return nil, fmt.Errorf("unverified member-overlay archive: %s", relative)
			}
		default:
			return nil, fmt.Errorf("unsupported composition archive mode %q for %s", archive.Mode, relative)
		}
		artifact := inspectCompositionArtifact(projectRoot, gameRoot, relative, archive, ownerModuleID)
		artifacts = append(artifacts, artifact)
	}
	for relative, present := range required {
		if !present {
			return nil, fmt.Errorf("composition set is missing required archive: %s", relative)
		}
	}
	sort.Slice(artifacts, func(i, j int) bool { return artifacts[i].RelativePath < artifacts[j].RelativePath })
	return artifacts, nil
}

func quartetTranslationArchives() []string {
	return []string{
		"Data/PACK11.PAK", "Data/PACK12.PAK",
		"Data/PACK01_01.PAK", "Data/PACK02_01.PAK",
		"Data/PACK01_02.PAK", "Data/PACK02_02.PAK",
		"Data/PACK01_03.PAK", "Data/PACK02_03.PAK",
		"Data/PACK00_04_01.PAK",
	}
}

func verifyLegacyDLCCompositionInputs(projectRoot string, inputs []compositionBuildLegacyDLCInput, contract LegacyDLCCompositionContract) error {
	if len(inputs) != len(contract.Artifacts) {
		return fmt.Errorf("Legacy DLC input count mismatch")
	}
	expected := map[string]LegacyDLCCompositionArtifact{}
	for _, item := range contract.Artifacts {
		expected[strings.ToLower(filepath.ToSlash(item.RelativePath))] = item
	}
	seen := map[string]bool{}
	for _, input := range inputs {
		key := strings.ToLower(filepath.ToSlash(input.ArchiveRelativePath))
		item, ok := expected[key]
		if !ok || seen[key] {
			return fmt.Errorf("unexpected or duplicate Legacy DLC input: %s", input.ArchiveRelativePath)
		}
		seen[key] = true
		manifestPath, err := resolveCompositionInputPath(projectRoot, input.ManifestPath)
		if err != nil {
			return err
		}
		evidencePath, err := resolveCompositionInputPath(projectRoot, input.ProvenanceEvidencePath)
		if err != nil {
			return err
		}
		candidatePath, err := resolveCompositionInputPath(projectRoot, input.CandidatePath)
		if err != nil {
			return err
		}
		baselinePath, err := resolveCompositionInputPath(projectRoot, input.BaselinePath)
		if err != nil {
			return err
		}
		if !sameFilesystemPath(manifestPath, contract.ManifestPath) || !strings.EqualFold(input.ManifestSHA256, contract.ManifestSHA256) || input.ManifestBytes != contract.ManifestBytes ||
			input.FamilyID != contract.FamilyID || input.Generation != contract.Generation || !reflect.DeepEqual(input.Members, contract.Members) || input.TransactionGroup != contract.TransactionGroup ||
			input.WorkstreamVersion != contract.WorkstreamVersion || !sameFilesystemPath(evidencePath, contract.ProvenanceEvidencePath) || !strings.EqualFold(input.ProvenanceEvidenceHash, contract.ProvenanceEvidenceHash) ||
			!sameFilesystemPath(candidatePath, item.CandidatePath) || !sameFilesystemPath(baselinePath, item.BaselinePath) ||
			!strings.EqualFold(input.CandidateSHA256, item.CandidateSHA256) || input.CandidateBytes != item.CandidateSize ||
			!strings.EqualFold(input.BaselineSHA256, item.BaselineSHA256) || input.BaselineBytes != item.BaselineSize ||
			!sameFoldedStringSet(input.AddedMembers, item.AddedMembers) || !sameFoldedStringSet(input.ChangedMembers, item.ChangedMembers) || !sameFoldedStringSet(input.RemovedMembers, item.RemovedMembers) {
			return fmt.Errorf("Legacy DLC input no longer matches the validated manifest: %s", input.ArchiveRelativePath)
		}
	}
	return nil
}

func resolveCompositionInputPath(projectRoot, value string) (string, error) {
	if strings.TrimSpace(value) == "" {
		return "", fmt.Errorf("empty composition input path")
	}
	if filepath.IsAbs(value) {
		return filepath.Clean(value), nil
	}
	return secureProjectPath(projectRoot, value)
}

func sameFoldedStringSet(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	normalize := func(values []string) []string {
		result := make([]string, len(values))
		for index, value := range values {
			result[index] = strings.ToLower(filepath.ToSlash(filepath.Clean(filepath.FromSlash(value))))
		}
		sort.Strings(result)
		return result
	}
	return reflect.DeepEqual(normalize(left), normalize(right))
}

func quartetTranslationBuildTarget(relative string) string {
	switch strings.ToLower(filepath.ToSlash(filepath.Clean(filepath.FromSlash(relative)))) {
	case strings.ToLower("Data/PACK01_01.PAK"), strings.ToLower("Data/PACK02_01.PAK"):
		return "blue_reflection_ray_quartet"
	case strings.ToLower("Data/PACK01_02.PAK"), strings.ToLower("Data/PACK02_02.PAK"):
		return "blue_reflection_sun_quartet"
	case strings.ToLower("Data/PACK01_03.PAK"), strings.ToLower("Data/PACK02_03.PAK"):
		return "second_light_quartet"
	default:
		return quartetTargetID
	}
}

func inspectCompositionArtifact(projectRoot, gameRoot, relative string, archive compositionBuildArchive, ownerModuleID string) ArtifactPreview {
	result := ArtifactPreview{
		ModuleID: ownerModuleID, RelativePath: filepath.ToSlash(relative),
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

func sameStringSet(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	a := append([]string{}, left...)
	b := append([]string{}, right...)
	sort.Strings(a)
	sort.Strings(b)
	return reflect.DeepEqual(a, b)
}

func verifyCurrentProfileInputs(projectRoot string, report compositionBuildReport, selectedProfileIDs []string, runtimeTest bool) error {
	if len(report.ProfileInputs) != len(selectedProfileIDs) {
		return fmt.Errorf("profile input count does not match selected profile count")
	}
	expected := map[string]bool{}
	for _, id := range selectedProfileIDs {
		if strings.TrimSpace(id) == "" || expected[id] {
			return fmt.Errorf("invalid or duplicate selected profile id: %q", id)
		}
		expected[id] = true
	}
	for _, input := range report.ProfileInputs {
		if !expected[input.ProfileID] {
			return fmt.Errorf("unexpected profile input: %s", input.ProfileID)
		}
		if !runtimeTest && !input.RuntimeValidated {
			return fmt.Errorf("non-runtime profile entered production composition: %s", input.ProfileID)
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
		if manifest.SchemaVersion != 1 || manifest.WorkstreamID != "quartet_restoration" || manifest.ProfileID != input.ProfileID || manifest.TargetRelativePath != input.TargetRelativePath || manifest.BaselineSHA256 != input.BaselineSHA256 || manifest.BaselineSize != input.BaselineBytes || manifest.ProfileSHA256 != input.PayloadSHA256 || manifest.ProfileSize != input.PayloadBytes || manifest.RuntimeValidated != input.RuntimeValidated {
			return fmt.Errorf("profile %s manifest no longer matches the composition input", input.ProfileID)
		}
		if !runtimeTest && !manifest.RuntimeValidated {
			return fmt.Errorf("profile %s lost runtime validation after composition build", input.ProfileID)
		}
	}

	manifestRoot, err := secureProjectPath(projectRoot, ".local/build/quartet_restoration/core_profiles")
	if err != nil {
		return err
	}
	current := map[string]bool{}
	err = filepath.WalkDir(manifestRoot, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == manifestRoot {
			return nil
		}
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("symlink is not allowed in restoration profile registry: %s", path)
		}
		if entry.IsDir() {
			return nil
		}
		if !strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			return nil
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("invalid profile manifest entry: %s", path)
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var manifest currentProfileManifest
		if err := json.Unmarshal(data, &manifest); err != nil {
			return fmt.Errorf("decode current profile manifest %s: %w", path, err)
		}
		if manifest.SchemaVersion != 1 || manifest.WorkstreamID != "quartet_restoration" || strings.TrimSpace(manifest.ProfileID) == "" {
			return fmt.Errorf("invalid current profile manifest: %s", path)
		}
		if current[manifest.ProfileID] {
			return fmt.Errorf("duplicate current profile id: %s", manifest.ProfileID)
		}
		if runtimeTest || manifest.RuntimeValidated {
			current[manifest.ProfileID] = true
		}
		return nil
	})
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(current, expected) {
		if runtimeTest {
			return fmt.Errorf("current all-candidate profile set changed after runtime-test composition build")
		}
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

func loadRepackReport(path, projectRoot string) (repackReport, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return repackReport{}, fmt.Errorf("read translation repack report: %w", err)
	}
	var report repackReport
	if err := json.Unmarshal(data, &report); err != nil {
		return repackReport{}, fmt.Errorf("decode translation repack report: %w", err)
	}
	if report.Type != translationRepackReportType || report.FormatVersion != 2 {
		return repackReport{}, fmt.Errorf("unsupported translation repack report type/version")
	}
	if report.Status != "ok" {
		return repackReport{}, fmt.Errorf("translation repack report status is %q, expected ok", report.Status)
	}
	currentTranslation, err := readTrimmedProjectFile(projectRoot, "workstreams/translation/VERSION")
	if err != nil {
		return repackReport{}, err
	}
	currentTooling, err := readTrimmedProjectFile(projectRoot, "workstreams/translation_tooling/VERSION")
	if err != nil {
		return repackReport{}, err
	}
	if report.TranslationVersion != currentTranslation || report.TranslationToolingVersion != currentTooling {
		return repackReport{}, fmt.Errorf(
			"translation build is stale: report=%s/%s current=%s/%s",
			report.TranslationVersion, report.TranslationToolingVersion, currentTranslation, currentTooling,
		)
	}
	if versionLess(report.TranslationVersion, minimumTranslationVersion) || versionLess(report.TranslationVersion, report.MinimumTranslationVersion) {
		return repackReport{}, fmt.Errorf("translation build predates corrected Quartet routing: %s", report.TranslationVersion)
	}
	if strings.TrimSpace(report.CanonicalInputFingerprint) == "" {
		return repackReport{}, fmt.Errorf("translation repack report has no canonical input fingerprint")
	}
	if err := verifyProjectFileFingerprint(projectRoot, report.LooseReportPath, report.LooseReportSHA256, report.LooseReportBytes); err != nil {
		return repackReport{}, fmt.Errorf("loose build report: %w", err)
	}
	return report, nil
}

func readTrimmedProjectFile(projectRoot, relative string) (string, error) {
	path, err := secureProjectPath(projectRoot, relative)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	value := strings.TrimSpace(string(data))
	if value == "" {
		return "", fmt.Errorf("empty project file: %s", relative)
	}
	return value, nil
}

func versionLess(left, right string) bool {
	var a, b [3]int
	if _, err := fmt.Sscanf(strings.TrimSpace(left), "%d.%d.%d", &a[0], &a[1], &a[2]); err != nil {
		return true
	}
	if _, err := fmt.Sscanf(strings.TrimSpace(right), "%d.%d.%d", &b[0], &b[1], &b[2]); err != nil {
		return true
	}
	for i := range a {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return false
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
	sourcePolicyOK := entry.SourcePolicy == "current_installation_baseline_extraction" ||
		entry.SourcePolicy == "current_installation_baseline_extraction_plus_verified_marker_overlay"
	if !sourcePolicyOK || entry.SourceArchiveBytes < 0 || len(entry.SourceArchiveSHA256) != 64 {
		result.Error = "archive was not structurally rebased from a fingerprinted current installation baseline"
		return result
	}
	if !entry.FullReextractVerified {
		result.Error = "archive did not pass full re-extraction verification"
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
