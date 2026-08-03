package main

import (
	"bufio"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/selection"
)

func parseModuleList(raw string) ([]string, bool) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, false
	}
	if strings.EqualFold(raw, "none") {
		return []string{}, true
	}
	seen := map[string]bool{}
	var result []string
	for _, item := range strings.Split(raw, ",") {
		id := strings.TrimSpace(item)
		if id != "" && !seen[id] {
			seen[id] = true
			result = append(result, id)
		}
	}
	return result, true
}

func chooseModules(
	modules []model.BundleModule,
	detections []model.Detection,
	explicit []string,
	explicitSet bool,
	prompt bool,
	in io.Reader,
	out io.Writer,
) (model.SelectionResult, error) {
	if explicitSet {
		return selection.Build(detections, modules, explicit, nil, "explicit")
	}
	if !prompt {
		return selection.Build(detections, modules, nil, nil, "defaults")
	}
	reader := bufio.NewReader(in)
	perTarget := map[string][]string{}
	for _, detection := range detections {
		available := selection.Available(modules, detection.TargetID)
		defaults := map[string]bool{}
		for _, module := range available {
			defaults[module.ModuleID] = contains(module.DefaultTargets, detection.TargetID)
		}
		if terminalIn, terminalOut, ok := terminalMenuAvailable(in, out); ok {
			chosen, err := chooseModulesTUI(detection, available, defaults, terminalIn, terminalOut)
			if err != nil {
				return model.SelectionResult{}, err
			}
			perTarget[detection.TargetID] = chosen
			continue
		}

		fmt.Fprintf(out, "\nAvailable modules for %s:\n", detection.DisplayName)
		for index, module := range available {
			defaultLabel := "off"
			if contains(module.DefaultTargets, detection.TargetID) {
				defaultLabel = "on"
			}
			fmt.Fprintf(out, "  %d) [%s by default] %s\n     %s\n", index+1, defaultLabel, module.DisplayName, module.Description)
		}
		fmt.Fprint(out, "Select module numbers or IDs (comma-separated; Enter=defaults; none=disable all): ")
		line, err := reader.ReadString('\n')
		if err != nil && err != io.EOF {
			return model.SelectionResult{}, err
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if strings.EqualFold(line, "none") {
			perTarget[detection.TargetID] = []string{}
			continue
		}
		var chosen []string
		seen := map[string]bool{}
		for _, token := range strings.Split(line, ",") {
			token = strings.TrimSpace(token)
			if token == "" {
				continue
			}
			id := token
			if number, convErr := strconv.Atoi(token); convErr == nil {
				if number < 1 || number > len(available) {
					return model.SelectionResult{}, fmt.Errorf("module number out of range: %d", number)
				}
				id = available[number-1].ModuleID
			}
			if !seen[id] {
				seen[id] = true
				chosen = append(chosen, id)
			}
		}
		perTarget[detection.TargetID] = chosen
	}
	return selection.Build(detections, modules, nil, perTarget, "interactive")
}

func printHumanSelection(out io.Writer, result model.SelectionResult) {
	for _, target := range result.Targets {
		fmt.Fprintf(out, "\nModules for %s:\n", target.DisplayName)
		for _, module := range target.AvailableModules {
			mark := " "
			if module.DesiredState == "enabled" {
				mark = "x"
			}
			fmt.Fprintf(out, "  [%s] %s (%s)\n", mark, module.DisplayName, module.ModuleID)
			if len(module.SourceTargets) > 0 {
				values := append([]string(nil), module.SourceTargets...)
				sort.Strings(values)
				fmt.Fprintf(out, "      source installation required later: %s\n", strings.Join(values, ", "))
			}
		}
		if len(target.SelectedModuleIDs) == 0 {
			fmt.Fprintln(out, "Desired state: no modules enabled")
		} else {
			fmt.Fprintf(out, "Desired state: enable %s\n", strings.Join(target.SelectedModuleIDs, ", "))
		}
	}
}

func contains(values []string, needle string) bool {
	for _, value := range values {
		if value == needle {
			return true
		}
	}
	return false
}
