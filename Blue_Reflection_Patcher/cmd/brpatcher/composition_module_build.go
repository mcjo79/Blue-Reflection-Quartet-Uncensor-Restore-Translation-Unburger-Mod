package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

func buildQuartetModuleComposition(projectRoot, gameRoot string, modules []string, tool compositionArchiveTool, timeout time.Duration) (quartetCompositionBuildReport, error) {
	normalized, err := normalizeQuartetCompositionModules(modules)
	if err != nil {
		return quartetCompositionBuildReport{}, err
	}
	if sameQuartetCompositionModules(normalized, []string{quartetTranslationModule, quartetRestorationModule}) {
		report, err := buildQuartetComposition(projectRoot, gameRoot, tool, timeout)
		report.FormatVersion = quartetCompositionBuildVersion
		report.SelectedModules = append([]string{}, normalized...)
		report.CompositionPolicy = "verify every selected-module source against one installed baseline, merge only declared member deltas, reject additions/removals or non-identical conflicts, fully re-extract rebuilt archives, and publish locally without touching the game"
		return report, err
	}

	report := quartetCompositionBuildReport{
		Type: quartetCompositionBuildType, FormatVersion: quartetCompositionBuildVersion,
		Status: "failed", GeneratedUTC: time.Now().UTC(), TargetID: quartetTargetID,
		CommitEnabled: false, SelectedModules: append([]string{}, normalized...),
		CompositionPolicy:    "verify every selected-module source against one installed baseline, merge only declared member deltas, reject additions/removals or non-identical conflicts, fully re-extract rebuilt archives, and publish locally without touching the game",
		OutputRoot:           filepath.ToSlash(quartetCompositionOutputRelative),
		EmbeddedReportPath:   filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, quartetCompositionEmbeddedReport)),
		ProductionProfileIDs: []string{}, ProfileInputs: []compositionBuildProfileInput{},
		LegacyDLCInputs: []compositionBuildLegacyDLCInput{}, Archives: []compositionBuildArchive{}, Errors: []string{}, Warnings: []string{},
	}
	projectRoot, err = filepath.Abs(projectRoot)
	if err != nil {
		return report, err
	}
	gameRoot, err = filepath.Abs(gameRoot)
	if err != nil {
		return report, err
	}
	report.ProjectRoot, report.GameRoot = projectRoot, gameRoot
	selected := quartetCompositionModuleSet(normalized)
	if selected[quartetTranslationModule] {
		report.TranslationLooseReportPath = filepath.ToSlash(translationLooseReportRelative)
		report.TranslationRepackReportPath = filepath.ToSlash(translationRepackReportRelative)
		loosePath, err := secureJoin(projectRoot, translationLooseReportRelative)
		if err != nil {
			return report, err
		}
		report.TranslationLooseReportSHA256, report.TranslationLooseReportBytes, err = checkedFile(loosePath)
		if err != nil {
			return report, err
		}
		repackPath, err := secureJoin(projectRoot, translationRepackReportRelative)
		if err != nil {
			return report, err
		}
		report.TranslationRepackReportSHA256, report.TranslationRepackReportBytes, err = checkedFile(repackPath)
		if err != nil {
			return report, err
		}
	}
	toolPath, toolHash, toolSize, err := tool.Identity()
	if err != nil {
		return report, fmt.Errorf("validate archive tool: %w", err)
	}
	report.GustPakPath, report.GustPakSHA256, report.GustPakBytes = toolPath, toolHash, toolSize

	preflight, err := buildQuartetModuleCompositionPreview(projectRoot, gameRoot, normalized)
	if err != nil {
		return report, fmt.Errorf("composition preflight: %w", err)
	}
	report.PreflightStatus = preflight.Status
	if preflight.Status != "ready_for_composition_build" {
		err := fmt.Errorf("composition preflight status is %s, expected ready_for_composition_build", preflight.Status)
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}

	translationByArchive := map[string]compositionTranslationBase{}
	for _, base := range preflight.TranslationBases {
		if base.Verified {
			translationByArchive[foldCompositionPath(base.ArchiveRelativePath)] = base
		}
	}

	registry := localProfileRegistry{Profiles: map[string]discoveredLocalProfile{}, Issues: []localProfileIssue{}}
	profilesByArchive := map[string][]discoveredLocalProfile{}
	if selected[quartetRestorationModule] {
		registry, err = discoverLocalProfiles(projectRoot)
		if err != nil {
			return report, err
		}
		for _, profile := range preflight.Profiles {
			if !profile.ProductionEligible {
				continue
			}
			item, ok := registry.Profiles[profile.ProfileID]
			if !ok {
				return report, fmt.Errorf("preflight-selected profile disappeared: %s", profile.ProfileID)
			}
			report.ProductionProfileIDs = append(report.ProductionProfileIDs, profile.ProfileID)
			key := foldCompositionPath(item.Manifest.TargetRelativePath)
			profilesByArchive[key] = append(profilesByArchive[key], item)
			manifestPath, err := secureJoin(projectRoot, item.ManifestPath)
			if err != nil {
				return report, err
			}
			manifestHash, manifestBytes, err := checkedFile(manifestPath)
			if err != nil {
				return report, err
			}
			payloadHash, payloadBytes, err := checkedFile(item.SourcePath)
			if err != nil {
				return report, err
			}
			report.ProfileInputs = append(report.ProfileInputs, compositionBuildProfileInput{
				ProfileID: profile.ProfileID, ManifestPath: filepath.ToSlash(item.ManifestPath),
				ManifestSHA256: manifestHash, ManifestBytes: manifestBytes,
				PayloadPath: relativeDisplayPath(projectRoot, item.SourcePath), PayloadSHA256: payloadHash, PayloadBytes: payloadBytes,
				TargetRelativePath: item.Manifest.TargetRelativePath, BaselineSHA256: item.Manifest.BaselineSHA256,
				BaselineBytes: item.Manifest.BaselineSize, RuntimeValidated: item.Manifest.RuntimeValidated,
			})
		}
	}
	sort.Strings(report.ProductionProfileIDs)
	sort.Slice(report.ProfileInputs, func(i, j int) bool { return report.ProfileInputs[i].ProfileID < report.ProfileInputs[j].ProfileID })
	for key := range profilesByArchive {
		sort.Slice(profilesByArchive[key], func(i, j int) bool {
			return profilesByArchive[key][i].Manifest.ProfileID < profilesByArchive[key][j].Manifest.ProfileID
		})
	}

	legacyByArchive := map[string]payloadpreview.LegacyDLCCompositionArtifact{}
	if selected[quartetLegacyDLCModule] {
		contract, err := payloadpreview.LoadLegacyDLCCompositionContract(projectRoot, gameRoot)
		if err != nil {
			return report, err
		}
		for _, item := range contract.Artifacts {
			legacyByArchive[foldCompositionPath(item.RelativePath)] = item
			report.LegacyDLCInputs = append(report.LegacyDLCInputs, compositionBuildLegacyDLCInput{
				ManifestPath: relativeDisplayPath(projectRoot, contract.ManifestPath), ManifestSHA256: contract.ManifestSHA256, ManifestBytes: contract.ManifestBytes,
				FamilyID: contract.FamilyID, Generation: contract.Generation, Members: append([]string{}, contract.Members...), TransactionGroup: contract.TransactionGroup,
				WorkstreamVersion: contract.WorkstreamVersion, ProvenanceEvidencePath: relativeDisplayPath(projectRoot, contract.ProvenanceEvidencePath), ProvenanceEvidenceHash: contract.ProvenanceEvidenceHash,
				ArchiveRelativePath: item.RelativePath, CandidatePath: relativeDisplayPath(projectRoot, item.CandidatePath),
				CandidateSHA256: item.CandidateSHA256, CandidateBytes: item.CandidateSize,
				BaselinePath: item.BaselinePath, BaselineSHA256: item.BaselineSHA256, BaselineBytes: item.BaselineSize,
				AddedMembers: append([]string{}, item.AddedMembers...), ChangedMembers: append([]string{}, item.ChangedMembers...),
				RemovedMembers: append([]string{}, item.RemovedMembers...),
			})
		}
	}

	lock, err := acquireCompositionBuildLock(projectRoot)
	if err != nil {
		return report, err
	}
	report.CompositionLockReclaimed = lock.Reclaimed
	report.CompositionLockReclaimReason = lock.ReclaimReason
	report.CompositionLockPreviousOwner = lock.PreviousOwner
	defer releaseCompositionBuildLock(lock)
	outputRoot, err := secureJoin(projectRoot, quartetCompositionOutputRelative)
	if err != nil {
		return report, err
	}
	if err := os.MkdirAll(filepath.Dir(outputRoot), 0o700); err != nil {
		return report, err
	}
	stagingRoot, err := os.MkdirTemp(filepath.Dir(outputRoot), ".blue_reflection_quartet-compose-*")
	if err != nil {
		return report, err
	}
	published := false
	defer func() {
		if !published {
			_ = os.RemoveAll(stagingRoot)
		}
	}()
	workRoot := filepath.Join(stagingRoot, ".work")
	if err := os.MkdirAll(workRoot, 0o700); err != nil {
		return report, err
	}

	archivePaths := map[string]string{}
	for key, base := range translationByArchive {
		archivePaths[key] = base.ArchiveRelativePath
	}
	for key, legacy := range legacyByArchive {
		archivePaths[key] = legacy.RelativePath
	}
	for key, profiles := range profilesByArchive {
		if len(profiles) > 0 {
			archivePaths[key] = profiles[0].Manifest.TargetRelativePath
		}
	}
	keys := make([]string, 0, len(archivePaths))
	for key := range archivePaths {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool { return archivePaths[keys[i]] < archivePaths[keys[j]] })
	for _, key := range keys {
		relative := archivePaths[key]
		translationBase, hasTranslation := translationByArchive[key]
		legacy, hasLegacy := legacyByArchive[key]
		profiles := profilesByArchive[key]
		var archive compositionBuildArchive
		switch {
		case hasTranslation && !hasLegacy && len(profiles) == 0:
			archive, err = publishTranslationPassthrough(projectRoot, stagingRoot, translationBase)
		case hasLegacy && !hasTranslation && len(profiles) == 0:
			archive, err = publishLegacyDLCPassthrough(projectRoot, stagingRoot, legacy)
		default:
			archive, err = composeQuartetModuleArchive(projectRoot, gameRoot, stagingRoot, workRoot, relative, translationBase, hasTranslation, legacy, hasLegacy, profiles, tool, timeout)
		}
		if err != nil {
			report.Archives = append(report.Archives, archive)
			report.Errors = append(report.Errors, fmt.Sprintf("%s: %v", relative, err))
			return report, fmt.Errorf("compose %s: %w", relative, err)
		}
		report.Archives = append(report.Archives, archive)
		report.PublishedArchiveCount++
		if archive.Mode == "member_overlay" {
			report.ComposedArchiveCount++
			if archive.FullReextractVerified {
				report.FullReextractCount++
			}
		} else {
			report.PassthroughArchiveCount++
		}
	}
	_ = os.RemoveAll(workRoot)
	report.Status = "ok"
	embedded := filepath.Join(stagingRoot, quartetCompositionEmbeddedReport)
	if err := writeJSONAtomic(embedded, report, 0o600); err != nil {
		return report, err
	}
	if err := publishCompositionDirectory(stagingRoot, outputRoot); err != nil {
		return report, err
	}
	published = true
	return report, nil
}

