package main

import (
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

type recordTranslationResult struct {
	Translation   translationbundle.ApplyAudit `json:"translation"`
	JournalPath   string                       `json:"journal_path,omitempty"`
	TransactionID string                       `json:"transaction_id,omitempty"`
	Status        string                       `json:"status"`
	GameModified  bool                         `json:"game_modified"`
}

func selectionUsesRecordTranslation(selection model.SelectionResult) (model.TargetSelection, bool, error) {
	if len(selection.Targets) != 1 {
		return model.TargetSelection{}, false, nil
	}
	target := selection.Targets[0]
	var required string
	switch target.TargetID {
	case "blue_reflection_original":
		required = "blue_reflection_translation"
	case "second_light_original":
		required = "second_light_translation"
	default:
		return model.TargetSelection{}, false, nil
	}
	if len(target.SelectedModuleIDs) != 1 || target.SelectedModuleIDs[0] != required {
		return model.TargetSelection{}, false, nil
	}
	return target, true, nil
}

func recordTranslationBundleRoot(explicit string) (string, bool) {
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
	for _, raw := range candidates {
		abs, err := filepath.Abs(raw)
		if err != nil {
			continue
		}
		for current := filepath.Clean(abs); ; current = filepath.Dir(current) {
			if !seen[current] {
				seen[current] = true
				p := filepath.Join(current, "content", "translation", "records.v1.json")
				if info, err := os.Stat(p); err == nil && info.Mode().IsRegular() {
					return current, true
				}
			}
			parent := filepath.Dir(current)
			if parent == current {
				break
			}
		}
	}
	return "", false
}

func chooseRecordTranslationAction(target model.TargetSelection, in io.Reader, out io.Writer) (guidedPayloadAction, error) {
	choices := []string{"Install / update now", "Prepare only", "Cancel"}
	idx, err := chooseSimpleMenu("Translation ready for "+target.DisplayName, choices, in, out)
	if err != nil {
		return guidedActionCancel, err
	}
	switch idx {
	case 0:
		return guidedActionInstall, nil
	case 1:
		return guidedActionPrepare, nil
	default:
		return guidedActionCancel, nil
	}
}

func runRecordTranslationGuided(selection model.SelectionResult, projectRoot string, prepare, install, confirmed, prompt bool, out io.Writer) (recordTranslationResult, error) {
	target, requested, err := selectionUsesRecordTranslation(selection)
	if err != nil || !requested {
		return recordTranslationResult{}, err
	}
	root, ok := recordTranslationBundleRoot(projectRoot)
	if !ok {
		return recordTranslationResult{}, fmt.Errorf("release Translation record bundle was not found")
	}
	bundle, err := translationbundle.Load(filepath.Join(root, "content", "translation", "records.v1.json"))
	if err != nil {
		return recordTranslationResult{}, err
	}
	action := guidedActionCancel
	switch {
	case prepare:
		action = guidedActionPrepare
	case install:
		if !confirmed {
			return recordTranslationResult{}, fmt.Errorf("non-interactive --install modifies game files; pass --yes")
		}
		action = guidedActionInstall
	case prompt:
		action, err = chooseRecordTranslationAction(target, os.Stdin, os.Stdout)
		if err != nil {
			return recordTranslationResult{}, err
		}
	default:
		return recordTranslationResult{Status: "ready_for_translation_build"}, nil
	}
	if action == guidedActionCancel {
		return recordTranslationResult{Status: "no_changes"}, nil
	}

	stateBase, err := stateRoot()
	if err != nil {
		return recordTranslationResult{}, err
	}
	stateDir := installationStateDirectory(stateBase, target.TargetID, target.Root)
	workDir, cleanupWorkspace, err := newPublicWorkRootWithStatus(stateDir, "unburger-translation-build-", func(message string) {
		fmt.Fprintf(out, "%sStorage:%s %s\n", ansiGray, ansiReset, message)
	})
	if err != nil {
		return recordTranslationResult{}, err
	}
	defer cleanupWorkspace()
	renderer := newBR1BuildProgressRenderer(out)
	audit, candidates, err := translationbundle.ApplyInstallation(bundle, target.TargetID, target.Root, workDir, map[string]string{}, br1rebuild.EncryptedTextTool{}, renderer.Callback)
	renderer.Finish()
	if err != nil {
		return recordTranslationResult{}, err
	}
	keys := make([]string, 0, len(candidates))
	for rel := range candidates {
		keys = append(keys, rel)
	}
	sort.Strings(keys)
	artifacts := make([]br1rebuild.OutputArtifact, 0, len(keys)+1)
	for _, rel := range keys {
		artifacts = append(artifacts, br1rebuild.OutputArtifact{RelativePath: rel, Path: candidates[rel]})
	}
	artifacts, err = appendTranslationManagedStateArtifact(target.TargetID, workDir, audit, artifacts)
	if err != nil {
		return recordTranslationResult{}, err
	}
	metadata := map[string]string{"target_id": target.TargetID, "purpose": "translation_records", "translation_version": bundle.TranslationVersion}
	prepRenderer := newTransactionProgressRenderer(out)
	prepRenderer.Status("prepare", "baseline", "Hashing final Translation artifacts and preserving the rollback baseline")
	journal, _, err := br1rebuild.PrepareArtifactsForTargetWithProgress(target.Root, stateDir, target.TargetID, artifacts, target.SelectedModuleIDs, metadata, prepRenderer.Callback)
	prepRenderer.Finish()
	if err != nil {
		return recordTranslationResult{}, err
	}
	result := recordTranslationResult{Translation: audit, JournalPath: journal, Status: "prepared", GameModified: false}
	if loaded, loadErr := loadTransactionJournal(journal); loadErr == nil {
		result.TransactionID = loaded.TransactionID
	}
	fmt.Fprintf(out, "\nPrepared Translation transaction.\nJournal: %s\n", journal)
	if action == guidedActionPrepare {
		return result, nil
	}
	commitRenderer := newTransactionProgressRenderer(out)
	committed, err := commitPreparedTransactionWithProgress(journal, commitRenderer.Callback)
	commitRenderer.Finish()
	if err != nil {
		return result, err
	}
	printHumanTransactionCommit(out, committed)
	result.Status = "installed"
	result.GameModified = true
	return result, nil
}
