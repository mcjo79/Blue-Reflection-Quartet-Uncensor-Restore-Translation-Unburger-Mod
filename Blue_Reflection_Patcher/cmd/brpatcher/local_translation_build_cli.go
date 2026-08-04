package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

const localTranslationWorkflowRelative = "workstreams/core/07_prepare_local_translation_payloads.sh"

type localTranslationBuildReport struct {
	Type              string `json:"type"`
	Status            string `json:"status"`
	TargetID          string `json:"target_id"`
	GameRoot          string `json:"game_root"`
	GameFilesModified bool   `json:"game_files_modified"`
}

func selectionSupportsLocalTranslationBuild(selection model.SelectionResult) bool {
	if len(selection.Targets) != 1 {
		return false
	}
	target := selection.Targets[0]
	if len(target.SelectedModuleIDs) == 0 {
		return false
	}
	translation := false
	for _, moduleID := range target.SelectedModuleIDs {
		switch moduleID {
		case "blue_reflection_translation":
			translation = true
		case "quartet_restoration":
			if target.TargetID != "blue_reflection_quartet" {
				return false
			}
		default:
			return false
		}
	}
	return translation
}

func resolveLocalTranslationProjectRoot(explicit string) (string, error) {
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
				if validLocalTranslationProjectRoot(current) {
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
		return "", fmt.Errorf("local Translation build workflow is unavailable under project root: %s", explicit)
	}
	return "", fmt.Errorf("local Translation build workflow was not found; pass --project-root PATH or set BR_PROJECT_ROOT")
}

func validLocalTranslationProjectRoot(root string) bool {
	for _, relative := range []string{
		"workstreams/core/VERSION",
		localTranslationWorkflowRelative,
		"workstreams/core/local_translation_workflow.py",
		"Blue_Reflection_Patcher/go.mod",
	} {
		info, err := os.Stat(filepath.Join(root, filepath.FromSlash(relative)))
		if err != nil || !info.Mode().IsRegular() {
			return false
		}
	}
	return true
}

func localTranslationBuildAvailable(projectRoot string, selection model.SelectionResult) bool {
	if !selectionSupportsLocalTranslationBuild(selection) {
		return false
	}
	_, err := resolveLocalTranslationProjectRoot(projectRoot)
	return err == nil
}

func runLocalTranslationPreviewBuild(projectRoot string, selection model.SelectionResult, out io.Writer) (string, error) {
	if !selectionSupportsLocalTranslationBuild(selection) {
		return "", fmt.Errorf("selected modules are not supported by the local Translation build workflow")
	}
	resolved, err := resolveLocalTranslationProjectRoot(projectRoot)
	if err != nil {
		return "", err
	}
	target := selection.Targets[0]
	workflow := filepath.Join(resolved, filepath.FromSlash(localTranslationWorkflowRelative))
	reportPath := filepath.Join(resolved, ".local", "reports", "core", "BR_LOCAL_TRANSLATION_GUIDED_BUILD_REPORT.json")
	if err := os.MkdirAll(filepath.Dir(reportPath), 0o755); err != nil {
		return "", fmt.Errorf("create local Translation report directory: %w", err)
	}
	command := exec.Command(
		workflow,
		"--game-dir", target.Root,
		"--modules", strings.Join(target.SelectedModuleIDs, ","),
		"--preview-only",
		"--json", reportPath,
	)
	command.Dir = resolved
	command.Env = append(os.Environ(), "BR_PROJECT_ROOT="+resolved)
	command.Stdout = out
	command.Stderr = out
	if err := command.Run(); err != nil {
		return reportPath, fmt.Errorf("local Translation build failed; no game file was modified: %w", err)
	}
	payload, err := os.ReadFile(reportPath)
	if err != nil {
		return reportPath, fmt.Errorf("read local Translation build report: %w", err)
	}
	var report localTranslationBuildReport
	if err := json.Unmarshal(payload, &report); err != nil {
		return reportPath, fmt.Errorf("decode local Translation build report: %w", err)
	}
	if report.Type != "br_local_translation_workflow_report" || report.Status != "ready_preview_only" {
		return reportPath, fmt.Errorf("local Translation build did not publish a ready preview: type=%s status=%s", report.Type, report.Status)
	}
	if report.GameFilesModified {
		return reportPath, fmt.Errorf("local Translation preview workflow unexpectedly reported modified game files")
	}
	if report.TargetID != target.TargetID || !sameLocalFilesystemPath(report.GameRoot, target.Root) {
		return reportPath, fmt.Errorf("local Translation build report target mismatch")
	}
	return reportPath, nil
}

