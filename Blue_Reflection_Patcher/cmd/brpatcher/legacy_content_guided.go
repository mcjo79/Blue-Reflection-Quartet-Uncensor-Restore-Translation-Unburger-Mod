package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/translationbundle"
)

type legacyContentStartOptions struct {
	ProjectRoot       string
	ReleaseRoot       string
	SourceRoot        string
	SteamRoot         string
	AssetRoot         string
	DisableAutoSource bool
	SimplifiedLabels  string
	SaveRoot          string
	SyncSaves         bool
	BuildLocal        bool
	Prepare           bool
	Install           bool
	Confirmed         bool
	Prompt            bool
}

type legacyContentResult struct {
	Survey             br1rebuild.SurveyReport              `json:"survey"`
	Build              br1rebuild.ReconstructionBuildReport `json:"build,omitempty"`
	Restoration        *br1rebuild.RestorationLayerAudit    `json:"restoration,omitempty"`
	Translation        *br1rebuild.TranslationLayerAudit    `json:"translation,omitempty"`
	TranslationRecords *translationbundle.ApplyAudit        `json:"translation_records,omitempty"`
	FinalAudit         *br1rebuild.CrossFileAudit           `json:"final_cross_file_audit,omitempty"`
	TitleMarker        *br1rebuild.QuartetTitleMarkerAudit  `json:"title_marker,omitempty"`
	JournalPath        string                               `json:"journal_path,omitempty"`
	TransactionID      string                               `json:"transaction_id,omitempty"`
	Status             string                               `json:"status"`
	GameModified       bool                                 `json:"game_modified"`
}

func selectionUsesIntegratedQuartetContent(selection model.SelectionResult) (model.TargetSelection, bool, error) {
	var found *model.TargetSelection
	for i := range selection.Targets {
		target := selection.Targets[i]
		if target.TargetID != "blue_reflection_quartet" {
			continue
		}
		integrated := false
		valid := true
		for _, moduleID := range target.SelectedModuleIDs {
			switch moduleID {
			case quartetLegacyDLCModule, quartetRestorationModule, quartetTranslationModule:
				integrated = true
			default:
				valid = false
			}
		}
		if !integrated || !valid {
			continue
		}
		if found != nil {
			return model.TargetSelection{}, false, fmt.Errorf("integrated Quartet content supports one target at a time")
		}
		copyTarget := target
		found = &copyTarget
	}
	if found == nil {
		return model.TargetSelection{}, false, nil
	}
	if len(selection.Targets) != 1 {
		return model.TargetSelection{}, false, fmt.Errorf("integrated Quartet content must be run for the Quartet installation separately")
	}
	return *found, true, nil
}

