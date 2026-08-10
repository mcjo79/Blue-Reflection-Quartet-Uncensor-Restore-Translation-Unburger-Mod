package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
)

type quartetDLCFamily string

const (
	quartetDLCBlueReflection quartetDLCFamily = "blue_reflection"
	quartetDLCSecondLight    quartetDLCFamily = "second_light"
)

type quartetDLCChoice struct {
	ID          quartetDLCFamily
	DisplayName string
	Description string
}

var quartetDLCChoices = []quartetDLCChoice{
	{
		ID:          quartetDLCBlueReflection,
		DisplayName: "BLUE REFLECTION",
		Description: "Legacy costumes and Tropical Island",
	},
	{
		ID:          quartetDLCSecondLight,
		DisplayName: "BLUE REFLECTION: Second Light",
		Description: "Costumes, maps, events, facilities and restored collaboration content",
	},
}

func defaultQuartetDLCSelection() map[quartetDLCFamily]bool {
	return map[quartetDLCFamily]bool{
		quartetDLCBlueReflection: true,
		quartetDLCSecondLight:    true,
	}
}

func selectedQuartetDLCFamilies(selected map[quartetDLCFamily]bool) []quartetDLCFamily {
	out := make([]quartetDLCFamily, 0, len(quartetDLCChoices))
	for _, choice := range quartetDLCChoices {
		if selected[choice.ID] {
			out = append(out, choice.ID)
		}
	}
	return out
}

func chooseQuartetDLCFamiliesTUI(in *os.File, out *os.File) ([]quartetDLCFamily, error) {
	restore, err := terminalEnterRawMode(in, out)
	if err != nil {
		return nil, err
	}
	defer restore()
	defer fmt.Fprint(out, ansiShowCur, ansiReset)

	selected := defaultQuartetDLCSelection()
	continueIndex := len(quartetDLCChoices)
	cursor := continueIndex
	reader := bufio.NewReader(in)
	fmt.Fprint(out, ansiHideCur)

	for {
		renderQuartetDLCMenu(out, selected, cursor)
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
			if cursor < len(quartetDLCChoices) {
				id := quartetDLCChoices[cursor].ID
				selected[id] = !selected[id]
			}
		case keyEnter:
			if cursor == continueIndex {
				families := selectedQuartetDLCFamilies(selected)
				if len(families) == 0 {
					continue
				}
				fmt.Fprint(out, ansiClear)
				return families, nil
			}
			id := quartetDLCChoices[cursor].ID
			selected[id] = !selected[id]
		case keyCancel:
			fmt.Fprint(out, ansiClear)
			return nil, fmt.Errorf("DLC source selection cancelled")
		}
	}
}

func renderQuartetDLCMenu(out io.Writer, selected map[quartetDLCFamily]bool, cursor int) {
	fmt.Fprint(out, ansiClear)
	renderTUIFrameTop(out, "DLC RESTORATION")
	renderTUIFrameRow(out, "%sControls%s  ↑/↓ move · Enter/Space toggle · Enter on Continue confirms · Q cancels", ansiGray, ansiReset)
	renderTUIFrameBlank(out)
	renderTUIFrameRow(out, "%sChoose DLC source games%s", ansiBold, ansiReset)
	renderTUIFrameBlank(out)

	for index, choice := range quartetDLCChoices {
		pointer := "  "
		pointerStyle := ""
		if cursor == index {
			pointer = "› "
			pointerStyle = ansiYellow + ansiBold
		}
		box := "[ ]"
		boxStyle := ansiGray
		if selected[choice.ID] {
			box = "[✓]"
			boxStyle = ansiGreen + ansiBold
		}
		renderTUIFrameRow(out, "%s%s%s%s%s%s %s%s%s", pointerStyle, pointer, ansiReset, boxStyle, box, ansiReset, ansiBold, choice.DisplayName, ansiReset)
		renderTUIFrameRow(out, "    %s%s%s", ansiDim, choice.Description, ansiReset)
		renderTUIFrameBlank(out)
	}

	pointer := "  "
	style := ""
	if cursor == len(quartetDLCChoices) {
		pointer = "› "
		style = ansiYellow + ansiBold
	}
	renderTUIFrameRow(out, "%s%s%s%s[ Continue ]%s", style, pointer, ansiReset, ansiBold, ansiReset)
	renderTUIFrameBottom(out)
}
