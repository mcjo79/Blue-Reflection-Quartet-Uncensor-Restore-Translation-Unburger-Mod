package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

type guidedPayloadAction string

const (
	guidedActionCancel  guidedPayloadAction = "cancel"
	guidedActionPrepare guidedPayloadAction = "prepare"
	guidedActionInstall guidedPayloadAction = "install"
)

type guidedPayloadResult struct {
	Action        guidedPayloadAction
	PrepareReport transactionPrepareReport
	CommitReport  transactionCommitReport
}

var prepareGuidedPayloadTransaction = prepareRevalidatedPayloadTransaction

func previewReadyForGuidedAction(preview payloadpreview.Preview) bool {
	return preview.Status == "ready" && len(preview.Targets) == 1 && preview.Targets[0].Status == "ready" && preview.Targets[0].PendingModuleCount == 0 && len(preview.Targets[0].SelectedModules) > 0
}

func previewActionCounts(preview payloadpreview.Preview) (changes, noops int) {
	for _, target := range preview.Targets {
		for _, module := range target.Modules {
			for _, artifact := range module.Artifacts {
				switch artifact.DesiredAction {
				case "add", "replace":
					changes++
				case "noop":
					noops++
				}
			}
		}
	}
	return changes, noops
}

func guidedPayloadSourceSummary(preview payloadpreview.Preview) string {
	composition := false
	unique := map[string]bool{}
	for _, target := range preview.Targets {
		for _, module := range target.Modules {
			for _, artifact := range module.Artifacts {
				if artifact.CompositionVerified {
					composition = true
				}
				unique[strings.ToLower(strings.TrimSpace(artifact.RelativePath))] = true
			}
		}
	}
	if composition {
		return fmt.Sprintf("verified shared member-level composition (%d unique game files)", len(unique))
	}
	return fmt.Sprintf("verified module payload set (%d unique game files)", len(unique))
}

func executeGuidedPayloadAction(preview payloadpreview.Preview, action guidedPayloadAction, out io.Writer) (guidedPayloadResult, error) {
	result := guidedPayloadResult{Action: action}
	switch action {
	case guidedActionCancel:
		return result, nil
	case guidedActionPrepare, guidedActionInstall:
		if !previewReadyForGuidedAction(preview) {
			return result, fmt.Errorf("payload set is not ready for guided preparation: %s", describePayloadPreviewReadiness(preview))
		}
		prepared, err := prepareGuidedPayloadTransaction(preview)
		if err != nil {
			return result, err
		}
		result.PrepareReport = prepared
		printHumanTransactionPrepare(out, prepared)
		if action == guidedActionPrepare || prepared.Status == "no_changes" {
			return result, nil
		}
		if prepared.Status != "prepared" || strings.TrimSpace(prepared.JournalPath) == "" {
			return result, fmt.Errorf("guided installation expected a prepared journal, got status=%s", prepared.Status)
		}
		committed, err := commitPreparedTransaction(prepared.JournalPath)
		if err != nil {
			return result, err
		}
		result.CommitReport = committed
		printHumanTransactionCommit(out, committed)
		return result, nil
	default:
		return result, fmt.Errorf("unsupported guided payload action %q", action)
	}
}

func chooseGuidedPayloadAction(preview payloadpreview.Preview, in io.Reader, out io.Writer) (guidedPayloadAction, error) {
	if !previewReadyForGuidedAction(preview) {
		return guidedActionCancel, fmt.Errorf("payload set is not ready: %s", describePayloadPreviewReadiness(preview))
	}
	if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
		return chooseGuidedPayloadActionTUI(preview, terminalIn, terminalOut)
	}
	return chooseGuidedPayloadActionLine(preview, in, out)
}

func chooseGuidedPayloadActionLine(preview payloadpreview.Preview, in io.Reader, out io.Writer) (guidedPayloadAction, error) {
	target := preview.Targets[0]
	changes, noops := previewActionCounts(preview)
	fmt.Fprintf(out, "\nReady for %s\n", target.DisplayName)
	fmt.Fprintf(out, "Game: %s\nModules: %s\nPayload source: %s\nChanges: %d; already current: %d\n", target.GameRoot, strings.Join(target.SelectedModules, ", "), guidedPayloadSourceSummary(preview), changes, noops)
	fmt.Fprintln(out, "  1) Install/update now (revalidates the complete plan, then modifies game files after verified backups)")
	fmt.Fprintln(out, "  2) Prepare only (revalidates the complete plan; does not modify game files)")
	fmt.Fprintln(out, "  3) Cancel")
	fmt.Fprint(out, "Choose 1-3: ")
	line, err := bufio.NewReader(in).ReadString('\n')
	if err != nil && err != io.EOF {
		return guidedActionCancel, err
	}
	switch strings.TrimSpace(line) {
	case "1":
		return guidedActionInstall, nil
	case "2":
		return guidedActionPrepare, nil
	case "", "3", "q", "Q":
		return guidedActionCancel, nil
	default:
		return guidedActionCancel, fmt.Errorf("invalid action selection")
	}
}

func chooseGuidedPayloadActionTUI(preview payloadpreview.Preview, in *os.File, out *os.File) (guidedPayloadAction, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return guidedActionCancel, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)
	reader := bufio.NewReader(in)
	cursor := 0
	fmt.Fprint(out, ansiHideCur)
	for {
		renderGuidedPayloadActionMenu(out, preview, cursor)
		key, err := readMenuKey(reader)
		if err != nil {
			return guidedActionCancel, err
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
				return guidedActionInstall, nil
			case 1:
				return guidedActionPrepare, nil
			default:
				return guidedActionCancel, nil
			}
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return guidedActionCancel, nil
		}
	}
}

func renderGuidedPayloadActionMenu(out io.Writer, preview payloadpreview.Preview, cursor int) {
	target := preview.Targets[0]
	changes, noops := previewActionCounts(preview)
	fmt.Fprint(out, ansiClear)
	fmt.Fprintf(out, "%s%sBLUE REFLECTION unified patcher%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sReady:%s %s%s%s\n", ansiBold, ansiReset, ansiBold, target.DisplayName, ansiReset)
	fmt.Fprintf(out, "%sGame directory:%s %s\n", ansiGray, ansiReset, target.GameRoot)
	fmt.Fprintf(out, "%sModules:%s %s\n", ansiGray, ansiReset, strings.Join(target.SelectedModules, ", "))
	fmt.Fprintf(out, "%sPayload source:%s %s\n", ansiGray, ansiReset, guidedPayloadSourceSummary(preview))
	fmt.Fprintf(out, "%sPlanned changes:%s %d   %sAlready current:%s %d\n\n", ansiGray, ansiReset, changes, ansiGray, ansiReset, noops)
	fmt.Fprintf(out, "%sChoose action%s\n", ansiBold, ansiReset)
	fmt.Fprintf(out, "%s↑/↓ move   Enter confirms   Q cancels%s\n\n", ansiDim, ansiReset)

	labels := []string{
		"Install / update now",
		"Prepare only",
		"Cancel",
	}
	descriptions := []string{
		"Rebuild and compare the canonical preview, revalidate the composition report and current game files, create or reuse the persistent baseline, then atomically install one deduplicated transaction.",
		"Rebuild and compare the canonical preview, then create the verified baseline, staging, backups and one journal while leaving all game files unchanged.",
		"Exit without preparing or modifying anything.",
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
	fmt.Fprintf(out, "%sSelecting Install / update now is the explicit confirmation that game files may be changed. The operation remains hash-guarded and rollback-capable.%s\n", ansiDim, ansiReset)
}