func runQuartetContentGuided(selection model.SelectionResult, opts legacyContentStartOptions, out io.Writer) (legacyContentResult, error) {
	target, requested, err := selectionUsesIntegratedQuartetContent(selection)
	if err != nil || !requested {
		return legacyContentResult{}, err
	}
	legacySelected := contains(target.SelectedModuleIDs, quartetLegacyDLCModule)
	restorationSelected := contains(target.SelectedModuleIDs, quartetRestorationModule)
	translationSelected := contains(target.SelectedModuleIDs, quartetTranslationModule)
	source := br1rebuild.SourceLocator{
		AssetRoot:  opts.AssetRoot,
		AnchorPath: legacyAssetAnchorPath(opts.ProjectRoot),
		LooseRoot:  opts.SourceRoot,
		SteamRoot:  opts.SteamRoot,
		AutoSteam:  !opts.DisableAutoSource,
	}
	simplified := strings.ToLower(strings.TrimSpace(opts.SimplifiedLabels))
	if simplified == "" {
		simplified = "blank"
	}
	if simplified != "blank" && simplified != "hant" {
		return legacyContentResult{}, fmt.Errorf("--legacy-sc-labels must be blank or hant")
	}
	surveyOptions := br1rebuild.SurveyOptions{TargetRoot: target.Root, UseHantForHans: simplified == "hant", RequireFreeSpace: true}
	result := legacyContentResult{Status: "ready", GameModified: false}
	stateBase, err := stateRoot()
	if err != nil {
		return result, err
	}
	stateDir := installationStateDirectory(stateBase, target.TargetID, target.Root)
	managedBaselineSources, activeManaged, err := activeManagedBaselineBuildSources(stateDir, target.TargetID, target.Root)
	if err != nil {
		return result, fmt.Errorf("resolve managed update baseline: %w", err)
	}
	if activeManaged {
		surveyOptions.TargetFileOverrides = managedBaselineSources
		fmt.Fprintf(out, "\n%sManaged update:%s rebuilding selected modules from the preserved pre-install baseline; the currently installed modded archives are not reused as clean inputs.\n", ansiCyan+ansiBold, ansiReset)
	}
	if legacySelected {
		if strings.TrimSpace(source.AssetRoot) == "" && strings.TrimSpace(source.LooseRoot) == "" && strings.TrimSpace(source.SteamRoot) == "" {
			if nearby, found, findErr := findNearbyLegacyAssetBundle(opts.ReleaseRoot, opts.ProjectRoot, source.AnchorPath); findErr != nil {
				return legacyContentResult{}, findErr
			} else if found {
				source.AssetRoot = nearby
				source.AutoSteam = false
				fmt.Fprintf(out, "\n%s%sCompatible BR1 source bundle detected beside the patcher:%s %s\n", ansiBold, ansiCyan, ansiReset, filepath.Base(nearby))
			}
		}
		if opts.Prompt && strings.TrimSpace(source.AssetRoot) == "" && strings.TrimSpace(source.LooseRoot) == "" && strings.TrimSpace(source.SteamRoot) == "" && !opts.DisableAutoSource {
			source, err = chooseLegacySourceLocation(os.Stdin, os.Stdout)
			if err != nil {
				return legacyContentResult{}, err
			}
		}
		var sourceRenderer *br1BuildProgressRenderer
		if strings.TrimSpace(source.AssetRoot) != "" {
			sourceRenderer = newBR1BuildProgressRenderer(out)
			defer sourceRenderer.Finish()
			sourceRenderer.Status("source_bundle_manifest", "Opening and validating BR1 source bundle metadata")
			source.Progress = sourceRenderer.Callback
		}
		surveyOptions.SourceLocator = source
		survey, err := br1rebuild.SurveyInstallPair(surveyOptions)
		if sourceRenderer != nil {
			sourceRenderer.Finish()
		}
		if err != nil {
			return legacyContentResult{}, err
		}
		if survey.Source.CleanupRoot != "" {
			defer os.RemoveAll(survey.Source.CleanupRoot)
			// Reuse the already verified temporary source image for the build so the
			// .unburger-assets payload is materialized exactly once per run.
			surveyOptions.SourceLocator = br1rebuild.SourceLocator{LooseRoot: survey.Source.Root}
		}
		printLegacyContentSurvey(out, survey)
		result.Survey = survey
		result.Status = survey.Status
		if !survey.Ready {
			return result, fmt.Errorf("BLUE REFLECTION legacy content survey is blocked")
		}
	}

	action := guidedActionCancel
	switch {
	case opts.Prepare:
		action = guidedActionPrepare
	case opts.Install:
		if !opts.Confirmed {
			return result, fmt.Errorf("non-interactive --install modifies game files; pass --yes or use the interactive action menu")
		}
		action = guidedActionInstall
	case opts.Prompt:
		action, err = chooseQuartetContentAction(target, os.Stdin, os.Stdout)
		if err != nil {
			return result, err
		}
	default:
		result.Status = "ready_for_quartet_content_build"
		return result, nil
	}
	if action == guidedActionCancel {
		result.Status = "survey_complete_no_changes"
		fmt.Fprintln(out, "No game files were modified.")
		return result, nil
	}

	projectRoot := strings.TrimSpace(opts.ProjectRoot)
	if translationSelected {
		if opts.BuildLocal {
			if _, err := runLocalTranslationPreviewBuild(projectRoot, selection, out); err != nil {
				return result, err
			}
		}
		projectRoot, err = resolveTranslationContentRoot(projectRoot)
		if err != nil {
			return result, err
		}
	}

	textCodec := br1rebuild.EncryptedTextTool{}
	surveyOptions.TextTool = textCodec

	workspace, cleanupWorkspace, err := newPublicWorkRootWithStatus(stateDir, "unburger-quartet-build-", func(message string) {
		fmt.Fprintf(out, "%sStorage:%s %s\n", ansiGray, ansiReset, message)
	})
	if err != nil {
		return result, err
	}
	defer cleanupWorkspace()
	renderer := newBR1BuildProgressRenderer(out)
	defer renderer.Finish()
	build := br1rebuild.ReconstructionBuildReport{Status: "not_requested", GameModified: false}
	candidates := map[string]string{}
	for relative, path := range managedBaselineSources {
		candidates[filepath.ToSlash(relative)] = path
	}
	if legacySelected {
		fmt.Fprintf(out, "\n%s%sBuilding verified BLUE REFLECTION legacy content set%s\n", ansiBold, ansiCyan, ansiReset)
		fmt.Fprintf(out, "%sWorkspace:%s %s\n", ansiGray, ansiReset, workspace)
		renderer.Status("legacy_source", "Reading verified BLUE REFLECTION source and Quartet target archives")
		build, err = br1rebuild.BuildCandidateSet(br1rebuild.ReconstructionBuildOptions{
			Survey: surveyOptions, StateRoot: stateDir, Workspace: workspace, PreserveWorkspace: true,
		}, renderer.Callback)
		renderer.Finish()
		if err != nil {
			return result, err
		}
		result.Build = build
		for _, artifact := range build.Candidates {
			candidates[filepath.ToSlash(artifact.RelativePath)] = artifact.Path
		}
	}
	overlayDir := filepath.Join(workspace, "composed")
	if restorationSelected {
		if _, exists := candidates["Data/PACK10_03.PAK"]; !exists {
			candidates["Data/PACK10_03.PAK"] = filepath.Join(target.Root, "Data", "PACK10_03.PAK")
		}
	}
	if restorationSelected {
		renderer.Status("restoration_build", "Composing approved UNCENSOR restoration layer")
		audit, updated, err := br1rebuild.ApplyApprovedRestoration(overlayDir, candidates, renderer.Callback)
		renderer.Finish()
		if err != nil {
			return result, err
		}
		candidates = updated
		result.Restoration = &audit
	}
	if translationSelected {
		renderer.Status("translation_build", "Composing verified Translation layer")
		bundlePath := filepath.Join(projectRoot, "content", "translation", "records.v1.json")
		if _, statErr := os.Stat(bundlePath); statErr == nil {
			bundle, loadErr := translationbundle.Load(bundlePath)
			if loadErr != nil {
				return result, loadErr
			}
			audit, updated, applyErr := translationbundle.ApplyInstallation(bundle, target.TargetID, target.Root, overlayDir, candidates, textCodec, renderer.Callback)
			renderer.Finish()
			if applyErr != nil {
				return result, applyErr
			}
			candidates = updated
			result.TranslationRecords = &audit
		} else {
			looseReport := filepath.Join(projectRoot, ".local", "reports", "translation", "BR_TRANSLATION_LOOSE_BUILD_REPORT.json")
			translationArchives, err := br1rebuild.TranslationChangedArchives(projectRoot, looseReport)
			if err != nil {
				return result, err
			}
			for _, relative := range translationArchives {
				if _, exists := candidates[relative]; !exists {
					path := filepath.Join(target.Root, filepath.FromSlash(relative))
					if info, statErr := os.Stat(path); statErr != nil || !info.Mode().IsRegular() {
						return result, fmt.Errorf("Translation baseline archive missing: %s", relative)
					}
					candidates[relative] = path
				}
			}
			audit, updated, err := br1rebuild.ApplyTranslationLast(projectRoot, looseReport, overlayDir, candidates, textCodec, renderer.Callback)
			renderer.Finish()
			if err != nil {
				return result, err
			}
			candidates = updated
			result.Translation = &audit
		}
	}

	if legacySelected {
		renderer.Status("final_audit", "Cross-checking wardrobe, module and archive invariants")
		_, targetFiles := br1rebuild.ResolveContentFilesWithTargetOverrides(result.Survey.Source.Root, target.Root, surveyOptions.TargetFileOverrides)
		wardrobePlan, err := br1rebuild.DeriveWardrobePlanWithTargetFiles(result.Survey.Source.Root, target.Root, targetFiles)
		if err != nil {
			return result, err
		}
		finalAudit, err := br1rebuild.AuditCrossFileWardrobe(candidates["B1.dll"], candidates["Data/PACK10_02.PAK"], candidates["Data/PACK12.PAK"], wardrobePlan, textCodec)
		if err != nil {
			return result, fmt.Errorf("final integrated content audit: %w", err)
		}
		result.FinalAudit = &finalAudit
		renderer.Finish()
	}

	markerLabels, markerLabelsErr := selectedVersionedContentIndicators(projectRoot, target.TargetID, target.SelectedModuleIDs)
	if markerLabelsErr != nil {
		return result, markerLabelsErr
	}
	if len(markerLabels) > 0 {
		markerRelative := "Data/PACK00_04_01.PAK"
		markerSource := candidates[markerRelative]
		if strings.TrimSpace(markerSource) == "" {
			markerSource = filepath.Join(target.Root, "Data", "PACK00_04_01.PAK")
		}
		renderer.Status("title_marker", "Overlaying selected UNBURGER indicators while preserving unrelated Quartet launcher UI")
		markerAudit, markerOutput, markerErr := br1rebuild.ApplyQuartetTitleMarker(filepath.Join(overlayDir, "title-marker"), markerSource, strings.Join(markerLabels, " / "), renderer.Callback)
		renderer.Finish()
		if markerErr != nil {
			return result, markerErr
		}
		candidates[markerRelative] = markerOutput
		result.TitleMarker = &markerAudit
	}

	finalArtifacts := make([]br1rebuild.OutputArtifact, 0, len(candidates)+2)
	keys := make([]string, 0, len(candidates))
	for relative := range candidates {
		keys = append(keys, relative)
	}
	sort.Strings(keys)
	for _, relative := range keys {
		finalArtifacts = append(finalArtifacts, br1rebuild.OutputArtifact{RelativePath: relative, Path: candidates[relative]})
	}
	if translationSelected && result.TranslationRecords != nil {
		finalArtifacts, err = appendTranslationManagedStateArtifact(target.TargetID, overlayDir, *result.TranslationRecords, finalArtifacts)
		if err != nil {
			return result, err
		}
	}
	if translationSelected {
		bundlePath := filepath.Join(projectRoot, "content", "translation", "records.v1.json")
		if _, statErr := os.Stat(bundlePath); os.IsNotExist(statErr) {
			excluded := map[string]bool{}
			for relative := range candidates {
				excluded[filepath.ToSlash(relative)] = true
			}
			extras, err := br1rebuild.TranslationStandaloneArtifacts(projectRoot, filepath.Join(projectRoot, ".local", "reports", "translation", "BR_TRANSLATION_PAK_REPACK_REPORT.json"), target.Root, overlayDir, excluded, renderer.Callback)
			if err != nil {
				return result, err
			}
			finalArtifacts = append(finalArtifacts, extras...)
		}
	}

	metadata := map[string]string{
		"target_id":         target.TargetID,
		"purpose":           "br1_legacy_content",
		"capability":        "br1_legacy_content_rebuild_v1",
		"source_origin":     result.Survey.Source.Origin,
		"composition_order": "legacy_content,restoration,translation",
	}
	prepProgress := newTransactionProgressRenderer(out)
	prepProgress.Status("prepare", "baseline", "Hashing final artifacts and preserving one game-side rollback baseline")
	journal, baselineManifest, err := br1rebuild.PrepareArtifactsForTargetWithProgress(target.Root, stateDir, target.TargetID, finalArtifacts, target.SelectedModuleIDs, metadata, prepProgress.Callback)
	prepProgress.Finish()
	if err != nil {
		return result, err
	}
	result.JournalPath = journal
	result.Build.JournalPath = journal
	result.Build.BaselineManifest = baselineManifest
	result.Status = "prepared"
	result.GameModified = false
	loaded, err := loadTransactionJournal(journal)
	if err == nil {
		result.TransactionID = loaded.TransactionID
		result.Build.TransactionID = loaded.TransactionID
	}
	fmt.Fprintf(out, "\nPrepared one all-or-none transaction.\nJournal: %s\n", journal)
	if action == guidedActionPrepare {
		return result, nil
	}

	txProgress := newTransactionProgressRenderer(out)
	committed, err := commitPreparedTransactionWithProgress(journal, txProgress.Callback)
	txProgress.Finish()
	if err != nil {
		return result, err
	}
	printHumanTransactionCommit(out, committed)
	result.Status = "installed"
	result.GameModified = true
	saveAccessStatus := "not_required"
	if legacySelected {
		saveAccessStatus = "not_updated"
	}

	if legacySelected && (opts.SyncSaves || (opts.Prompt && chooseLegacySaveSync(os.Stdin, os.Stdout))) {
		selection, selectErr := chooseQuartetSaveSelection(opts.SaveRoot, target.Root, opts.Prompt, os.Stdin, os.Stdout)
		if selectErr != nil {
			if selectErr == errQuartetSaveAccessCancelled {
				fmt.Fprintln(out, "Save access update skipped. Game files remain installed; run save-access later after choosing the save folder or Wine/Proton prefix.")
				printQuartetWorkflowComplete(out, target.SelectedModuleIDs, "skipped")
				return result, nil
			}
			return result, selectErr
		}
		dllPath := filepath.Join(target.Root, "B1.dll")
		preview, previewErr := previewQuartetSaveAccess(selection, dllPath, false)
		if previewErr != nil {
			return result, previewErr
		}
		changes := 0
		for _, saveReport := range preview {
			if reportNeedsSaveWrite(saveReport) {
				changes++
			}
		}
		fmt.Fprintf(out, "Save access: %d save(s) selected; %d need restored costume/Tropical Island flags.\n", len(preview), changes)
		if changes > 0 {
			if _, applyErr := applyQuartetSaveAccess(selection, dllPath, false, out); applyErr != nil {
				return result, applyErr
			}
			saveAccessStatus = "updated"
		} else {
			fmt.Fprintln(out, "Selected saves are already current.")
			saveAccessStatus = "already_current"
		}
		fmt.Fprintln(out, "Run save-access again after creating a new playthrough/save.")
	}
	printQuartetWorkflowComplete(out, target.SelectedModuleIDs, saveAccessStatus)
	return result, nil
}

