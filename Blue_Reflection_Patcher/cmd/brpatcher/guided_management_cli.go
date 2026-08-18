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
	guidedManagementContinue        guidedManagementAction = "continue"
	guidedManagementCreateDLCAssets guidedManagementAction = "create_dlc_assets"
	guidedManagementRemove          guidedManagementAction = "remove"
	guidedManagementCancel          guidedManagementAction = "cancel"
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
	if !state.Inspection.Active && detection.TargetID != "blue_reflection_quartet" {
		return guidedManagementContinue, state, nil
	}
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		action, err := chooseGuidedInstallationManagementTUI(state, terminalIn, terminalOut)
		return action, state, err
	}
	action, err := chooseGuidedInstallationManagementLine(state, in, out)
	return action, state, err
}

func guidedManagementEntries(state guidedManagementState) []struct {
	label       string
	description string
	action      guidedManagementAction
} {
	entries := []struct {
		label       string
		description string
		action      guidedManagementAction
	}{
		{"Install / update modules", "Continue to module selection. Required safety checks run only when needed.", guidedManagementContinue},
	}
	if state.Detection.TargetID == "blue_reflection_quartet" {
		entries = append(entries, struct {
			label       string
			description string
			action      guidedManagementAction
		}{"Create reusable encrypted DLC source bundle", "Build a local DLC-only .unburger-assets from installed BLUE REFLECTION and Second Light copies. No game files are modified.", guidedManagementCreateDLCAssets})
	}
	if state.Inspection.Active {
		entries = append(entries, struct {
			label       string
			description string
			action      guidedManagementAction
		}{"Remove all installed modules", "Run the hash-guarded rollback. Externally changed files are never overwritten.", guidedManagementRemove})
	}
	entries = append(entries, struct {
		label       string
		description string
		action      guidedManagementAction
	}{"Cancel", "Exit without changing files or state.", guidedManagementCancel})
	return entries
}

func chooseGuidedInstallationManagementLine(state guidedManagementState, in io.Reader, out io.Writer) (guidedManagementAction, error) {
	if state.Inspection.Active {
		fmt.Fprintf(out, "\nManaged installation detected for %s\n", state.Detection.DisplayName)
		fmt.Fprintf(out, "Status: recorded managed installation; file verification runs only for the chosen action\nModules: %s\n", strings.Join(state.Inspection.SelectedModules, ", "))
	} else {
		fmt.Fprintf(out, "\n%s\n", state.Detection.DisplayName)
	}
	entries := guidedManagementEntries(state)
	for i, entry := range entries {
		fmt.Fprintf(out, "  %d) %s\n", i+1, entry.label)
	}
	fmt.Fprintf(out, "Choose 1-%d: ", len(entries))
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return guidedManagementCancel, err
	}
	choice := parseGuidedManagementChoice(line)
	if choice == "" || choice == "q" {
		return guidedManagementCancel, nil
	}
	var index int
	if _, err := fmt.Sscanf(choice, "%d", &index); err != nil || index < 1 || index > len(entries) {
		return guidedManagementCancel, fmt.Errorf("invalid installation-management selection")
	}
	return entries[index-1].action, nil
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
	entries := guidedManagementEntries(state)
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
				cursor = len(entries) - 1
			}
		case keyDown:
			cursor++
			if cursor >= len(entries) {
				cursor = 0
			}
		case keyEnter, keyToggle:
			fmt.Fprint(out, ansiClear)
			return entries[cursor].action, nil
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return guidedManagementCancel, nil
		}
	}
}

func renderGuidedInstallationManagementMenu(out io.Writer, state guidedManagementState, cursor int) {
	fmt.Fprint(out, ansiClear)
	title := "START"
	if state.Inspection.Active {
		title = "MANAGED INSTALLATION"
	}
	renderTUIFrameTop(out, title)
	renderTUIFrameRow(out, "%sGame%s      %s%s%s", ansiGray, ansiReset, ansiBold, state.Detection.DisplayName, ansiReset)
	renderTUIFrameRow(out, "%sDirectory%s %s", ansiGray, ansiReset, state.Detection.Root)
	if state.Inspection.Active {
		renderTUIFrameRow(out, "%sModules%s   %s", ansiGray, ansiReset, strings.Join(state.Inspection.SelectedModules, ", "))
		renderTUIFrameRow(out, "%sStatus%s    managed installation recorded", ansiGray, ansiReset)
		renderTUIFrameRow(out, "%sVerification%s deferred until the selected action; opening this menu does not rehash the game", ansiGray, ansiReset)
	}
	renderTUIFrameRow(out, "%sControls%s  ↑/↓ move · Enter confirms · Q cancels", ansiGray, ansiReset)
	renderTUIFrameBlank(out)
	renderTUIFrameRow(out, "%sChoose action%s", ansiBold, ansiReset)
	renderTUIFrameBlank(out)

	entries := guidedManagementEntries(state)
	for index, entry := range entries {
		pointer := "  "
		style := ""
		if cursor == index {
			pointer = "› "
			style = ansiYellow + ansiBold
		}
		labelStyle := ansiBold
		if entry.action == guidedManagementContinue {
			labelStyle = ansiGreen + ansiBold
		} else if entry.action == guidedManagementRemove {
			labelStyle = ansiYellow + ansiBold
		} else if entry.action == guidedManagementCreateDLCAssets {
			labelStyle = ansiCyan + ansiBold
		}
		renderTUIFrameRow(out, "%s%s%s%s%s%s", style, pointer, ansiReset, labelStyle, entry.label, ansiReset)
		renderTUIFrameRow(out, "    %s%s%s", ansiDim, entry.description, ansiReset)
		renderTUIFrameBlank(out)
	}
	if state.Inspection.Active {
		renderTUIFrameRow(out, "%sRollback verifies the current transaction-owned hash immediately before each restore. Unknown/external changes are never overwritten.%s", ansiDim, ansiReset)
	} else if state.Detection.TargetID == "blue_reflection_quartet" {
		renderTUIFrameRow(out, "%sThe DLC bundle builder is read-only with respect to all games and stores only the reduced, encrypted DLC source set.%s", ansiDim, ansiReset)
	}
	renderTUIFrameBottom(out)
}
