package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	quartetCompositionPreviewType    = "br_quartet_translation_restoration_composition_preflight"
	quartetCompositionPreviewVersion = 3
	quartetTargetID                  = "blue_reflection_quartet"
	translationLooseReportRelative   = ".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json"
	translationRepackReportRelative  = ".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json"
)

var quartetTranslationArchives = []struct {
	TargetID string
	Path     string
}{
	{"blue_reflection_quartet", "Data/PACK11.PAK"},
	{"blue_reflection_quartet", "Data/PACK12.PAK"},
	{"blue_reflection_ray_quartet", "Data/PACK01_01.PAK"},
	{"blue_reflection_ray_quartet", "Data/PACK02_01.PAK"},
	{"blue_reflection_sun_quartet", "Data/PACK01_02.PAK"},
	{"blue_reflection_sun_quartet", "Data/PACK02_02.PAK"},
	{"second_light_quartet", "Data/PACK01_03.PAK"},
	{"second_light_quartet", "Data/PACK02_03.PAK"},
	{"blue_reflection_quartet", "Data/PACK00_04_01.PAK"},
}

type compositionLooseFile struct {
	ArchiveRelativePath string `json:"archive_relative_path"`
	InternalPath        string `json:"internal_path"`
	Changed             bool   `json:"changed"`
}

type compositionLooseTarget struct {
	Files []compositionLooseFile `json:"files"`
}

type compositionLooseReport struct {
	Type                      string                            `json:"type"`
	FormatVersion             int                               `json:"format_version"`
	Status                    string                            `json:"status"`
	TranslationVersion        string                            `json:"translation_version"`
	TranslationToolingVersion string                            `json:"translation_tooling_version"`
	CanonicalInputFingerprint string                            `json:"canonical_input_fingerprint"`
	Targets                   map[string]compositionLooseTarget `json:"targets"`
}

type compositionRepackArchive struct {
	TargetID            string   `json:"target_id"`
	ArchiveRelativePath string   `json:"archive_relative_path"`
	OutputPath          string   `json:"output_path"`
	OutputSHA256        string   `json:"output_sha256"`
	OutputBytes         int64    `json:"output_bytes"`
	Failures            []string `json:"failures"`
}

type compositionRepackReport struct {
	Type                      string                     `json:"type"`
	FormatVersion             int                        `json:"format_version"`
	Status                    string                     `json:"status"`
	TranslationVersion        string                     `json:"translation_version"`
	TranslationToolingVersion string                     `json:"translation_tooling_version"`
	CanonicalInputFingerprint string                     `json:"canonical_input_fingerprint"`
	Archives                  []compositionRepackArchive `json:"archives"`
}

type compositionTranslationBase struct {
	ArchiveRelativePath string   `json:"archive_relative_path"`
	SourcePath          string   `json:"source_path"`
	SHA256              string   `json:"sha256"`
	Bytes               int64    `json:"bytes"`
	ChangedMemberCount  int      `json:"changed_member_count"`
	ChangedMembers      []string `json:"changed_members"`
	Verified            bool     `json:"verified"`
	Error               string   `json:"error,omitempty"`
}

type compositionProfilePreview struct {
	ProfileID               string   `json:"profile_id"`
	TargetRelativePath      string   `json:"target_relative_path"`
	ManifestPath            string   `json:"manifest_path"`
	SourcePath              string   `json:"source_path"`
	WorkstreamVersion       string   `json:"workstream_version"`
	RuntimeValidated        bool     `json:"runtime_validated"`
	ChangedMemberCount      int      `json:"changed_member_count"`
	ChangedMembers          []string `json:"changed_members"`
	TranslationConflicts    []string `json:"translation_conflicts"`
	RuntimeProfileConflicts []string `json:"runtime_profile_conflicts"`
	Status                  string   `json:"status"`
	ProductionEligible      bool     `json:"production_eligible"`
}