func printQuartetWorkflowComplete(out io.Writer, modules []string, saveAccessStatus string) {
	labels := selectedContentIndicators("blue_reflection_quartet", modules)
	moduleText := strings.Join(labels, " / ")
	if moduleText == "" {
		moduleText = "No modules selected"
	}
	saveText := "Not required"
	saveStyle := ansiGreen
	readyText := "The game is ready to play."
	switch saveAccessStatus {
	case "updated":
		saveText = "Updated and verified"
	case "already_current":
		saveText = "Already current"
	case "skipped", "not_updated":
		saveText = "Not updated — restored DLC may remain locked in existing/new saves"
		saveStyle = ansiYellow
		readyText = "Game files are ready; run Save Access when you want restored DLC unlocks in that save."
	}
	line := strings.Repeat("─", 84)
	fmt.Fprintf(out, "\n%s╭─ UNBURGER · COMPLETE %s%s\n", ansiCyan+ansiBold, strings.Repeat("─", 62), ansiReset)
	fmt.Fprintf(out, "%s│%s %s✓%s Game files installed and verified\n", ansiCyan, ansiReset, ansiGreen, ansiReset)
	fmt.Fprintf(out, "%s│%s %s✓%s Modules: %s\n", ansiCyan, ansiReset, ansiGreen, ansiReset, moduleText)
	fmt.Fprintf(out, "%s│%s %s●%s Save Access: %s\n", ansiCyan, ansiReset, saveStyle, ansiReset, saveText)
	fmt.Fprintf(out, "%s│%s %s%s%s\n", ansiCyan, ansiReset, ansiBold, readyText, ansiReset)
	fmt.Fprintf(out, "%s╰%s╯%s\n", ansiCyan, line, ansiReset)
}