func sameLocalFilesystemPath(left, right string) bool {
	leftAbs, leftErr := filepath.Abs(left)
	rightAbs, rightErr := filepath.Abs(right)
	if leftErr != nil || rightErr != nil {
		return false
	}
	leftAbs = filepath.Clean(leftAbs)
	rightAbs = filepath.Clean(rightAbs)
	if runtime.GOOS == "windows" {
		return strings.EqualFold(leftAbs, rightAbs)
	}
	return leftAbs == rightAbs
}

func chooseLocalTranslationBuild(in io.Reader, out io.Writer) (bool, error) {
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		return chooseLocalTranslationBuildTUI(terminalIn, terminalOut)
	}
	return chooseLocalTranslationBuildLine(in, out)
}

func chooseLocalTranslationBuildLine(in io.Reader, out io.Writer) (bool, error) {
	fmt.Fprintln(out, "\nVerified local Translation payloads are missing or out of date.")
	fmt.Fprintln(out, "  1) Build current payloads and continue")
	fmt.Fprintln(out, "  2) Cancel")
	fmt.Fprint(out, "Choose 1-2: ")
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return false, err
	}
	switch strings.TrimSpace(line) {
	case "1", "y", "Y", "yes", "YES":
		return true, nil
	case "", "2", "n", "N", "no", "NO", "q", "Q":
		return false, nil
	default:
		return false, fmt.Errorf("invalid local build selection")
	}
}

func chooseLocalTranslationBuildTUI(in *os.File, out *os.File) (bool, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return false, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)
	reader := bufio.NewReader(in)
	cursor := 0
	fmt.Fprint(out, ansiHideCur)
	for {
		renderLocalTranslationBuildMenu(out, cursor)
		key, err := readMenuKey(reader)
		if err != nil {
			return false, err
		}
		switch key {
		case keyUp, keyDown:
			if cursor == 0 {
				cursor = 1
			} else {
				cursor = 0
			}
		case keyEnter, keyToggle:
			fmt.Fprint(out, ansiClear)
			return cursor == 0, nil
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return false, nil
		}
	}
}

func renderLocalTranslationBuildMenu(out io.Writer, cursor int) {
	fmt.Fprint(out, ansiClear)
	fmt.Fprintf(out, "%s%sBLUE REFLECTION unified patcher%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sLocal Translation payloads are not ready%s\n", ansiBold, ansiReset)
	fmt.Fprintf(out, "%sThe development workflow can rebuild the selected target from current canonical records, repack it, add the correct title marker and verify it without modifying the game.%s\n\n", ansiDim, ansiReset)
	fmt.Fprintf(out, "%sChoose action%s\n", ansiBold, ansiReset)
	fmt.Fprintf(out, "%s↑/↓ move   Enter confirms   Q cancels%s\n\n", ansiDim, ansiReset)
	labels := []string{"Build current payloads and continue", "Cancel"}
	descriptions := []string{
		"Run the target-aware local build in preview-only mode, then return to the normal install/prepare menu.",
		"Leave the current reports and game files unchanged.",
	}
	for index, label := range labels {
		pointer := "  "
		style := ""
		if cursor == index {
			pointer = "› "
			style = ansiYellow + ansiBold
		}
		labelStyle := ansiBold
		if index == 0 {
			labelStyle = ansiGreen + ansiBold
		}
		fmt.Fprintf(out, "%s%s%s%s%s%s\n", style, pointer, ansiReset, labelStyle, label, ansiReset)
		fmt.Fprintf(out, "     %s%s%s\n\n", ansiDim, descriptions[index], ansiReset)
	}
	fmt.Fprintf(out, "%sThis build step never writes game files. Installation still requires a separate explicit confirmation.%s\n", ansiDim, ansiReset)
}
