package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/bundle"
	"local/blue-reflection-patcher/internal/detect"
	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan"
	"local/blue-reflection-patcher/internal/targets"
)

const version = "0.0.9-dev"

type rootsFlag []string

func (value *rootsFlag) String() string { return strings.Join(*value, ",") }
func (value *rootsFlag) Set(item string) error {
	*value = append(*value, item)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "version":
		fmt.Println(version)
	case "detect":
		err = commandDetect(os.Args[2:])
	case "inspect-bundle":
		err = commandInspectBundle(os.Args[2:])
	case "plan":
		err = commandPlan(os.Args[2:])
	case "state-path":
		err = commandStatePath(os.Args[2:])
	case "quartet-profile-activate":
		err = commandQuartetProfileActivate(os.Args[2:])
	case "quartet-profile-status":
		err = commandQuartetProfileStatus(os.Args[2:])
	case "quartet-profile-rollback":
		err = commandQuartetProfileRollback(os.Args[2:])
	case "quartet-shader-profile-activate":
		err = commandQuartetShaderProfileActivate(os.Args[2:])
	case "quartet-shader-profile-status":
		err = commandQuartetShaderProfileStatus(os.Args[2:])
	case "quartet-shader-profile-rollback":
		err = commandQuartetShaderProfileRollback(os.Args[2:])
	case "help", "-h", "--help":
		usage()
	default:
		err = fmt.Errorf("unknown command: %s", os.Args[1])
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
		os.Exit(1)
	}
}

func commandDetect(args []string) error {
	flags := flag.NewFlagSet("detect", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	flags.Var(&roots, "root", "manual game root; may be repeated")
	flags.StringVar(&output, "json", "", "write JSON result to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	items, err := detect.Detect(specs, roots)
	if err != nil {
		return err
	}
	return emit(items, output)
}

func commandInspectBundle(args []string) error {
	flags := flag.NewFlagSet("inspect-bundle", flag.ContinueOnError)
	var path string
	flags.StringVar(&path, "bundle", "", "path to .brpatch or manifest JSON")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if path == "" {
		return fmt.Errorf("--bundle is required")
	}
	manifest, err := bundle.Load(path)
	if err != nil {
		return err
	}
	return emit(manifest, "")
}

func commandPlan(args []string) error {
	flags := flag.NewFlagSet("plan", flag.ContinueOnError)
	var path, moduleList, output string
	var roots rootsFlag
	flags.StringVar(&path, "bundle", "", "path to .brpatch or manifest JSON")
	flags.StringVar(&moduleList, "modules", "", "comma-separated module IDs; empty uses defaults")
	flags.StringVar(&output, "json", "", "write plan JSON to this file")
	flags.Var(&roots, "root", "manual game root; may be repeated")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if path == "" {
		return fmt.Errorf("--bundle is required")
	}
	manifest, err := bundle.Load(path)
	if err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	detections, err := detect.Detect(specs, roots)
	if err != nil {
		return err
	}
	var modules []string
	for _, item := range strings.Split(moduleList, ",") {
		if trimmed := strings.TrimSpace(item); trimmed != "" {
			modules = append(modules, trimmed)
		}
	}
	patchPlan, err := plan.Build(manifest, detections, modules)
	if err != nil {
		return err
	}
	return emit(patchPlan, output)
}

func commandStatePath(args []string) error {
	flags := flag.NewFlagSet("state-path", flag.ContinueOnError)
	var appID string
	flags.StringVar(&appID, "app-id", "series", "Steam app ID or series")
	if err := flags.Parse(args); err != nil {
		return err
	}
	root, err := stateRoot()
	if err != nil {
		return err
	}
	fmt.Println(filepath.Join(root, "unburger-patcher", "blue-reflection", appID))
	return nil
}

func stateRoot() (string, error) {
	if value := os.Getenv("XDG_STATE_HOME"); value != "" {
		return value, nil
	}
	if value := os.Getenv("LOCALAPPDATA"); value != "" {
		return value, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".local", "state"), nil
}

func emit(value any, output string) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if output == "" {
		_, err = os.Stdout.Write(data)
		return err
	}
	if err := os.MkdirAll(filepath.Dir(output), 0o755); err != nil && filepath.Dir(output) != "." {
		return err
	}
	return os.WriteFile(output, data, 0o644)
}

func usage() {
	fmt.Print(`Blue Reflection unified PC patcher planner

Commands:
  version
  detect [--root PATH] [--json FILE]
  inspect-bundle --bundle FILE
  plan --bundle FILE [--modules ID,ID] [--root PATH] [--json FILE]
  state-path [--app-id ID]
  quartet-profile-activate --project-root PATH --game-root PATH PROFILE_ID
  quartet-profile-status --project-root PATH --game-root PATH
  quartet-profile-rollback --project-root PATH --game-root PATH
  quartet-shader-profile-activate --project-root PATH --game-root PATH PROFILE_ID
  quartet-shader-profile-status --project-root PATH --game-root PATH
  quartet-shader-profile-rollback --project-root PATH --game-root PATH

The general apply/repack engine remains gated until EBM/XML import and PAK rebuild
validation are complete. This development binary already validates bundle
manifests, detects Steam/manual installations and creates deterministic plans.
`)
}

var _ model.PatchPlan