type compositionArchivePreview struct {
	ArchiveRelativePath    string   `json:"archive_relative_path"`
	BaseSourceKind         string   `json:"base_source_kind"`
	BaseSourcePath         string   `json:"base_source_path"`
	BaselineSHA256         string   `json:"baseline_sha256,omitempty"`
	BaselineBytes          int64    `json:"baseline_bytes,omitempty"`
	InstalledSHA256        string   `json:"installed_sha256,omitempty"`
	InstalledBytes         int64    `json:"installed_bytes,omitempty"`
	InstalledBaselineMatch bool     `json:"installed_baseline_match"`
	EligibleProfileIDs     []string `json:"eligible_profile_ids"`
	OverlayMemberCount     int      `json:"overlay_member_count"`
	OutputPath             string   `json:"output_path"`
	Status                 string   `json:"status"`
	Warnings               []string `json:"warnings"`
}

type compositionLegacyDLCInput struct {
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
	Verified               bool     `json:"verified"`
	Error                  string   `json:"error,omitempty"`
}

type quartetCompositionPreview struct {
	Type                         string                       `json:"type"`
	FormatVersion                int                          `json:"format_version"`
	Status                       string                       `json:"status"`
	GeneratedUTC                 time.Time                    `json:"generated_utc"`
	ProjectRoot                  string                       `json:"project_root"`
	GameRoot                     string                       `json:"game_root"`
	TargetID                     string                       `json:"target_id"`
	CommitEnabled                bool                         `json:"commit_enabled"`
	CompositionPolicy            string                       `json:"composition_policy"`
	SelectedModules              []string                     `json:"selected_modules"`
	TranslationLooseReport       string                       `json:"translation_loose_report"`
	TranslationRepackReport      string                       `json:"translation_repack_report"`
	ProfileManifestRoot          string                       `json:"profile_manifest_root"`
	ValidProfileCount            int                          `json:"valid_profile_count"`
	RegistryIssueCount           int                          `json:"registry_issue_count"`
	RuntimeValidatedProfileCount int                          `json:"runtime_validated_profile_count"`
	ProductionEligibleCount      int                          `json:"production_eligible_count"`
	TranslationBases             []compositionTranslationBase `json:"translation_bases"`
	LegacyDLCInputs              []compositionLegacyDLCInput  `json:"legacy_dlc_inputs"`
	Profiles                     []compositionProfilePreview  `json:"profiles"`
	Archives                     []compositionArchivePreview  `json:"archives"`
	RegistryIssues               []localProfileIssue          `json:"registry_issues"`
	Warnings                     []string                     `json:"warnings"`
}