func publishLegacyDLCPassthrough(projectRoot, stagingRoot string, legacy payloadpreview.LegacyDLCCompositionArtifact) (compositionBuildArchive, error) {
	archive := compositionBuildArchive{
		ArchiveRelativePath: legacy.RelativePath, Mode: "verified_legacy_dlc_passthrough",
		BaseSourceKind: "verified_legacy_dlc_candidate", BaseSourcePath: relativeDisplayPath(projectRoot, legacy.CandidatePath),
		BaseSHA256: legacy.CandidateSHA256, BaseBytes: legacy.CandidateSize,
		InstalledBaselinePath: legacy.BaselinePath, InstalledBaselineSHA256: legacy.BaselineSHA256, InstalledBaselineBytes: legacy.BaselineSize,
		ProfileIDs: []string{}, TranslationChangedMembers: []string{}, OverlayMembers: []compositionBuildMember{},
		Status: "failed", Warnings: []string{}, ManifestDeclarationChecked: true,
	}
	destination, err := secureJoin(stagingRoot, legacy.RelativePath)
	if err != nil {
		return archive, err
	}
	if err := copyFileDurable(legacy.CandidatePath, destination, legacy.CandidateSHA256, legacy.CandidateSize, 0o600); err != nil {
		return archive, err
	}
	archive.OutputPath = filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, filepath.FromSlash(legacy.RelativePath)))
	archive.OutputSHA256, archive.OutputBytes, err = checkedFile(destination)
	if err != nil {
		return archive, err
	}
	archive.Status = "published_verified_legacy_dlc_passthrough"
	return archive, nil
}

