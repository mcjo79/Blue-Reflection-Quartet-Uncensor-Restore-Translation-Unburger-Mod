package main

import (
	"fmt"
	"path/filepath"
	"sort"
	"time"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

func buildQuartetModuleCompositionPreview(rawProjectRoot, gameRoot string, modules []string) (quartetCompositionPreview, error) {
	return buildQuartetModuleCompositionPreviewWithPolicy(rawProjectRoot, gameRoot, modules, restorationProfilePolicyRuntimeValidated)
}

func buildQuartetModuleCompositionPreviewWithPolicy(rawProjectRoot, gameRoot string, modules []string, rawPolicy string) (quartetCompositionPreview, error) {
	normalized, err := normalizeQuartetCompositionModules(modules)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	policy, err := normalizeRestorationProfilePolicy(rawPolicy)
	if err != nil {
		return quartetCompositionPreview{}, err
	}
	if err := validateRestorationProfilePolicyForModules(policy, normalized); err != nil {
		return quartetCompositionPreview{}, err
	}
	runtimeTestMode := policy == restorationProfilePolicyAllCandidatesRuntimeTest
	if !runtimeTestMode && sameQuartetCompositionModules(normalized, []string{quartetTranslationModule, quartetRestorationModule}) {
		preview, err := buildQuartetCompositionPreview(rawProjectRoot, gameRoot)
		if err != nil {
			return quartetCompositionPreview{}, err
		}
		preview.FormatVersion = quartetCompositionPreviewVersion
		preview.SelectedModules = append([]string{}, normalized...)
		preview.CompositionPolicy = "start from each verified selected-module source, merge only declared member deltas, reject additions/removals or non-identical member conflicts, and fully re-extract every rebuilt archive"
		preview.ProfileSelectionPolicy = policy
		for index := range preview.Profiles {
			preview.Profiles[index].SelectedForComposition = preview.Profiles[index].ProductionEligible
			if preview.Profiles[index].SelectedForComposition {
				preview.SelectedProfileCount++
			}
		}
		return preview, nil
	}

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
	selected := quartetCompositionModuleSet(normalized)
	preview := quartetCompositionPreview{
		Type: quartetCompositionPreviewType, FormatVersion: quartetCompositionPreviewVersion,
		GeneratedUTC: time.Now().UTC(), ProjectRoot: projectRoot, GameRoot: gameRoot,
		TargetID: quartetTargetID, CommitEnabled: false,
		SelectedModules:        append([]string{}, normalized...),
		ProfileSelectionPolicy: policy,
		RuntimeTestOnly:        runtimeTestMode,
		CompositionPolicy:      "start from each verified selected-module source, merge only declared member deltas, reject additions/removals or non-identical member conflicts, and fully re-extract every rebuilt archive",
		TranslationBases:       []compositionTranslationBase{}, LegacyDLCInputs: []compositionLegacyDLCInput{},
		Profiles: []compositionProfilePreview{}, Archives: []compositionArchivePreview{},
		RegistryIssues: []localProfileIssue{}, Warnings: []string{},
	}
	if runtimeTestMode {
		preview.CompositionPolicy = "isolated Restoration-only runtime test: select every current valid profile manifest, require a stable all-candidate set, reject member conflicts, compose from exact installed baselines, and keep production eligibility unchanged"
	}

	translationMembers := map[string]map[string]bool{}
	translationBaseByArchive := map[string]compositionTranslationBase{}
	translationReady := true
	if selected[quartetTranslationModule] {
		preview.TranslationLooseReport = filepath.ToSlash(translationLooseReportRelative)
		preview.TranslationRepackReport = filepath.ToSlash(translationRepackReportRelative)
		loose, err := loadCompositionLooseReport(filepath.Join(projectRoot, filepath.FromSlash(translationLooseReportRelative)), projectRoot)
		if err != nil {
			return quartetCompositionPreview{}, err
		}
		repack, err := loadCompositionRepackReport(filepath.Join(projectRoot, filepath.FromSlash(translationRepackReportRelative)), projectRoot)
		if err != nil {
			return quartetCompositionPreview{}, err
		}
		translationMembers = changedTranslationMembers(loose)
		preview.TranslationBases = verifyQuartetTranslationBases(projectRoot, repack, translationMembers)
		for _, base := range preview.TranslationBases {
			translationBaseByArchive[foldCompositionPath(base.ArchiveRelativePath)] = base
			if !base.Verified {
				translationReady = false
			}
		}
	}

	var registry localProfileRegistry
	eligibleProfilesByArchive := map[string][]discoveredLocalProfile{}
	runtimeBlocked := false
	if selected[quartetRestorationModule] {
		preview.ProfileManifestRoot = filepath.ToSlash(localProfileManifestRoot)
		registry, err = discoverLocalProfiles(projectRoot)
		if err != nil {
			return quartetCompositionPreview{}, err
		}
		preview.RegistryIssues = append([]localProfileIssue{}, registry.Issues...)
		preview.RegistryIssueCount = len(registry.Issues)
		profileIDs := make([]string, 0, len(registry.Profiles))
		for id := range registry.Profiles {
			profileIDs = append(profileIDs, id)
		}
		sort.Strings(profileIDs)
		selectedOwners := map[string][]string{}
		for _, id := range profileIDs {
			item := registry.Profiles[id]
			if !runtimeTestMode && !item.Manifest.RuntimeValidated {
				continue
			}
			for _, member := range item.Manifest.ChangedMembers {
				key := foldCompositionPath(item.Manifest.TargetRelativePath) + "\x00" + foldCompositionPath(member)
				selectedOwners[key] = append(selectedOwners[key], id)
			}
		}
		for key := range selectedOwners {
			sort.Strings(selectedOwners[key])
		}
		for _, id := range profileIDs {
			item := registry.Profiles[id]
			manifest := item.Manifest
			profile := compositionProfilePreview{
				ProfileID: id, TargetRelativePath: manifest.TargetRelativePath,
				ManifestPath: item.ManifestPath, SourcePath: relativeDisplayPath(projectRoot, item.SourcePath),
				WorkstreamVersion: manifest.WorkstreamVersion, RuntimeValidated: manifest.RuntimeValidated,
				ChangedMemberCount: manifest.ChangedMemberCount, ChangedMembers: append([]string{}, manifest.ChangedMembers...),
				TranslationConflicts: []string{}, RuntimeProfileConflicts: []string{},
			}
			translationSet := translationMembers[foldCompositionPath(manifest.TargetRelativePath)]
			for _, member := range manifest.ChangedMembers {
				foldedMember := foldCompositionPath(member)
				if translationSet[foldedMember] {
					profile.TranslationConflicts = append(profile.TranslationConflicts, member)
				}
				key := foldCompositionPath(manifest.TargetRelativePath) + "\x00" + foldedMember
				owners := selectedOwners[key]
				if len(owners) > 1 {
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
				profile.Status = "blocked_profile_member_conflict"
			case runtimeTestMode:
				profile.Status = "eligible_runtime_test_candidate"
				profile.RuntimeTestEligible = true
				profile.SelectedForComposition = true
				key := foldCompositionPath(manifest.TargetRelativePath)
				eligibleProfilesByArchive[key] = append(eligibleProfilesByArchive[key], item)
			case !profile.RuntimeValidated:
				profile.Status = "candidate_awaiting_runtime_validation"
			default:
				profile.Status = "eligible_runtime_validated"
				profile.ProductionEligible = true
				profile.SelectedForComposition = true
				key := foldCompositionPath(manifest.TargetRelativePath)
				eligibleProfilesByArchive[key] = append(eligibleProfilesByArchive[key], item)
			}
			if profile.RuntimeValidated {
				preview.RuntimeValidatedProfileCount++
				if !runtimeTestMode && !profile.ProductionEligible {
					runtimeBlocked = true
				}
			}
			if len(profile.RuntimeProfileConflicts) > 0 {
				runtimeBlocked = true
			}
			if profile.ProductionEligible {
				preview.ProductionEligibleCount++
			}
			if profile.RuntimeTestEligible {
				preview.RuntimeTestCandidateCount++
			}
			if profile.SelectedForComposition {
				preview.SelectedProfileCount++
			}
			preview.Profiles = append(preview.Profiles, profile)
		}
		preview.ValidProfileCount = len(preview.Profiles)
		if len(registry.Issues) > 0 {
			preview.Warnings = append(preview.Warnings, fmt.Sprintf("%d invalid restoration profile manifest(s) were isolated and excluded", len(registry.Issues)))
		}
	}

	legacyByArchive := map[string]compositionLegacyDLCInput{}
	legacyReady := true
	if selected[quartetLegacyDLCModule] {
		contract, err := payloadpreview.LoadLegacyDLCCompositionContract(projectRoot, gameRoot)
		if err != nil {
			legacyReady = false
			preview.Warnings = append(preview.Warnings, err.Error())
		} else {
			for _, item := range contract.Artifacts {
				input := compositionLegacyDLCInput{
					ManifestPath: relativeDisplayPath(projectRoot, contract.ManifestPath), ManifestSHA256: contract.ManifestSHA256, ManifestBytes: contract.ManifestBytes,
					FamilyID: contract.FamilyID, Generation: contract.Generation, Members: append([]string{}, contract.Members...), TransactionGroup: contract.TransactionGroup,
					WorkstreamVersion: contract.WorkstreamVersion, ProvenanceEvidencePath: relativeDisplayPath(projectRoot, contract.ProvenanceEvidencePath), ProvenanceEvidenceHash: contract.ProvenanceEvidenceHash,
					ArchiveRelativePath: item.RelativePath, CandidatePath: relativeDisplayPath(projectRoot, item.CandidatePath),
					CandidateSHA256: item.CandidateSHA256, CandidateBytes: item.CandidateSize,
					BaselinePath: item.BaselinePath, BaselineSHA256: item.BaselineSHA256, BaselineBytes: item.BaselineSize,
					AddedMembers: append([]string{}, item.AddedMembers...), ChangedMembers: append([]string{}, item.ChangedMembers...),
					RemovedMembers: append([]string{}, item.RemovedMembers...), Verified: true,
				}
				preview.LegacyDLCInputs = append(preview.LegacyDLCInputs, input)
				legacyByArchive[foldCompositionPath(item.RelativePath)] = input
			}
		}
	}

	archivePaths := map[string]string{}
	for key, base := range translationBaseByArchive {
		archivePaths[key] = base.ArchiveRelativePath
	}
	for key, input := range legacyByArchive {
		archivePaths[key] = input.ArchiveRelativePath
	}
	for key, profiles := range eligibleProfilesByArchive {
		if len(profiles) > 0 {
			archivePaths[key] = profiles[0].Manifest.TargetRelativePath
		}
	}
	keys := make([]string, 0, len(archivePaths))
	for key := range archivePaths {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool { return archivePaths[keys[i]] < archivePaths[keys[j]] })
	archiveBlocked := false
	for _, key := range keys {
		relative := archivePaths[key]
		base, hasTranslation := translationBaseByArchive[key]
		legacy, hasLegacy := legacyByArchive[key]
		profiles := eligibleProfilesByArchive[key]
		archive := compositionArchivePreview{
			ArchiveRelativePath: relative,
			OutputPath:          filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, filepath.FromSlash(relative))),
			EligibleProfileIDs:  []string{}, Warnings: []string{}, Status: "ready_for_passthrough",
		}
		for _, profile := range profiles {
			archive.EligibleProfileIDs = append(archive.EligibleProfileIDs, profile.Manifest.ProfileID)
		}
		sort.Strings(archive.EligibleProfileIDs)
		if hasTranslation {
			archive.BaseSourceKind = "verified_translation_archive"
			archive.BaseSourcePath = base.SourcePath
		} else if hasLegacy {
			archive.BaseSourceKind = "verified_legacy_dlc_candidate"
			archive.BaseSourcePath = legacy.CandidatePath
			archive.BaselineSHA256, archive.BaselineBytes = legacy.BaselineSHA256, legacy.BaselineBytes
			archive.InstalledSHA256, archive.InstalledBytes = legacy.BaselineSHA256, legacy.BaselineBytes
			archive.InstalledBaselineMatch = true
		} else {
			archive.BaseSourceKind = "installed_game_baseline"
		}
		legacyDelta := map[string]bool{}
		if hasLegacy {
			for _, member := range append(append([]string{}, legacy.AddedMembers...), legacy.ChangedMembers...) {
				legacyDelta[foldCompositionPath(member)] = true
			}
			if len(legacy.RemovedMembers) > 0 {
				archive.Status = "blocked_legacy_dlc_removal"
				archive.Warnings = append(archive.Warnings, "Legacy DLC composition contract contains removed members")
				archiveBlocked = true
			}
		}
		if hasTranslation && hasLegacy {
			for member := range translationMembers[key] {
				if legacyDelta[member] {
					archive.Status = "blocked_translation_legacy_dlc_member_conflict"
					archive.Warnings = append(archive.Warnings, "Translation and Legacy DLC declare the same member: "+member)
					archiveBlocked = true
				}
			}
		}
		for _, profile := range profiles {
			for _, member := range profile.Manifest.ChangedMembers {
				if legacyDelta[foldCompositionPath(member)] {
					archive.Status = "blocked_restoration_legacy_dlc_member_conflict"
					archive.Warnings = append(archive.Warnings, "Restoration and Legacy DLC declare the same member: "+member)
					archiveBlocked = true
				}
			}
		}
		archive.OverlayMemberCount = len(legacyDelta)
		for _, profile := range profiles {
			archive.OverlayMemberCount += len(profile.Manifest.ChangedMembers)
		}
		if archive.Status == "ready_for_passthrough" && (len(profiles) > 0 || (hasTranslation && hasLegacy)) {
			archive.Status = "ready_for_member_overlay"
		}
		preview.Archives = append(preview.Archives, archive)
		preview.Warnings = append(preview.Warnings, archive.Warnings...)
	}

	switch {
	case selected[quartetTranslationModule] && !translationReady:
		preview.Status = "blocked_translation_build_unavailable"
	case selected[quartetLegacyDLCModule] && !legacyReady:
		preview.Status = "blocked_legacy_dlc_input_unavailable"
	case runtimeBlocked:
		preview.Status = "blocked_member_conflict"
	case archiveBlocked:
		preview.Status = "blocked_archive_precondition"
	case runtimeTestMode && selected[quartetRestorationModule] && preview.SelectedProfileCount > 0 && preview.RegistryIssueCount == 0:
		preview.Status = "ready_for_runtime_test_composition_build"
	case runtimeTestMode && preview.RegistryIssueCount > 0:
		preview.Status = "blocked_invalid_profile_registry"
	case selected[quartetRestorationModule] && preview.ProductionEligibleCount > 0:
		preview.Status = "ready_for_composition_build"
	case selected[quartetRestorationModule] && preview.ValidProfileCount > 0:
		preview.Status = "awaiting_runtime_validated_profiles"
	case selected[quartetRestorationModule]:
		preview.Status = "no_restoration_profiles_registered"
	default:
		preview.Status = "ready_for_composition_build"
	}
	return preview, nil
}