func legacyAssetAnchorPath(projectRoot string) string {
	candidates := []string{
		filepath.Join(projectRoot, "contracts", "BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"),
		filepath.Join(projectRoot, "workstreams", "core", "contracts", "release", "BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"),
	}
	for _, candidate := range candidates {
		if info, err := os.Stat(candidate); err == nil && !info.IsDir() {
			return candidate
		}
	}
	return candidates[0]
}

func resolveTranslationContentRoot(explicit string) (string, error) {
	candidates := []string{}
	if strings.TrimSpace(explicit) != "" {
		candidates = append(candidates, explicit)
	}
	if env := strings.TrimSpace(os.Getenv("BR_PROJECT_ROOT")); env != "" {
		candidates = append(candidates, env)
	}
	if exe, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Dir(exe))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, cwd)
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
				releaseBundle := filepath.Join(current, "content", "translation", "records.v1.json")
				if info, statErr := os.Stat(releaseBundle); statErr == nil && info.Mode().IsRegular() {
					return current, nil
				}
				needed := []string{
					"workstreams/translation/VERSION",
					"workstreams/translation_tooling/VERSION",
					".local/reports/translation/BR_TRANSLATION_LOOSE_BUILD_REPORT.json",
					".local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json",
				}
				ok := true
				for _, relative := range needed {
					if info, statErr := os.Stat(filepath.Join(current, filepath.FromSlash(relative))); statErr != nil || !info.Mode().IsRegular() {
						ok = false
						break
					}
				}
				if ok {
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
	return "", fmt.Errorf("verified Translation content was not found; pass --project-root PATH")
}

