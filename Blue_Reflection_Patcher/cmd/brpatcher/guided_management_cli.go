package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/installstate"
)

type guidedManagementAction string

const (
	guidedManagementContinue guidedManagementAction = "continue"
	guidedManagementRemove   guidedManagementAction = "remove"
	guidedManagementCancel   guidedManagementAction = "cancel"
)

type guidedManagementState struct {
	Detection      model.Detection
	StateDirectory string
	Inspection     installstate.Inspection
}

func inspectGuidedManagement(detection model.Detection) (guidedManagementState, error) {
	base, err := stateRoot()
	if err != nil {
		return guidedManagementState{}, err
	}
	stateDirectory := installationStateDirectory(base, detection.TargetID, detection.Root)
	// Startup management is intentionally metadata-only. A previous version
	// hashed every managed multi-gigabyte file before it could even show the
	// rollback menu. The destructive action itself performs the authoritative
	// hash guard, so that eager full-disk pass added latency without adding a
	// distinct safety boundary.
	active, exists, err := installstate.Load(stateDirectory, detection.TargetID, detection.Root)
	if err != nil {
		return guidedManagementState{}, err
	}
	inspection := installstate.Inspection{Status: installstate.InspectionNotActive, Active: false, Files: []installstate.FileComparison{}, Warnings: []string{}}
	if exists {
		inspection.Active = true
		inspection.Status = "active_recorded_verification_deferred"
		inspection.StatePath = installstate.ActivePath(stateDirectory)
		inspection.TransactionID = active.TransactionID
		inspection.BaselineID = active.BaselineID
		inspection.BaselineManifestPath = active.BaselineManifestPath
		inspection.PreviousStatePath = active.PreviousStatePath
		inspection.SelectedModules = append([]string(nil), active.SelectedModules...)
	}
	return guidedManagementState{Detection: detection, StateDirectory: stateDirectory, Inspection: inspection}, nil
}

func chooseGuidedInstallationManagement(detection model.Detection, in io.Reader, out io.Writer) (guidedManagementAction, guidedManagementState, error) {
	state, err := inspectGuidedManagement(detection)
	if err != nil {
		return guidedManagementCancel, state, err
	}
	if !state.Inspection.Active {
		return guidedManagementContinue, state, nil
	}
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		action, err := chooseGuidedInstallationManagementTUI(state, terminalIn, terminalOut)
		return action, state, err
	}
	action, err := chooseGuidedInstallationManagementLine(state, in, out)
	return action, state, err
}

func chooseGuidedInstallationManagementLine(state guidedManagementState, in io.Reader, out io.Writer) (guidedManagementAction, error) {
	fmt.Fprintf(out, "\nManaged installation detected for %s\n", state.Detection.DisplayName)
	fmt.Fprintf(out, "Status: recorded managed installation; file verification runs only for the chosen action\nModules: %s\n", strings.Join(state.Inspection.SelectedModules, ", "))
	fmt.Fprintln(out, "  1) Continue to install/update modules")
	fmt.Fprintln(out, "  2) Remove all patcher-installed modules")
	fmt.Fprintln(out, "  3) Cancel")
	fmt.Fprint(out, "Choose 1-3: ")
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return guidedManagementCancel, err
	}
	switch parseGuidedManagementChoice(line) {
	case "1":
		return guidedManagementContinue, nil
	case "2":
		return guidedManagementRemove, nil
	case "", "3", "q":
		return guidedManagementCancel, nil
	default:
		return guidedManagementCancel, fmt.Errorf("invalid installation-management selection")
	}
}

func chooseGuidedInstallationManagementTUI(state guidedManagementState, in *os.File, out *os.File) (guidedManagementAction, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return guidedManagementCancel, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)
	reader := bufio.NewReader(in)
	cursor := 0
	fmt.Fprint(out, ansiHideCur)
	for {
		renderGuidedInstallationManagementMenu(out, state, cursor)
		key, err := readMenuKey(reader)
		if err != nil {
			return guidedManagementCancel, err
		}
		switch key {
		case keyUp:
			cursor--
			if cursor < 0 {
				cursor = 2
			}
		case keyDown:
			cursor++
			if cursor > 2 {
				cursor = 0
			}
		case keyEnter, keyToggle:
			fmt.Fprint(out, ansiClear)
			switch cursor {
			case 0:
				return guidedManagementContinue, nil
			case 1:
				return guidedManagementRemove, nil
			default:
				return guidedManagementCancel, nil
			}
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return guidedManagementCancel, nil
		}
	}
}

func renderGuidedInstallationManagementMenu(out io.Writer, state guidedManagementState, cursor int) {
	fmt.Fprint(out, ansiClear)
	renderTUIFrameTop(out, "MANAGED INSTALLATION")
	renderTUIFrameRow(out, "%sGame%s      %s%s%s", ansiGray, ansiReset, ansiBold, state.Detection.DisplayName, ansiReset)
	renderTUIFrameRow(out, "%sDirectory%s %s", ansiGray, ansiReset, state.Detection.Root)
	renderTUIFrameRow(out, "%sModules%s   %s", ansiGray, ansiReset, strings.Join(state.Inspection.SelectedModules, ", "))
	renderTUIFrameRow(out, "%sStatus%s    managed installation recorded", ansiGray, ansiReset)
	renderTUIFrameRow(out, "%sVerification%s deferred until the selected action; opening this menu does not rehash the game", ansiGray, ansiReset)
	renderTUIFrameRow(out, "%sControls%s  ↑/↓ move · Enter confirms · Q cancels", ansiGray, ansiReset)
	renderTUIFrameBlank(out)
	renderTUIFrameRow(out, "%sChoose action%s", ansiBold, ansiReset)
	renderTUIFrameBlank(out)

	labels := []string{"Install / update modules", "Remove all installed modules", "Cancel"}
	descriptions := []string{
		"Continue to module selection. Required safety checks run with visible progress only when they are actually needed.",
		"Run the hash-guarded rollback directly. It will refuse externally changed files before overwriting them.",
		"Exit without changing files or state.",
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
		} else if index == 1 {
			labelStyle = ansiYellow + ansiBold
		}
		renderTUIFrameRow(out, "%s%s%s%s%s%s", style, pointer, ansiReset, labelStyle, label, ansiReset)
		renderTUIFrameRow(out, "    %s%s%s", ansiDim, descriptions[index], ansiReset)
		renderTUIFrameBlank(out)
	}
	renderTUIFrameRow(out, "%sRollback verifies the current transaction-owned hash immediately before each restore. Unknown/external changes are never overwritten.%s", ansiDim, ansiReset)
	renderTUIFrameBottom(out)
}