func composeQuartetModuleArchive(projectRoot, gameRoot, stagingRoot, workRoot, archiveRelative string, translationBase compositionTranslationBase, hasTranslation bool, legacy payloadpreview.LegacyDLCCompositionArtifact, hasLegacy bool, profiles []discoveredLocalProfile, tool compositionArchiveTool, timeout time.Duration) (compositionBuildArchive, error) {
	archive := compositionBuildArchive{
		ArchiveRelativePath: archiveRelative, Mode: "member_overlay", ProfileIDs: []string{},
		TranslationChangedMembers: []string{}, OverlayMembers: []compositionBuildMember{}, Status: "failed", Warnings: []string{},
	}
	for _, profile := range profiles {
		archive.ProfileIDs = append(archive.ProfileIDs, profile.Manifest.ProfileID)
	}
	sort.Strings(archive.ProfileIDs)
	installedPath, _, err := resolveCaseInsensitiveCompositionPath(gameRoot, archiveRelative)
	if err != nil {
		return archive, err
	}
	installedHash, installedSize, err := checkedFile(installedPath)
	if err != nil {
		return archive, err
	}
	archive.InstalledBaselinePath, archive.InstalledBaselineSHA256, archive.InstalledBaselineBytes = installedPath, installedHash, installedSize
	if hasLegacy && (legacy.BaselineSHA256 != installedHash || legacy.BaselineSize != installedSize) {
		return archive, fmt.Errorf("Legacy DLC baseline differs from installed archive")
	}
	for _, profile := range profiles {
		if profile.Manifest.BaselineSHA256 != installedHash || profile.Manifest.BaselineSize != installedSize {
			return archive, fmt.Errorf("Restoration profile %s baseline differs from installed archive", profile.Manifest.ProfileID)
		}
	}
	archiveWork := filepath.Join(workRoot, safeWorkName(archiveRelative))
	baselineExtract, err := tool.Extract(installedPath, filepath.Join(archiveWork, "baseline"), timeout)
	if err != nil {
		return archive, err
	}
	baselineMembers, err := hashCompositionMembers(baselineExtract.Root, baselineExtract.Entries)
	if err != nil {
		return archive, err
	}
	baseExtract := baselineExtract
	if hasTranslation {
		translationPath, err := resolveCompositionProjectPath(projectRoot, translationBase.SourcePath)
		if err != nil {
			return archive, err
		}
		archive.BaseSourceKind, archive.BaseSourcePath = "verified_translation_archive", translationBase.SourcePath
		archive.BaseSHA256, archive.BaseBytes = translationBase.SHA256, translationBase.Bytes
		archive.TranslationChangedMembers = append([]string{}, translationBase.ChangedMembers...)
		baseExtract, err = tool.Extract(translationPath, filepath.Join(archiveWork, "base"), timeout)
		if err != nil {
			return archive, err
		}
		if err := requireSameEntrySet(baselineExtract.Entries, baseExtract.Entries); err != nil {
			return archive, fmt.Errorf("translation member set differs from baseline: %w", err)
		}
		baseMembers, err := hashCompositionMembers(baseExtract.Root, baseExtract.Entries)
		if err != nil {
			return archive, err
		}
		actual := memberDifferences(baselineMembers, baseMembers)
		declared, err := foldedMemberSet(translationBase.ChangedMembers)
		if err != nil {
			return archive, err
		}
		if extras := setDifference(actual, declared); len(extras) > 0 {
			return archive, fmt.Errorf("translation PAK changes undeclared member(s): %s", strings.Join(extras, ", "))
		}
	} else if hasLegacy {
		archive.BaseSourceKind, archive.BaseSourcePath = "verified_legacy_dlc_candidate", relativeDisplayPath(projectRoot, legacy.CandidatePath)
		archive.BaseSHA256, archive.BaseBytes = legacy.CandidateSHA256, legacy.CandidateSize
		baseExtract, err = tool.Extract(legacy.CandidatePath, filepath.Join(archiveWork, "base"), timeout)
		if err != nil {
			return archive, err
		}
	} else {
		archive.BaseSourceKind, archive.BaseSourcePath = "installed_game_baseline", installedPath
		archive.BaseSHA256, archive.BaseBytes = installedHash, installedSize
	}

	var legacyExtract compositionExtractedArchive
	legacyOverlays := map[string]compositionOverlaySource{}
	if hasLegacy {
		legacyExtract, err = tool.Extract(legacy.CandidatePath, filepath.Join(archiveWork, "legacy-dlc"), timeout)
		if err != nil {
			return archive, err
		}
		legacyOverlays, err = verifyLegacyDLCMemberDelta(baselineExtract, baselineMembers, legacyExtract, legacy)
		if err != nil {
			return archive, err
		}
		if hasTranslation && len(legacy.AddedMembers) > 0 {
			return archive, fmt.Errorf("translation-based composition cannot add Legacy DLC members to %s", archiveRelative)
		}
	}

	stageRoot := filepath.Join(archiveWork, "stage")
	if err := cloneCompositionExtraction(baseExtract.Root, stageRoot); err != nil {
		return archive, err
	}
	manifestRelative, err := filepath.Rel(baseExtract.Root, baseExtract.ManifestPath)
	if err != nil {
		return archive, err
	}
	stageManifest := filepath.Join(stageRoot, manifestRelative)
	baseMembers, err := hashCompositionMembers(baseExtract.Root, baseExtract.Entries)
	if err != nil {
		return archive, err
	}
	overlays := map[string]compositionOverlaySource{}
	if hasLegacy && hasTranslation {
		for key, overlay := range legacyOverlays {
			if err := mergeModuleCompositionOverlay(overlays, key, overlay); err != nil {
				return archive, err
			}
		}
	}
	for _, profile := range profiles {
		profileExtract, err := tool.Extract(profile.SourcePath, filepath.Join(archiveWork, "profile-"+safeWorkName(profile.Manifest.ProfileID)), timeout)
		if err != nil {
			return archive, err
		}
		if err := requireSameEntrySet(baselineExtract.Entries, profileExtract.Entries); err != nil {
			return archive, err
		}
		profileMembers, err := hashCompositionMembers(profileExtract.Root, profileExtract.Entries)
		if err != nil {
			return archive, err
		}
		actual := memberDifferences(baselineMembers, profileMembers)
		declared, err := foldedMemberSet(profile.Manifest.ChangedMembers)
		if err != nil || !sameStringSet(actual, declared) {
			return archive, fmt.Errorf("profile %s manifest declaration mismatch", profile.Manifest.ProfileID)
		}
		for _, raw := range profile.Manifest.ChangedMembers {
			member, err := normalizeCompositionMember(raw)
			if err != nil {
				return archive, err
			}
			key := foldCompositionPath(member)
			if hasLegacy {
				if _, conflict := legacyOverlays[key]; conflict {
					return archive, fmt.Errorf("Restoration and Legacy DLC member conflict: %s", member)
				}
			}
			fingerprint := profileMembers[key]
			source, err := secureCompositionMemberPath(profileExtract.Root, fingerprint.Path)
			if err != nil {
				return archive, err
			}
			candidate := compositionOverlaySource{Member: compositionBuildMember{InternalPath: fingerprint.Path, SHA256: fingerprint.SHA256, Bytes: fingerprint.Bytes, SourceProfileIDs: []string{profile.Manifest.ProfileID}, SourceModuleIDs: []string{quartetRestorationModule}}, SourcePath: source}
			if err := mergeModuleCompositionOverlay(overlays, key, candidate); err != nil {
				return archive, err
			}
		}
	}
	overlayKeys := make([]string, 0, len(overlays))
	for key := range overlays {
		overlayKeys = append(overlayKeys, key)
	}
	sort.Strings(overlayKeys)
	for _, key := range overlayKeys {
		overlay := overlays[key]
		destination, err := secureCompositionMemberPath(stageRoot, overlay.Member.InternalPath)
		if err != nil {
			return archive, err
		}
		if err := replaceCompositionMember(overlay.SourcePath, destination, overlay.Member.SHA256, overlay.Member.Bytes); err != nil {
			return archive, err
		}
		archive.OverlayMembers = append(archive.OverlayMembers, overlay.Member)
	}
	stageMembers, err := hashCompositionMembers(stageRoot, baseExtract.Entries)
	if err != nil {
		return archive, err
	}
	actualStage := memberDifferences(baseMembers, stageMembers)
	expectedStage := map[string]bool{}
	for _, key := range overlayKeys {
		expectedStage[key] = true
	}
	if !sameStringSet(actualStage, expectedStage) {
		return archive, fmt.Errorf("staged composition changed unexpected members")
	}
	archive.ManifestDeclarationChecked = true
	archive.UnchangedMemberCount = len(baseExtract.Entries) - len(overlayKeys)
	builtPak, _, err := tool.Repack(stageManifest, stageRoot, timeout)
	if err != nil {
		return archive, err
	}
	outputEntries, _, err := tool.List(builtPak, timeout)
	if err != nil {
		return archive, err
	}
	if err := requireSameEntrySet(baseExtract.Entries, outputEntries); err != nil {
		return archive, err
	}
	verifyExtract, err := tool.Extract(builtPak, filepath.Join(archiveWork, "verify"), timeout)
	if err != nil {
		return archive, err
	}
	verifiedMembers, err := hashCompositionMembers(verifyExtract.Root, verifyExtract.Entries)
	if err != nil {
		return archive, err
	}
	if differences := detailedMemberHashDifferences(stageMembers, verifiedMembers); len(differences) > 0 {
		return archive, fmt.Errorf("full re-extract verification failed: %s", strings.Join(differences, "; "))
	}
	archive.ListedEntryCount, archive.ReextractedEntryCount = len(outputEntries), len(verifiedMembers)
	archive.FullReextractVerified = true
	outputDestination, err := secureJoin(stagingRoot, archiveRelative)
	if err != nil {
		return archive, err
	}
	builtHash, builtSize, err := checkedFile(builtPak)
	if err != nil {
		return archive, err
	}
	if err := copyFileDurable(builtPak, outputDestination, builtHash, builtSize, 0o600); err != nil {
		return archive, err
	}
	archive.OutputPath = filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, filepath.FromSlash(archiveRelative)))
	archive.OutputSHA256, archive.OutputBytes = builtHash, builtSize
	archive.Status = "published_member_overlay_verified"
	return archive, nil
}