func activeManagedBaselineBuildSources(stateDir, targetID, gameRoot string) (map[string]string, bool, error) {
	active, exists, err := installstate.Load(stateDir, targetID, gameRoot)
	if err != nil {
		return nil, false, err
	}
	if !exists {
		return map[string]string{}, false, nil
	}

	// Walk the managed predecessor chain metadata-only. The current transaction's
	// immediate baseline is the state that existed just before that update; after
	// two or more updates it can therefore already contain modded bytes. For every
	// currently managed path we need the earliest baseline record in the chain --
	// the state before that path was first managed -- so candidate composition can
	// never stack a new build on top of an older UNBURGER build.
	states := []installstate.State{active}
	seenStates := map[string]bool{active.TransactionID: true}
	previous := strings.TrimSpace(active.PreviousStatePath)
	stateRoot, err := filepath.Abs(stateDir)
	if err != nil {
		return nil, false, err
	}
	for depth := 0; previous != ""; depth++ {
		if depth >= 1024 {
			return nil, false, fmt.Errorf("active installation history is too deep")
		}
		absolute, err := filepath.Abs(previous)
		if err != nil {
			return nil, false, err
		}
		rel, err := filepath.Rel(stateRoot, absolute)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) || filepath.IsAbs(rel) {
			return nil, false, fmt.Errorf("active installation predecessor is outside its state directory: %s", absolute)
		}
		older, err := installstate.LoadPath(absolute, targetID, gameRoot)
		if err != nil {
			return nil, false, err
		}
		if seenStates[older.TransactionID] {
			return nil, false, fmt.Errorf("active installation history contains a cycle at transaction %s", older.TransactionID)
		}
		seenStates[older.TransactionID] = true
		states = append(states, older)
		previous = strings.TrimSpace(older.PreviousStatePath)
	}

	needed := map[string]string{}
	for _, item := range active.Files {
		relative := filepath.ToSlash(item.RelativePath)
		needed[strings.ToLower(relative)] = relative
	}
	resolved := map[string]bool{}
	result := map[string]string{}

	// states is newest -> oldest; inspect oldest -> newest so the first baseline
	// record seen for a path is its true pre-management source.
	for index := len(states) - 1; index >= 0; index-- {
		state := states[index]
		manifest, stored, err := baseline.LoadStoredPaths(state.BaselineManifestPath)
		if err != nil {
			return nil, false, err
		}
		if manifest.BaselineID != state.BaselineID || manifest.Fingerprint != state.BaselineFingerprint || manifest.TargetID != targetID || filepath.Clean(manifest.GameRoot) != filepath.Clean(gameRoot) {
			return nil, false, fmt.Errorf("managed update baseline identity mismatch for transaction %s", state.TransactionID)
		}
		for _, record := range manifest.Files {
			key := strings.ToLower(filepath.ToSlash(record.RelativePath))
			if _, wanted := needed[key]; !wanted || resolved[key] {
				continue
			}
			resolved[key] = true
			if !record.Existed {
				continue
			}
			path, ok := stored[record.RelativePath]
			if !ok || strings.TrimSpace(path) == "" {
				return nil, false, fmt.Errorf("preserved baseline file is unavailable: %s", needed[key])
			}
			result[needed[key]] = path
		}
	}
	for key, relative := range needed {
		if !resolved[key] {
			return nil, false, fmt.Errorf("active managed path has no preserved pre-management baseline record: %s", relative)
		}
	}
	return result, true, nil
}

func nearbyLegacyAssetSearchRoots(releaseRoot, projectRoot string) []string {
	seen := map[string]bool{}
	var roots []string
	add := func(raw string) {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			return
		}
		abs, err := filepath.Abs(raw)
		if err != nil {
			return
		}
		abs = filepath.Clean(abs)
		if !seen[abs] {
			seen[abs] = true
			roots = append(roots, abs)
		}
	}
	add(releaseRoot)
	// A repository/project-root invocation may intentionally keep a developer
	// source bundle beside BUILD_RELEASE.sh. The public release root is checked
	// first so a sibling bundle wins over this fallback.
	add(projectRoot)
	if executable, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(executable)
		add(exeDir)
		add(filepath.Dir(exeDir))
		add(filepath.Dir(filepath.Dir(exeDir)))
	}
	// Do not search the current/game/Steam directories for developer source
	// bundles. Automatic game discovery and .unburger-assets discovery are
	// intentionally separate: a source bundle must stay beside the patcher
	// release (or an explicit developer project root).
	return roots
}

