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
	inspection, err := installstate.Inspect(stateDirectory, detection.TargetID, detection.Root)
	if err != nil {
		return guidedManagementState{}, err
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
	fmt.Fprintf(out, "Status: %s\nModules: %s\n", state.Inspection.Status, strings.Join(state.Inspection.SelectedModules, ", "))
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
	fmt.Fprintf(out, "%s%sBLUE REFLECTION unified patcher%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sManaged installation:%s %s%s%s\n", ansiBold, ansiReset, ansiBold, state.Detection.DisplayName, ansiReset)
	fmt.Fprintf(out, "%sGame directory:%s %s\n", ansiGray, ansiReset, state.Detection.Root)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiGray, ansiReset, state.Inspection.Status)
	fmt.Fprintf(out, "%sModules:%s %s\n\n", ansiGray, ansiReset, strings.Join(state.Inspection.SelectedModules, ", "))
	fmt.Fprintf(out, "%sChoose action%s\n", ansiBold, ansiReset)
	fmt.Fprintf(out, "%s↑/↓ move   Enter confirms   Q cancels%s\n\n", ansiDim, ansiReset)

	labels := []string{"Install / update modules", "Remove all installed modules", "Cancel"}
	descriptions := []string{
		"Continue to module selection, payload verification and the normal explicit install menu.",
		"Roll back every patcher-managed update in reverse order until the preserved baseline is restored.",
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
		fmt.Fprintf(out, "%s%s%s%s%s%s\n", style, pointer, ansiReset, labelStyle, label, ansiReset)
		fmt.Fprintf(out, "     %s%s%s\n\n", ansiDim, descriptions[index], ansiReset)
	}
	fmt.Fprintf(out, "%sRemoval proceeds only while every managed file matches either the recorded installed state or the preserved baseline; external changes are never overwritten.%s\n", ansiDim, ansiReset)
}