func verifyLegacyDLCMemberDelta(baselineExtract compositionExtractedArchive, baselineMembers map[string]compositionMemberFingerprint, candidateExtract compositionExtractedArchive, legacy payloadpreview.LegacyDLCCompositionArtifact) (map[string]compositionOverlaySource, error) {
	candidateMembers, err := hashCompositionMembers(candidateExtract.Root, candidateExtract.Entries)
	if err != nil {
		return nil, err
	}
	added := map[string]bool{}
	changed := map[string]bool{}
	removed := map[string]bool{}
	for key, candidate := range candidateMembers {
		baseline, ok := baselineMembers[key]
		if !ok {
			added[key] = true
		} else if candidate.SHA256 != baseline.SHA256 || candidate.Bytes != baseline.Bytes {
			changed[key] = true
		}
	}
	for key := range baselineMembers {
		if _, ok := candidateMembers[key]; !ok {
			removed[key] = true
		}
	}
	expectedAdded, err := foldedMemberSet(legacy.AddedMembers)
	if err != nil {
		return nil, err
	}
	expectedChanged, err := foldedMemberSet(legacy.ChangedMembers)
	if err != nil {
		return nil, err
	}
	expectedRemoved, err := foldedMemberSet(legacy.RemovedMembers)
	if err != nil {
		return nil, err
	}
	if !sameStringSet(added, expectedAdded) || !sameStringSet(changed, expectedChanged) || !sameStringSet(removed, expectedRemoved) {
		return nil, fmt.Errorf("Legacy DLC candidate member delta mismatch: added=%s changed=%s removed=%s", strings.Join(sortedSet(added), ","), strings.Join(sortedSet(changed), ","), strings.Join(sortedSet(removed), ","))
	}
	result := map[string]compositionOverlaySource{}
	for key := range changed {
		fingerprint := candidateMembers[key]
		source, err := secureCompositionMemberPath(candidateExtract.Root, fingerprint.Path)
		if err != nil {
			return nil, err
		}
		result[key] = compositionOverlaySource{Member: compositionBuildMember{InternalPath: fingerprint.Path, SHA256: fingerprint.SHA256, Bytes: fingerprint.Bytes, SourceModuleIDs: []string{quartetLegacyDLCModule}}, SourcePath: source}
	}
	return result, nil
}

func mergeModuleCompositionOverlay(overlays map[string]compositionOverlaySource, key string, candidate compositionOverlaySource) error {
	if existing, ok := overlays[key]; ok {
		if existing.Member.SHA256 != candidate.Member.SHA256 || existing.Member.Bytes != candidate.Member.Bytes {
			return fmt.Errorf("non-identical module overlay conflict for %s", candidate.Member.InternalPath)
		}
		existing.Member.SourceProfileIDs = append(existing.Member.SourceProfileIDs, candidate.Member.SourceProfileIDs...)
		existing.Member.SourceModuleIDs = append(existing.Member.SourceModuleIDs, candidate.Member.SourceModuleIDs...)
		sort.Strings(existing.Member.SourceProfileIDs)
		sort.Strings(existing.Member.SourceModuleIDs)
		existing.Member.SourceProfileIDs = uniqueStrings(existing.Member.SourceProfileIDs)
		existing.Member.SourceModuleIDs = uniqueStrings(existing.Member.SourceModuleIDs)
		overlays[key] = existing
		return nil
	}
	overlays[key] = candidate
	return nil
}