func findNearbyLegacyAssetBundle(releaseRoot, projectRoot, anchorPath string) (string, bool, error) {
	for _, root := range nearbyLegacyAssetSearchRoots(releaseRoot, projectRoot) {
		if st, err := os.Stat(root); err != nil || !st.IsDir() {
			continue
		}
		bundle, found, err := br1rebuild.FindCompatibleSourceAssetBundle(root, anchorPath)
		if err != nil {
			return "", false, fmt.Errorf("inspect nearby BR1 source bundle in %s: %w", root, err)
		}
		if found {
			return bundle, true, nil
		}
	}
	return "", false, nil
}

func chooseLegacySourceLocation(in io.Reader, out io.Writer) (br1rebuild.SourceLocator, error) {
	choices := []string{
		"Auto-detect from Steam libraries",
		"Use a BLUE REFLECTION (2017) game folder",
		"Use a Steam installation or Steam library folder",
	}
	index, err := chooseSimpleMenu("BLUE REFLECTION (2017) source", choices, in, out)
	if err != nil {
		return br1rebuild.SourceLocator{}, err
	}
	switch index {
	case 0:
		return br1rebuild.SourceLocator{AutoSteam: true}, nil
	case 1:
		value, err := readPathPrompt(in, out, "Game folder: ")
		return br1rebuild.SourceLocator{LooseRoot: value, AutoSteam: false}, err
	case 2:
		value, err := readPathPrompt(in, out, "Steam / library folder: ")
		return br1rebuild.SourceLocator{SteamRoot: value, AutoSteam: false}, err
	default:
		return br1rebuild.SourceLocator{}, fmt.Errorf("invalid source selection")
	}
}

func chooseQuartetContentAction(target model.TargetSelection, in io.Reader, out io.Writer) (guidedPayloadAction, error) {
	choices := []string{"Install / update now", "Prepare only", "Cancel"}
	index, err := chooseSimpleMenu("Legacy content ready for "+target.DisplayName, choices, in, out)
	if err != nil {
		return guidedActionCancel, err
	}
	switch index {
	case 0:
		return guidedActionInstall, nil
	case 1:
		return guidedActionPrepare, nil
	default:
		return guidedActionCancel, nil
	}
}

func chooseSimpleMenu(title string, choices []string, in io.Reader, out io.Writer) (int, error) {
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		restore, err := terminalEnterRawMode(terminalIn, terminalOut)
		if err != nil {
			return 0, err
		}
		defer restore()
		reader := bufio.NewReader(terminalIn)
		cursor := 0
		fmt.Fprint(terminalOut, ansiHideCur)
		defer fmt.Fprint(terminalOut, ansiShowCur, ansiReset)
		for {
			fmt.Fprint(terminalOut, ansiClear)
			fmt.Fprintf(terminalOut, "%s%s%s%s\n\n", ansiBold, ansiCyan, title, ansiReset)
			for i, choice := range choices {
				pointer := "  "
				style := ""
				if i == cursor {
					pointer = "› "
					style = ansiYellow + ansiBold
				}
				fmt.Fprintf(terminalOut, "%s%s%s%s\n", style, pointer, choice, ansiReset)
			}
			key, err := readMenuKey(reader)
			if err != nil {
				return 0, err
			}
			switch key {
			case keyUp:
				cursor = (cursor + len(choices) - 1) % len(choices)
			case keyDown:
				cursor = (cursor + 1) % len(choices)
			case keyEnter, keyToggle:
				fmt.Fprint(terminalOut, ansiClear)
				return cursor, nil
			case keyCancel:
				return len(choices) - 1, nil
			}
		}
	}
	fmt.Fprintf(out, "\n%s\n", title)
	for i, choice := range choices {
		fmt.Fprintf(out, "  %d) %s\n", i+1, choice)
	}
	fmt.Fprintf(out, "Choose 1-%d: ", len(choices))
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return 0, err
	}
	var index int
	if _, err := fmt.Sscanf(strings.TrimSpace(line), "%d", &index); err != nil || index < 1 || index > len(choices) {
		return 0, fmt.Errorf("invalid selection")
	}
	return index - 1, nil
}

func readPathPrompt(in io.Reader, out io.Writer, label string) (string, error) {
	fmt.Fprint(out, label)
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return "", err
	}
	value := strings.Trim(strings.TrimSpace(line), `"`)
	if value == "" {
		return "", fmt.Errorf("path cannot be empty")
	}
	return value, nil
}

