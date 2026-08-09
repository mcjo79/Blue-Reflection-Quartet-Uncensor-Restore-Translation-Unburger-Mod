package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"

	"local/blue-reflection-patcher/internal/model"
)

const (
	ansiReset   = "\x1b[0m"
	ansiBold    = "\x1b[1m"
	ansiDim     = "\x1b[2m"
	ansiCyan    = "\x1b[36m"
	ansiGreen   = "\x1b[32m"
	ansiYellow  = "\x1b[33m"
	ansiGray    = "\x1b[90m"
	ansiClear   = "\x1b[2J\x1b[H"
	ansiHideCur = "\x1b[?25l"
	ansiShowCur = "\x1b[?25h"
)

const tuiFrameWidth = 92

func renderTUIFrameTop(out io.Writer, title string) {
	title = strings.ToUpper(strings.TrimSpace(title))
	fill := tuiFrameWidth - len(title) - 5
	if fill < 1 {
		fill = 1
	}
	fmt.Fprintf(out, "%s╭─ UNBURGER · %s %s%s\n", ansiCyan+ansiBold, title, strings.Repeat("─", fill), ansiReset)
}

func renderTUIFrameRow(out io.Writer, format string, args ...any) {
	fmt.Fprintf(out, "%s│%s ", ansiCyan, ansiReset)
	fmt.Fprintf(out, format, args...)
	fmt.Fprintln(out)
}

func renderTUIFrameBlank(out io.Writer) {
	fmt.Fprintf(out, "%s│%s\n", ansiCyan, ansiReset)
}

func renderTUIFrameBottom(out io.Writer) {
	fmt.Fprintf(out, "%s╰%s╯%s\n", ansiCyan, strings.Repeat("─", tuiFrameWidth), ansiReset)
}

type menuKey int

const (
	keyUnknown menuKey = iota
	keyUp
	keyDown
	keyEnter
	keyToggle
	keyCancel
)

func chooseModulesTUI(
	detection model.Detection,
	available []model.BundleModule,
	defaults map[string]bool,
	in *os.File,
	out *os.File,
) ([]string, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return nil, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)

	selected := make(map[string]bool, len(available))
	for _, module := range available {
		selected[module.ModuleID] = defaults[module.ModuleID]
	}
	cursor := 0
	continueIndex := len(available)
	reader := bufio.NewReader(in)
	fmt.Fprint(out, ansiHideCur)

	for {
		renderModuleMenu(out, detection, available, selected, cursor)
		key, err := readMenuKey(reader)
		if err != nil {
			return nil, err
		}
		switch key {
		case keyUp:
			cursor--
			if cursor < 0 {
				cursor = continueIndex
			}
		case keyDown:
			cursor++
			if cursor > continueIndex {
				cursor = 0
			}
		case keyToggle:
			if cursor < len(available) {
				id := available[cursor].ModuleID
				selected[id] = !selected[id]
			}
		case keyEnter:
			if cursor == continueIndex {
				fmt.Fprint(out, ansiClear)
				return selectedModuleIDs(available, selected), nil
			}
			id := available[cursor].ModuleID
			selected[id] = !selected[id]
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return nil, fmt.Errorf("module selection cancelled")
		}
	}
}

func renderModuleMenu(
	out io.Writer,
	detection model.Detection,
	modules []model.BundleModule,
	selected map[string]bool,
	cursor int,
) {
	fmt.Fprint(out, ansiClear)
	renderTUIFrameTop(out, "MODULE SELECTION")
	renderTUIFrameRow(out, "%sGame%s      %s%s%s", ansiGray, ansiReset, ansiBold, detection.DisplayName, ansiReset)
	renderTUIFrameRow(out, "%sDirectory%s %s", ansiGray, ansiReset, detection.Root)
	renderTUIFrameRow(out, "%sControls%s  ↑/↓ move · Enter/Space toggle · Enter on Continue confirms · Q cancels", ansiGray, ansiReset)
	renderTUIFrameBlank(out)
	renderTUIFrameRow(out, "%sChoose modules%s", ansiBold, ansiReset)
	renderTUIFrameBlank(out)

	for index, module := range modules {
		pointer := "  "
		pointerStyle := ""
		if cursor == index {
			pointer = "› "
			pointerStyle = ansiYellow + ansiBold
		}
		box := "[ ]"
		boxStyle := ansiGray
		if selected[module.ModuleID] {
			box = "[✓]"
			boxStyle = ansiGreen + ansiBold
		}
		renderTUIFrameRow(out, "%s%s%s%s%s%s %s%s%s", pointerStyle, pointer, ansiReset, boxStyle, box, ansiReset, ansiBold, module.DisplayName, ansiReset)
		renderTUIFrameRow(out, "    %s%s%s", ansiDim, module.Description, ansiReset)
		if contains(module.DefaultTargets, detection.TargetID) {
			renderTUIFrameRow(out, "    %s(default)%s", ansiGray, ansiReset)
		}
		if len(module.SourceTargets) > 0 {
			renderTUIFrameRow(out, "    %ssource installation selected later: %s%s", ansiGray, strings.Join(module.SourceTargets, ", "), ansiReset)
		}
		renderTUIFrameBlank(out)
	}

	pointer := "  "
	style := ""
	if cursor == len(modules) {
		pointer = "› "
		style = ansiYellow + ansiBold
	}
	renderTUIFrameRow(out, "%s%s%s%s[ Continue ]%s", style, pointer, ansiReset, ansiBold, ansiReset)
	renderTUIFrameBottom(out)
}

func selectedModuleIDs(modules []model.BundleModule, selected map[string]bool) []string {
	result := make([]string, 0, len(modules))
	for _, module := range modules {
		if selected[module.ModuleID] {
			result = append(result, module.ModuleID)
		}
	}
	return result
}

func readMenuKey(reader *bufio.Reader) (menuKey, error) {
	value, err := reader.ReadByte()
	if err != nil {
		return keyUnknown, err
	}
	switch value {
	case '\r', '\n':
		return keyEnter, nil
	case ' ':
		return keyToggle, nil
	case 'q', 'Q':
		return keyCancel, nil
	case 0x1b:
		// Escape on its own cancels. Arrow keys arrive as ESC [ A/B or ESC O A/B.
		second, err := reader.ReadByte()
		if err != nil {
			return keyCancel, nil
		}
		if second != '[' && second != 'O' {
			return keyCancel, nil
		}
		third, err := reader.ReadByte()
		if err != nil {
			return keyUnknown, err
		}
		switch third {
		case 'A':
			return keyUp, nil
		case 'B':
			return keyDown, nil
		default:
			return keyUnknown, nil
		}
	default:
		return keyUnknown, nil
	}
}

func terminalMenuAvailable(in io.Reader, out io.Writer) (*os.File, *os.File, bool) {
	input, inputOK := in.(*os.File)
	output, outputOK := out.(*os.File)
	if !inputOK || !outputOK || os.Getenv("TERM") == "dumb" {
		return nil, nil, false
	}
	inputInfo, inputErr := input.Stat()
	outputInfo, outputErr := output.Stat()
	if inputErr != nil || outputErr != nil {
		return nil, nil, false
	}
	return input, output, inputInfo.Mode()&os.ModeCharDevice != 0 && outputInfo.Mode()&os.ModeCharDevice != 0
}