func commandQuartetCompositionPreview(args []string) error {
	flags := flag.NewFlagSet("quartet-composition-preview", flag.ContinueOnError)
	var roots rootsFlag
	var output, projectRoot, moduleList string
	flags.Var(&roots, "game-dir", "BLUE REFLECTION Quartet game directory")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified translation and restoration builds")
	flags.StringVar(&output, "json", "", "write composition preflight JSON to this file")
	flags.StringVar(&moduleList, "modules", "blue_reflection_translation,quartet_restoration", "comma-separated Quartet modules to compose")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	items, err := detectWithFallback(specs, roots, false, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	var quartet []model.Detection
	for _, item := range items {
		if item.TargetID == quartetTargetID {
			quartet = append(quartet, item)
		}
	}
	if len(quartet) != 1 {
		return fmt.Errorf("expected exactly one detected BLUE REFLECTION Quartet installation, found %d", len(quartet))
	}
	modules, err := normalizeQuartetCompositionModules([]string{moduleList})
	if err != nil {
		return err
	}
	preview, err := buildQuartetModuleCompositionPreview(projectRoot, quartet[0].Root, modules)
	if err != nil {
		return err
	}
	printHumanQuartetCompositionPreview(os.Stdout, preview)
	if output != "" {
		if err := emit(preview, output); err != nil {
			return err
		}
		fmt.Printf("Composition preflight report: %s\n", output)
	}
	return nil
}

func buildQuartetCompositionPreview(rawProjectRoot, gameRoot string) (quartetCompositionPreview, error) {
	projectRoot, err := payloadpreview.ResolveProjectRoot(rawProjectRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	projectRoot, err = filepath.Abs(projectRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	gameRoot, err = filepath.Abs(gameRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	loose, err := loadCompositionLooseReport(filepath.Join(projectRoot, filepath.FromSlash(translationLooseReportRelative)), projectRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	repack, err := loadCompositionRepackReport(filepath.Join(projectRoot, filepath.FromSlash(translationRepackReportRelative)), projectRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	registry, err := discoverLocalProfiles(projectRoot)
	if err != nil {
		return quartetCompositionPreview{}, err
	}

	translationMembers := changedTranslationMembers(loose)
	translationBases := verifyQuartetTranslationBases(projectRoot, repack, translationMembers)
	translationBaseByArchive := map[string]compositionTranslationBase{}
	for _, base := range translationBases {
		translationBaseByArchive[foldCompositionPath(base.ArchiveRelativePath)] = base
	}

	profiles := make([]compositionProfilePreview, 0, len(registry.Profiles))
	profileIDs := make([]string, 0, len(registry.Profiles))
	for id := range registry.Profiles {
		profileIDs = append(profileIDs, id)
	}
	sort.Strings(profileIDs)

	runtimeOwners := map[string][]string{}
	for _, id := range profileIDs {
		item := registry.Profiles[id]
		if !item.Manifest.RuntimeValidated {
			continue
		}
		for _, member := range item.Manifest.ChangedMembers {
			key := foldCompositionPath(item.Manifest.TargetRelativePath) + "\x00" + foldCompositionPath(member)
			runtimeOwners[key] = append(runtimeOwners[key], id)
		}
	}
	for key := range runtimeOwners {
		sort.Strings(runtimeOwners[key])
	}

	for _, id := range profileIDs {
		item := registry.Profiles[id]
		manifest := item.Manifest
		profile := compositionProfilePreview{
			ProfileID: id, TargetRelativePath: manifest.TargetRelativePath,
			ManifestPath: item.ManifestPath, SourcePath: relativeDisplayPath(projectRoot, item.SourcePath),
			WorkstreamVersion: manifest.WorkstreamVersion, RuntimeValidated: manifest.RuntimeValidated,
			ChangedMemberCount:   manifest.ChangedMemberCount,
			ChangedMembers:       append([]string{}, manifest.ChangedMembers...),
			TranslationConflicts: []string{}, RuntimeProfileConflicts: []string{},
		}
		translationSet := translationMembers[foldCompositionPath(manifest.TargetRelativePath)]
		for _, member := range manifest.ChangedMembers {
			foldedMember := foldCompositionPath(member)
			if translationSet[foldedMember] {
				profile.TranslationConflicts = append(profile.TranslationConflicts, member)
			}
			key := foldCompositionPath(manifest.TargetRelativePath) + "\x00" + foldedMember
			owners := runtimeOwners[key]
			if manifest.RuntimeValidated && len(owners) > 1 {
				for _, owner := range owners {
					if owner != id {
						profile.RuntimeProfileConflicts = append(profile.RuntimeProfileConflicts, owner+":"+member)
					}
				}
			}
		}
		sort.Strings(profile.TranslationConflicts)
		sort.Strings(profile.RuntimeProfileConflicts)
		switch {
		case len(profile.TranslationConflicts) > 0:
			profile.Status = "blocked_translation_member_conflict"
		case len(profile.RuntimeProfileConflicts) > 0:
			profile.Status = "blocked_runtime_profile_conflict"
		case !profile.RuntimeValidated:
			profile.Status = "candidate_awaiting_runtime_validation"
		default:
			profile.Status = "eligible_runtime_validated"
			profile.ProductionEligible = true
		}
		profiles = append(profiles, profile)
	}

	preview := quartetCompositionPreview{
		Type: quartetCompositionPreviewType, FormatVersion: quartetCompositionPreviewVersion,
		GeneratedUTC: time.Now().UTC(), ProjectRoot: projectRoot, GameRoot: gameRoot,
		TargetID: quartetTargetID, CommitEnabled: false,
		CompositionPolicy:       "start from the verified translation archive when present, overlay only manifest-declared restoration members, reject exact member conflicts, re-extract and verify before any future transaction",
		TranslationLooseReport:  filepath.ToSlash(translationLooseReportRelative),
		TranslationRepackReport: filepath.ToSlash(translationRepackReportRelative),
		ProfileManifestRoot:     filepath.ToSlash(localProfileManifestRoot),
		ValidProfileCount:       len(profiles), RegistryIssueCount: len(registry.Issues),
		TranslationBases: translationBases, Profiles: profiles,
		RegistryIssues: append([]localProfileIssue{}, registry.Issues...), Warnings: []string{},
	}
	runtimeBlocked := false
	for _, profile := range profiles {
		if profile.RuntimeValidated {
			preview.RuntimeValidatedProfileCount++
			if !profile.ProductionEligible {
				runtimeBlocked = true
			}
		}
		if profile.ProductionEligible {
			preview.ProductionEligibleCount++
		}
	}
	preview.Archives = buildCompositionArchivePreviews(projectRoot, gameRoot, profiles, registry, translationBaseByArchive)

	translationReady := true
	for _, base := range translationBases {
		if !base.Verified {
			translationReady = false
		}
	}
	archiveBlocked := false
	for _, archive := range preview.Archives {
		if strings.HasPrefix(archive.Status, "blocked") {
			archiveBlocked = true
		}
		preview.Warnings = append(preview.Warnings, archive.Warnings...)
	}
	switch {
	case !translationReady:
		preview.Status = "blocked_translation_build_unavailable"
	case runtimeBlocked:
		preview.Status = "blocked_member_conflict"
	case archiveBlocked:
		preview.Status = "blocked_archive_precondition"
	case preview.ProductionEligibleCount > 0:
		preview.Status = "ready_for_composition_build"
	case preview.ValidProfileCount > 0:
		preview.Status = "awaiting_runtime_validated_profiles"
	default:
		preview.Status = "no_restoration_profiles_registered"
	}
	if len(registry.Issues) > 0 {
		preview.Warnings = append(preview.Warnings, fmt.Sprintf("%d invalid restoration profile manifest(s) were isolated and excluded", len(registry.Issues)))
	}
	return preview, nil
}

func loadCompositionLooseReport(path, projectRoot string) (compositionLooseReport, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return compositionLooseReport{}, fmt.Errorf("read translation loose build report: %w", err)
	}
	var report compositionLooseReport
	if err := json.Unmarshal(data, &report); err != nil {
		return compositionLooseReport{}, fmt.Errorf("decode translation loose build report: %w", err)
	}
	if report.Type != "br_translation_loose_build_report" || report.FormatVersion != 2 {
		return compositionLooseReport{}, fmt.Errorf("unsupported translation loose build report type/version")
	}
	if report.Status != "ok" {
		return compositionLooseReport{}, fmt.Errorf("translation loose build report status is %q, expected ok", report.Status)
	}
	if err := validateCompositionTranslationVersions(projectRoot, report.TranslationVersion, report.TranslationToolingVersion); err != nil {
		return compositionLooseReport{}, err
	}
	if strings.TrimSpace(report.CanonicalInputFingerprint) == "" {
		return compositionLooseReport{}, fmt.Errorf("translation loose build report has no canonical input fingerprint")
	}
	for _, targetID := range []string{"blue_reflection_quartet", "blue_reflection_ray_quartet", "blue_reflection_sun_quartet", "second_light_quartet"} {
		if _, ok := report.Targets[targetID]; !ok {
			return compositionLooseReport{}, fmt.Errorf("translation loose build report has no %s target", targetID)
		}
	}
	return report, nil
}

func loadCompositionRepackReport(path, projectRoot string) (compositionRepackReport, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return compositionRepackReport{}, fmt.Errorf("read translation repack report: %w", err)
	}
	var report compositionRepackReport
	if err := json.Unmarshal(data, &report); err != nil {
		return compositionRepackReport{}, fmt.Errorf("decode translation repack report: %w", err)
	}
	if report.Type != "br_translation_pak_repack_report" || report.FormatVersion != 2 {
		return compositionRepackReport{}, fmt.Errorf("unsupported translation repack report type/version")
	}
	if report.Status != "ok" {
		return compositionRepackReport{}, fmt.Errorf("translation repack report status is %q, expected ok", report.Status)
	}
	if err := validateCompositionTranslationVersions(projectRoot, report.TranslationVersion, report.TranslationToolingVersion); err != nil {
		return compositionRepackReport{}, err
	}
	if strings.TrimSpace(report.CanonicalInputFingerprint) == "" {
		return compositionRepackReport{}, fmt.Errorf("translation repack report has no canonical input fingerprint")
	}
	return report, nil
}

func validateCompositionTranslationVersions(projectRoot, translationVersion, toolingVersion string) error {
	read := func(relative string) (string, error) {
		path, err := secureJoin(projectRoot, relative)
		if err != nil {
			return "", err
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return "", err
		}
		return strings.TrimSpace(string(data)), nil
	}
	currentTranslation, err := read("workstreams/translation/VERSION")
	if err != nil {
		return err
	}
	currentTooling, err := read("workstreams/translation_tooling/VERSION")
	if err != nil {
		return err
	}
	if translationVersion != currentTranslation || toolingVersion != currentTooling {
		return fmt.Errorf("translation report is stale: report=%s/%s current=%s/%s", translationVersion, toolingVersion, currentTranslation, currentTooling)
	}
	var major, minor, patch int
	if _, err := fmt.Sscanf(translationVersion, "%d.%d.%d", &major, &minor, &patch); err != nil || major != 0 || minor != 0 || patch < 113 {
		return fmt.Errorf("translation report predates corrected Quartet routing: %s", translationVersion)
	}
	return nil
}

func changedTranslationMembers(report compositionLooseReport) map[string]map[string]bool {
	result := map[string]map[string]bool{}
	for _, targetID := range []string{"blue_reflection_quartet", "blue_reflection_ray_quartet", "blue_reflection_sun_quartet", "second_light_quartet"} {
		for _, file := range report.Targets[targetID].Files {
			if !file.Changed || strings.TrimSpace(file.ArchiveRelativePath) == "" || strings.TrimSpace(file.InternalPath) == "" {
				continue
			}
			archive := foldCompositionPath(file.ArchiveRelativePath)
			if result[archive] == nil {
				result[archive] = map[string]bool{}
			}
			result[archive][foldCompositionPath(file.InternalPath)] = true
		}
	}
	return result
}

func verifyQuartetTranslationBases(projectRoot string, report compositionRepackReport, members map[string]map[string]bool) []compositionTranslationBase {
	result := make([]compositionTranslationBase, 0, len(quartetTranslationArchives))
	for _, wanted := range quartetTranslationArchives {
		relative := wanted.Path
		base := compositionTranslationBase{ArchiveRelativePath: relative, ChangedMembers: []string{}}
		for member := range members[foldCompositionPath(relative)] {
			base.ChangedMembers = append(base.ChangedMembers, member)
		}
		sort.Strings(base.ChangedMembers)
		base.ChangedMemberCount = len(base.ChangedMembers)
		var entry *compositionRepackArchive
		for index := range report.Archives {
			candidate := &report.Archives[index]
			if candidate.TargetID == wanted.TargetID && foldCompositionPath(candidate.ArchiveRelativePath) == foldCompositionPath(relative) {
				entry = candidate
				break
			}
		}
		if entry == nil {
			base.Error = "archive is absent from the verified translation repack report"
			result = append(result, base)
			continue
		}
		if len(entry.Failures) > 0 {
			base.Error = "archive verification report contains failures"
			result = append(result, base)
			continue
		}
		path, err := secureJoin(projectRoot, entry.OutputPath)
		if err != nil {
			base.Error = err.Error()
			result = append(result, base)
			continue
		}
		base.SourcePath = relativeDisplayPath(projectRoot, path)
		actualHash, actualSize, err := checkedFile(path)
		if err != nil {
			base.Error = err.Error()
			result = append(result, base)
			continue
		}
		base.SHA256, base.Bytes = actualHash, actualSize
		if actualHash != entry.OutputSHA256 || actualSize != entry.OutputBytes {
			base.Error = "local translation archive does not match the verified repack report"
			result = append(result, base)
			continue
		}
		base.Verified = true
		result = append(result, base)
	}
	return result
}

func buildCompositionArchivePreviews(projectRoot, gameRoot string, profiles []compositionProfilePreview, registry localProfileRegistry, translationBases map[string]compositionTranslationBase) []compositionArchivePreview {
	targets := []string{
		"Data/PACK11.PAK", "Data/PACK12.PAK",
		"Data/PACK01_01.PAK", "Data/PACK02_01.PAK",
		"Data/PACK01_02.PAK", "Data/PACK02_02.PAK",
		"Data/PACK01_03.PAK", "Data/PACK02_03.PAK",
		"Data/PACK00_04_01.PAK", "Data/PACK10_01.PAK", "Data/PACK10_03.PAK",
	}
	result := make([]compositionArchivePreview, 0, len(targets))
	for _, target := range targets {
		archive := compositionArchivePreview{
			ArchiveRelativePath: target,
			OutputPath:          filepath.ToSlash(filepath.Join(".local/build/composition", quartetTargetID, filepath.FromSlash(target))),
			EligibleProfileIDs:  []string{}, Warnings: []string{}, Status: "not_selected",
		}

		baselineHashes := map[string]int64{}
		overlayMembers := map[string]bool{}
		for _, profile := range profiles {
			if profile.TargetRelativePath != target || !profile.ProductionEligible {
				continue
			}
			manifest := registry.Profiles[profile.ProfileID].Manifest
			baselineHashes[manifest.BaselineSHA256] = manifest.BaselineSize
			archive.EligibleProfileIDs = append(archive.EligibleProfileIDs, profile.ProfileID)
			for _, member := range manifest.ChangedMembers {
				overlayMembers[foldCompositionPath(member)] = true
			}
		}
		sort.Strings(archive.EligibleProfileIDs)
		archive.OverlayMemberCount = len(overlayMembers)
		if len(archive.EligibleProfileIDs) == 0 {
			if base, ok := translationBases[foldCompositionPath(target)]; ok {
				archive.BaseSourceKind = "verified_translation_archive"
				archive.BaseSourcePath = base.SourcePath
			} else {
				archive.BaseSourceKind = "installed_game_baseline"
			}
			result = append(result, archive)
			continue
		}

		if base, ok := translationBases[foldCompositionPath(target)]; ok {
			archive.BaseSourceKind = "verified_translation_archive"
			archive.BaseSourcePath = base.SourcePath
			if !base.Verified {
				archive.Status = "blocked_translation_base"
				archive.Warnings = append(archive.Warnings, fmt.Sprintf("%s translation base is not verified: %s", target, base.Error))
			}
		} else {
			archive.BaseSourceKind = "installed_game_baseline"
			path, _, err := resolveCaseInsensitiveCompositionPath(gameRoot, target)
			if err != nil {
				archive.Status = "blocked_installed_baseline"
				archive.Warnings = append(archive.Warnings, err.Error())
			} else {
				archive.BaseSourcePath = path
			}
		}

		if len(baselineHashes) > 1 {
			archive.Status = "blocked_inconsistent_profile_baselines"
			archive.Warnings = append(archive.Warnings, fmt.Sprintf("runtime-validated profiles for %s do not share one baseline", target))
		}
		for hash, size := range baselineHashes {
			archive.BaselineSHA256, archive.BaselineBytes = hash, size
		}
		if archive.BaselineSHA256 != "" {
			installedPath, _, err := resolveCaseInsensitiveCompositionPath(gameRoot, target)
			if err != nil {
				archive.Status = "blocked_installed_baseline"
				archive.Warnings = append(archive.Warnings, err.Error())
			} else if hash, size, err := checkedFile(installedPath); err != nil {
				archive.Status = "blocked_installed_baseline"
				archive.Warnings = append(archive.Warnings, err.Error())
			} else {
				archive.InstalledSHA256, archive.InstalledBytes = hash, size
				archive.InstalledBaselineMatch = hash == archive.BaselineSHA256 && size == archive.BaselineBytes
				if !archive.InstalledBaselineMatch {
					archive.Status = "blocked_installed_baseline_mismatch"
					archive.Warnings = append(archive.Warnings, fmt.Sprintf("installed %s differs from the baseline declared by selected restoration profiles", target))
				}
			}
		}
		if archive.Status == "not_selected" {
			archive.Status = "ready_for_member_overlay"
		}
		result = append(result, archive)
	}
	return result
}

func resolveCaseInsensitiveCompositionPath(root, relative string) (string, bool, error) {
	current := filepath.Clean(root)
	parts := strings.Split(filepath.ToSlash(filepath.Clean(filepath.FromSlash(relative))), "/")
	for _, part := range parts {
		entries, err := os.ReadDir(current)
		if err != nil {
			return "", false, fmt.Errorf("read %s while resolving %s: %w", current, relative, err)
		}
		match := ""
		for _, entry := range entries {
			if strings.EqualFold(entry.Name(), part) {
				if match != "" && match != entry.Name() {
					return "", false, fmt.Errorf("ambiguous case-insensitive path component %q under %s", part, current)
				}
				match = entry.Name()
			}
		}
		if match == "" {
			return filepath.Join(current, filepath.FromSlash(strings.Join(parts, "/"))), false, fmt.Errorf("required game archive is missing: %s", relative)
		}
		current = filepath.Join(current, match)
	}
	info, err := os.Lstat(current)
	if err != nil {
		return current, false, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return current, false, fmt.Errorf("game archive is not a regular non-symlink file: %s", current)
	}
	return current, true, nil
}

func foldCompositionPath(value string) string {
	clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(value)))
	clean = strings.TrimPrefix(clean, "./")
	return strings.ToLower(clean)
}

func printHumanQuartetCompositionPreview(out io.Writer, preview quartetCompositionPreview) {
	fmt.Fprintf(out, "\n%s%sQuartet module composition preflight%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, preview.Status)
	selected := map[string]bool{}
	for _, moduleID := range preview.SelectedModules {
		selected[moduleID] = true
	}
	if selected[quartetRestorationModule] {
		fmt.Fprintf(out, "Restoration profiles: %d valid, %d runtime validated, %d production eligible\n", preview.ValidProfileCount, preview.RuntimeValidatedProfileCount, preview.ProductionEligibleCount)
	}
	if selected[quartetLegacyDLCModule] {
		verified := 0
		for _, input := range preview.LegacyDLCInputs {
			if input.Verified {
				verified++
			}
		}
		fmt.Fprintf(out, "Legacy DLC inputs: %d verified of %d\n", verified, len(preview.LegacyDLCInputs))
	}
	for _, archive := range preview.Archives {
		style := ansiGreen
		if strings.HasPrefix(archive.Status, "blocked") {
			style = ansiYellow + ansiBold
		} else if archive.Status == "not_selected" {
			style = ansiDim
		}
		fmt.Fprintf(out, "  %s%-38s%s %s\n", style, archive.ArchiveRelativePath, ansiReset, archive.Status)
		if len(archive.EligibleProfileIDs) > 0 {
			fmt.Fprintf(out, "      profiles=%d overlay_members=%d base=%s\n", len(archive.EligibleProfileIDs), archive.OverlayMemberCount, archive.BaseSourceKind)
		}
		for _, warning := range archive.Warnings {
			fmt.Fprintf(out, "      %s%s%s\n", ansiYellow, warning, ansiReset)
		}
	}
	if selected[quartetRestorationModule] {
		candidateCount := 0
		for _, profile := range preview.Profiles {
			if profile.Status == "candidate_awaiting_runtime_validation" {
				candidateCount++
			}
		}
		if candidateCount > 0 {
			fmt.Fprintf(out, "%s%d valid profile(s) remain candidates and are not included until runtime validation.%s\n", ansiDim, candidateCount, ansiReset)
		}
	}
	fmt.Fprintf(out, "%sPreview only:%s no archive was composed and no game file was modified.\n", ansiBold, ansiReset)
}

func selectionRequestsQuartetComposition(selection model.SelectionResult) (string, []string, bool) {
	for _, target := range selection.Targets {
		if target.TargetID != quartetTargetID {
			continue
		}
		set := map[string]bool{}
		for _, id := range target.SelectedModuleIDs {
			set[id] = true
		}
		if !quartetSelectionNeedsComposition(set) {
			continue
		}
		modules, err := normalizeQuartetCompositionModules(target.SelectedModuleIDs)
		if err != nil {
			return target.Root, append([]string(nil), target.SelectedModuleIDs...), true
		}
		return target.Root, modules, true
	}
	return "", nil, false
}