func printLegacyContentSurvey(out io.Writer, report br1rebuild.SurveyReport) {
	statusStyle := ansiGreen + ansiBold
	if !report.Ready {
		statusStyle = ansiYellow + ansiBold
	}
	fmt.Fprintf(out, "\n%s%sBLUE REFLECTION legacy source check%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s%s%s\n", ansiGray, ansiReset, statusStyle, report.Status, ansiReset)
	fmt.Fprintf(out, "%sSource:%s %s %s(%s)%s\n\n", ansiGray, ansiReset, report.Source.Root, ansiDim, report.Source.Origin, ansiReset)
	for _, check := range report.Checks {
		mark, style := "✓", ansiGreen+ansiBold
		if !check.OK {
			mark, style = "!", ansiYellow+ansiBold
		}
		fmt.Fprintf(out, "  %s%s%s  %-34s %s%s%s\n", style, mark, ansiReset, check.Name, ansiDim, check.Detail, ansiReset)
	}
	if report.Wardrobe != nil {
		fmt.Fprintf(out, "\n%sWardrobe:%s source=%d  target=%d  restored=%d  unavailable=%d  final=%d\n", ansiGray, ansiReset, report.Wardrobe.SourceRecords, report.Wardrobe.TargetRecords, report.Wardrobe.ImportableRecords, report.Wardrobe.UnavailableRecords, report.Wardrobe.FinalRecords)
	}
	if report.BinaryLayout != nil {
		fmt.Fprintf(out, "%sB1 module:%s table=%d  bounds=%d  field/party=%d\n", ansiGray, ansiReset, report.BinaryLayout.RosterRefs, report.BinaryLayout.ScopedBounds, report.BinaryLayout.ExtraBounds)
	}
}

type br1BuildProgressRenderer struct {
	out       io.Writer
	terminal  bool
	active    bool
	started   bool
	startedAt time.Time
	lastDraw  time.Time
	lastItem  br1rebuild.BuildProgress
	spinner   int
	stop      chan struct{}
	done      chan struct{}
	mu        sync.Mutex
}

func newBR1BuildProgressRenderer(out io.Writer) *br1BuildProgressRenderer {
	terminal := false
	if file, ok := out.(*os.File); ok {
		if info, err := file.Stat(); err == nil {
			terminal = info.Mode()&os.ModeCharDevice != 0
		}
	}
	if os.Getenv("BRPATCHER_FORCE_PROGRESS_TTY") == "1" {
		terminal = true
	}
	return &br1BuildProgressRenderer{out: out, terminal: terminal}
}

func (r *br1BuildProgressRenderer) Status(phase, detail string) {
	r.Callback(br1rebuild.BuildProgress{Phase: phase, CurrentFile: detail})
}

func (r *br1BuildProgressRenderer) Callback(item br1rebuild.BuildProgress) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ensureActiveLocked()
	r.lastItem = item
	r.renderLocked(false)
}

func (r *br1BuildProgressRenderer) ensureActiveLocked() {
	if r.active {
		return
	}
	r.active = true
	r.started = false
	r.startedAt = time.Now()
	r.lastDraw = time.Time{}
	r.spinner = 0
	r.stop = make(chan struct{})
	r.done = make(chan struct{})
	stop := r.stop
	done := r.done
	go func() {
		ticker := time.NewTicker(800 * time.Millisecond)
		defer ticker.Stop()
		defer close(done)
		for {
			select {
			case <-ticker.C:
				r.mu.Lock()
				if r.active && r.stop == stop {
					r.spinner++
					r.renderLocked(true)
				}
				r.mu.Unlock()
			case <-stop:
				return
			}
		}
	}()
}

func (r *br1BuildProgressRenderer) renderLocked(heartbeat bool) {
	now := time.Now()
	if !r.terminal {
		if heartbeat && !r.lastDraw.IsZero() && now.Sub(r.lastDraw) < 10*time.Second {
			return
		}
		if !heartbeat && !r.lastDraw.IsZero() && now.Sub(r.lastDraw) < 2*time.Second {
			return
		}
		item := r.lastItem
		fmt.Fprintf(r.out, "[%s] %s | overall %s | current %s | %s | elapsed %s\n",
			legacyPhaseLabel(item.Phase), legacyActivityLabel(item.Phase),
			legacyPercentText(item.OverallDone, item.OverallTotal), legacyPercentText(item.CurrentDone, item.CurrentTotal),
			strings.TrimSpace(item.CurrentFile), formatElapsed(now.Sub(r.startedAt)))
		r.lastDraw = now
		return
	}

	item := r.lastItem
	if !r.started {
		fmt.Fprint(r.out, "\n\n\n\n\n\n\n")
		r.started = true
	}
	fmt.Fprint(r.out, "\033[7A")
	line := strings.Repeat("─", 92)
	fmt.Fprintf(r.out, "\r\033[2K%s╭─ UNBURGER · CONTENT BUILD %s%s\n", ansiCyan+ansiBold, strings.Repeat("─", 64), ansiReset)
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s%-76s%s\n", ansiCyan, ansiReset, "Stage", ansiBold, compactLegacyProgress(legacyPhaseLabel(item.Phase), 76), ansiReset)
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s %6s  %s\n", ansiCyan, ansiReset, "Overall", legacyProgressBar(item.OverallDone, item.OverallTotal, 32), legacyPercentText(item.OverallDone, item.OverallTotal), legacyProgressBytes(item.OverallDone, item.OverallTotal))
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s %6s  %s\n", ansiCyan, ansiReset, "Current", legacyProgressBar(item.CurrentDone, item.CurrentTotal, 32), legacyPercentText(item.CurrentDone, item.CurrentTotal), legacyProgressBytes(item.CurrentDone, item.CurrentTotal))
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s\n", ansiCyan, ansiReset, "File", compactLegacyProgress(strings.TrimSpace(item.CurrentFile), 78))
	spin := []string{"◐", "◓", "◑", "◒"}[r.spinner%4]
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s%s%s  %s·%s elapsed %s\n", ansiCyan, ansiReset, "Activity", ansiYellow, spin, ansiReset, legacyActivityLabel(item.Phase), ansiGray, formatElapsed(now.Sub(r.startedAt)))
	fmt.Fprintf(r.out, "\r\033[2K%s╰%s╯%s\n", ansiCyan, line, ansiReset)
	r.lastDraw = now
}

