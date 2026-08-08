package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/translationbundle"
)

type legacyContentStartOptions struct {
	ProjectRoot       string
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
		AssetRoot: opts.AssetRoot,
		LooseRoot: opts.SourceRoot,
		SteamRoot: opts.SteamRoot,
		AutoSteam: !opts.DisableAutoSource,
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
	if legacySelected {
		if opts.Prompt && strings.TrimSpace(source.AssetRoot) == "" && strings.TrimSpace(source.LooseRoot) == "" && strings.TrimSpace(source.SteamRoot) == "" && !opts.DisableAutoSource {
			source, err = chooseLegacySourceLocation(os.Stdin, os.Stdout)
			if err != nil {
				return legacyContentResult{}, err
			}
		}
		surveyOptions.SourceLocator = source
		survey, err := br1rebuild.SurveyInstallPair(surveyOptions)
		if err != nil {
			return legacyContentResult{}, err
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

	stateBase, err := stateRoot()
	if err != nil {
		return result, err
	}
	stateDir := installationStateDirectory(stateBase, target.TargetID, target.Root)
	workspace := br1rebuild.DefaultCandidateWorkspace(stateDir)
	if err := os.MkdirAll(workspace, 0o755); err != nil {
		return result, err
	}
	renderer := newBR1BuildProgressRenderer(out)
	build := br1rebuild.ReconstructionBuildReport{Status: "not_requested", GameModified: false}
	candidates := map[string]string{}
	if legacySelected {
		fmt.Fprintf(out, "\nBuilding verified BLUE REFLECTION legacy content set\nWorkspace: %s\n", workspace)
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
		audit, updated, err := br1rebuild.ApplyApprovedRestoration(overlayDir, candidates, renderer.Callback)
		renderer.Finish()
		if err != nil {
			return result, err
		}
		candidates = updated
		result.Restoration = &audit
	}
	if translationSelected {
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
		_, targetFiles := br1rebuild.ResolveContentFiles(result.Survey.Source.Root, target.Root)
		wardrobePlan, err := br1rebuild.DeriveWardrobePlan(result.Survey.Source.Root, target.Root, targetFiles["pack12"])
		if err != nil {
			return result, err
		}
		finalAudit, err := br1rebuild.AuditCrossFileWardrobe(candidates["B1.dll"], candidates["Data/PACK10_02.PAK"], candidates["Data/PACK12.PAK"], wardrobePlan, textCodec)
		if err != nil {
			return result, fmt.Errorf("final integrated content audit: %w", err)
		}
		result.FinalAudit = &finalAudit
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
	journal, baselineManifest, err := br1rebuild.PrepareArtifacts(target.Root, stateDir, finalArtifacts, target.SelectedModuleIDs, metadata)
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

	if legacySelected && (opts.SyncSaves || (opts.Prompt && chooseLegacySaveSync(os.Stdin, os.Stdout))) {
		saveRoot := opts.SaveRoot
		if strings.TrimSpace(saveRoot) == "" && opts.Prompt {
			saveRoot, err = promptLegacySaveRoot(os.Stdin, os.Stdout)
			if err != nil {
				return result, err
			}
		}
		if err := syncLegacySaveAccess(saveRoot, target.Root, candidates["B1.dll"], out); err != nil {
			return result, err
		}
	}
	return result, nil
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
	fmt.Fprintf(out, "\nBLUE REFLECTION legacy content survey\nStatus: %s\nSource: %s (%s)\n", report.Status, report.Source.Root, report.Source.Origin)
	for _, check := range report.Checks {
		mark := "OK"
		if !check.OK {
			mark = "FAIL"
		}
		fmt.Fprintf(out, "  %-4s %-34s %s\n", mark, check.Name, check.Detail)
	}
	if report.Wardrobe != nil {
		fmt.Fprintf(out, "Wardrobe: source=%d target=%d restored=%d unavailable=%d final=%d\n", report.Wardrobe.SourceRecords, report.Wardrobe.TargetRecords, report.Wardrobe.ImportableRecords, report.Wardrobe.UnavailableRecords, report.Wardrobe.FinalRecords)
	}
	if report.BinaryLayout != nil {
		fmt.Fprintf(out, "B1 module: table sites=%d bounded sites=%d field/party sites=%d\n", report.BinaryLayout.RosterRefs, report.BinaryLayout.ScopedBounds, report.BinaryLayout.ExtraBounds)
	}
}

type br1BuildProgressRenderer struct {
	out    io.Writer
	active bool
}

func newBR1BuildProgressRenderer(out io.Writer) *br1BuildProgressRenderer {
	return &br1BuildProgressRenderer{out: out}
}
func (r *br1BuildProgressRenderer) Callback(item br1rebuild.BuildProgress) {
	overall := 0.0
	if item.OverallTotal > 0 {
		overall = 100 * float64(item.OverallDone) / float64(item.OverallTotal)
	}
	current := 0.0
	if item.CurrentTotal > 0 {
		current = 100 * float64(item.CurrentDone) / float64(item.CurrentTotal)
	}
	fmt.Fprintf(r.out, "\rOverall %6.2f%%  Current %6.2f%%  [%s] %-55s", overall, current, item.Phase, compactLegacyProgress(item.CurrentFile, 55))
	r.active = true
}
func (r *br1BuildProgressRenderer) Finish() {
	if r.active {
		fmt.Fprintln(r.out)
		r.active = false
	}
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

func promptLegacySaveRoot(in io.Reader, out io.Writer) (string, error) {
	if local := strings.TrimSpace(os.Getenv("LOCALAPPDATA")); local != "" {
		candidate := filepath.Join(local, "KoeiTecmo", "BLUE REFLECTION Quartet", "BLUE REFLECTION")
		if info, err := os.Stat(candidate); err == nil && info.IsDir() {
			fmt.Fprintf(out, "Detected save folder: %s\n", candidate)
			fmt.Fprint(out, "Use this folder [Y/n]: ")
			line, _ := bufio.NewReader(in).ReadString('\n')
			value := strings.ToLower(strings.TrimSpace(line))
			if value == "" || value == "y" || value == "yes" {
				return candidate, nil
			}
		}
	}
	fmt.Fprintln(out, "Paste the folder containing the Quartet .pcsave files.")
	fmt.Fprint(out, "Save folder: ")
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && strings.TrimSpace(line) == "" {
		return "", err
	}
	value := strings.Trim(strings.TrimSpace(line), `"`)
	if value == "" {
		return "", fmt.Errorf("save folder was not provided")
	}
	return value, nil
}

func syncLegacySaveAccess(explicitRoot, gameRoot, dllPath string, out io.Writer) error {
	root := strings.Trim(strings.TrimSpace(explicitRoot), `"`)
	if root == "" {
		return fmt.Errorf("save synchronization requires --legacy-save-root PATH; game files are already installed and remain rollback-capable")
	}
	root, err := filepath.Abs(root)
	if err != nil {
		return err
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return err
	}
	count := 0
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(strings.ToLower(entry.Name()), ".pcsave") {
			continue
		}
		path := filepath.Join(root, entry.Name())
		report, err := br1rebuild.UpdateSaveAccessState(path, dllPath, false, true)
		if err != nil {
			return fmt.Errorf("update save %s: %w", entry.Name(), err)
		}
		fmt.Fprintf(out, "Save: %s  costume flags=%d  island event=%v  backup=%s\n", entry.Name(), report.WardrobeBytesChanged, report.IslandChanged, report.Backup)
		count++
	}
	if count == 0 {
		return fmt.Errorf("no .pcsave files found in %s", root)
	}
	_ = gameRoot
	return nil
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
