package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/detect"
	"local/blue-reflection-patcher/internal/model"
)

func defaultDetectionCandidates(explicit []string) ([]detect.RootCandidate, error) {
	if len(explicit) > 0 {
		candidates := make([]detect.RootCandidate, 0, len(explicit))
		for _, root := range explicit {
			candidates = append(candidates, detect.RootCandidate{Path: root, Source: "explicit_path"})
		}
		return candidates, nil
	}
	cwd, err := os.Getwd()
	if err != nil {
		return nil, fmt.Errorf("resolve current directory: %w", err)
	}
	candidates := []detect.RootCandidate{{Path: cwd, Source: "current_directory"}}
	if executable, err := os.Executable(); err == nil {
		candidates = append(candidates, detect.RootCandidate{
			Path: filepath.Dir(executable), Source: "executable_directory",
		})
	}
	return candidates, nil
}

func detectWithFallback(
	specs []model.TargetSpec,
	explicit []string,
	prompt bool,
	in io.Reader,
	out io.Writer,
) ([]model.Detection, error) {
	candidates, err := defaultDetectionCandidates(explicit)
	if err != nil {
		return nil, err
	}
	items, err := detect.Detect(specs, candidates)
	if err != nil {
		return nil, err
	}
	if len(items) > 0 || !prompt {
		return items, nil
	}

	fmt.Fprintln(out, "No supported Blue Reflection installation was detected in the current directory.")
	fmt.Fprint(out, "Enter the game directory path (leave empty to cancel): ")
	reader := bufio.NewReader(in)
	line, err := reader.ReadString('\n')
	if err != nil && line == "" {
		return nil, fmt.Errorf("read game directory path: %w", err)
	}
	path := strings.TrimSpace(line)
	path = strings.Trim(path, `"`)
	if path == "" {
		return nil, fmt.Errorf("no game directory was provided")
	}
	items, err = detect.Detect(specs, []detect.RootCandidate{{Path: path, Source: "prompted_path"}})
	if err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return nil, fmt.Errorf("the selected directory does not match a supported Blue Reflection installation: %s", path)
	}
	return items, nil
}

func stdinIsInteractive() bool {
	info, err := os.Stdin.Stat()
	return err == nil && info.Mode()&os.ModeCharDevice != 0
}

func printHumanDetections(out io.Writer, items []model.Detection) {
	for index, item := range items {
		if index > 0 {
			fmt.Fprintln(out)
		}
		fmt.Fprintf(out, "Detected: %s\n", item.DisplayName)
		fmt.Fprintf(out, "Game directory: %s\n", item.Root)
		fmt.Fprintf(out, "Detection source: %s\n", item.Source)
		fmt.Fprintln(out, "Identification: structural game files (store-independent)")
	}
}