func (r *br1BuildProgressRenderer) Finish() {
	r.mu.Lock()
	if !r.active {
		r.mu.Unlock()
		return
	}
	stop, done := r.stop, r.done
	if r.terminal && r.started {
		r.spinner++
		r.renderLocked(false)
	}
	r.active = false
	r.stop = nil
	r.done = nil
	r.mu.Unlock()
	close(stop)
	<-done
	if r.terminal {
		fmt.Fprintln(r.out)
	}
}

func legacyPhaseLabel(phase string) string {
	switch phase {
	case "build":
		return "Build archive"
	case "verify":
		return "Verify archive"
	case "restoration_build":
		return "Apply UNCENSOR"
	case "restoration_verify":
		return "Verify UNCENSOR"
	case "translation_build":
		return "Apply Translation"
	case "translation_verify":
		return "Verify Translation"
	case "state_recovery":
		return "Recover previous attempt"
	case "final_audit":
		return "Final integrity audit"
	case "prepare_transaction":
		return "Prepare safe installation"
	case "legacy_source":
		return "Read legacy source"
	case "source_bundle_manifest":
		return "Check BR1 source bundle"
	case "source_bundle_extract":
		return "Materialize BR1 source bundle"
	case "source_bundle_verify":
		return "Verify BR1 source members"
	case "title_marker":
		return "Build title-screen marker"
	default:
		if strings.TrimSpace(phase) == "" {
			return "Working"
		}
		return strings.ReplaceAll(phase, "_", " ")
	}
}

func legacyActivityLabel(phase string) string {
	switch phase {
	case "build", "restoration_build", "translation_build":
		return "Writing and repacking archive data"
	case "verify", "restoration_verify", "translation_verify", "final_audit":
		return "Reading and hashing archive data"
	case "state_recovery":
		return "Cleaning a safe incomplete prepare from the previous version"
	case "prepare_transaction":
		return "Capturing rollback state, hashing and staging verified files"
	case "legacy_source":
		return "Reading and validating source/target game archives"
	case "source_bundle_manifest":
		return "Reading bundle metadata and clean-source binding"
	case "source_bundle_extract":
		return "Extracting and SHA-256 checking source images while writing them"
	case "source_bundle_verify":
		return "Checking the approved BR1 members used by the reconstruction"
	case "title_marker":
		return "Replacing the stock KOEI/legal strip with selected module indicators"
	default:
		return "Disk and integrity work in progress"
	}
}

func legacyPercentText(done, total int64) string {
	if total <= 0 {
		return "  --  "
	}
	return fmt.Sprintf("%5.1f%%", progressPercent(done, total))
}

func legacyProgressBar(done, total int64, width int) string {
	if total <= 0 {
		return "[" + strings.Repeat("·", width) + "]"
	}
	return progressBar(progressPercent(done, total), width)
}

func legacyProgressBytes(done, total int64) string {
	if total <= 0 {
		return "size/progress not measurable for this phase"
	}
	return fmt.Sprintf("%s / %s", formatProgressBytes(done), formatProgressBytes(total))
}

func formatElapsed(value time.Duration) string {
	if value < 0 {
		value = 0
	}
	seconds := int(value.Round(time.Second).Seconds())
	return fmt.Sprintf("%02d:%02d", seconds/60, seconds%60)
}

func compactLegacyProgress(value string, width int) string {
	value = strings.TrimSpace(value)
	if len(value) <= width {
		return value
	}
	if width <= 3 {
		return value[:width]
	}
	return "..." + value[len(value)-(width-3):]
}

func chooseLegacySaveSync(in io.Reader, out io.Writer) bool {
	fmt.Fprintln(out, "\nThe game files are installed. Update costume/island access in existing BLUE REFLECTION Quartet saves now?")
	fmt.Fprint(out, "Update saves [y/N]: ")
	line, _ := bufio.NewReader(in).ReadString('\n')
	value := strings.ToLower(strings.TrimSpace(line))
	return value == "y" || value == "yes"
}

func loadTransactionJournal(path string) (struct{ TransactionID string }, error) {
	// The public report needs only the transaction identifier; read the small journal directly.
	data, err := os.ReadFile(path)
	if err != nil {
		return struct{ TransactionID string }{}, err
	}
	marker := `"transaction_id"`
	i := strings.Index(string(data), marker)
	if i < 0 {
		return struct{ TransactionID string }{}, fmt.Errorf("transaction journal has no identifier")
	}
	tail := string(data)[i+len(marker):]
	q1 := strings.Index(tail, `"`)
	if q1 < 0 {
		return struct{ TransactionID string }{}, fmt.Errorf("transaction journal identifier is malformed")
	}
	tail = tail[q1+1:]
	q2 := strings.Index(tail, `"`)
	if q2 < 0 {
		return struct{ TransactionID string }{}, fmt.Errorf("transaction journal identifier is malformed")
	}
	return struct{ TransactionID string }{TransactionID: tail[:q2]}, nil
}
