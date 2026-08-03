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
	"local/blue-reflection-patcher/internal/plan/catalog"
	"local/blue-reflection-patcher/internal/targets"
)

const version = "0.0.23-dev"

type rootsFlag []string

func (value *rootsFlag) String() string { return strings.Join(*value, ",") }
func (value *rootsFlag) Set(item string) error {
	*value = append(*value, item)
	return nil
}

func main() {
	if len(os.Args) < 2 {
		if err := commandStart(nil); err != nil {
			fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
			os.Exit(1)
		}
		return
	}
	var err error
	switch os.Args[1] {
	case "version":
		fmt.Println(version)
	case "start":
		err = commandStart(os.Args[2:])
	case "detect":
		err = commandDetect(os.Args[2:])
	case "inspect-bundle":
		err = commandInspectBundle(os.Args[2:])
	case "plan":
		err = commandPlan(os.Args[2:])
	case "state-path":
		err = commandStatePath(os.Args[2:])
	case "payload-preview":
		err = commandPayloadPreview(os.Args[2:])
	case "quartet-composition-preview":
		err = commandQuartetCompositionPreview(os.Args[2:])
	case "transaction-self-test":
		err = commandTransactionSelfTest(os.Args[2:])
	case "quartet-profile-activate":
		err = commandDiscoveredProfileActivate(os.Args[2:], "Data/PACK11.PAK")
	case "quartet-profile-status":
		err = commandDiscoveredProfileStatus(os.Args[2:], "Data/PACK11.PAK")
	case "quartet-profile-rollback":
		err = commandDiscoveredProfileRollback(os.Args[2:], "Data/PACK11.PAK")
	case "quartet-shader-profile-activate":
		err = commandDiscoveredProfileActivate(os.Args[2:], "Data/PACK10_01.PAK")
	case "quartet-shader-profile-status":
		err = commandDiscoveredProfileStatus(os.Args[2:], "Data/PACK10_01.PAK")
	case "quartet-shader-profile-rollback":
		err = commandDiscoveredProfileRollback(os.Args[2:], "Data/PACK10_01.PAK")
	case "quartet-field-profile-activate":
		err = commandDiscoveredProfileActivate(os.Args[2:], "Data/PACK10_03.PAK")
	case "quartet-field-profile-status":
		err = commandDiscoveredProfileStatus(os.Args[2:], "Data/PACK10_03.PAK")
	case "quartet-field-profile-rollback":
		err = commandDiscoveredProfileRollback(os.Args[2:], "Data/PACK10_03.PAK")
	case "quartet-local-profile-list":
		err = commandDiscoveredProfileList(os.Args[2:])
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

func commandStart(args []string) error {
	flags := flag.NewFlagSet("start", flag.ContinueOnError)
	var roots rootsFlag
	var noPrompt bool
	var moduleList, output, projectRoot, payloadOutput string
	flags.Var(&roots, "game-dir", "game directory; may be repeated")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.BoolVar(&noPrompt, "no-prompt", false, "use default modules and fail instead of prompting for a game directory")
	flags.StringVar(&moduleList, "modules", "", "comma-separated module IDs; 'none' disables all modules")
	flags.StringVar(&output, "json", "", "write the selected desired state to this JSON file")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified local build artifacts")
	flags.StringVar(&payloadOutput, "payload-json", "", "write local payload transaction preview JSON to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	prompt := !noPrompt && stdinIsInteractive()
	items, err := detectWithFallback(specs, roots, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	if len(items) == 0 {
		return fmt.Errorf("no supported installation detected; run from the game directory or pass --game-dir PATH")
	}
	printHumanDetections(os.Stdout, items)
	modules, err := catalog.Load()
	if err != nil {
		return err
	}
	explicit, explicitSet := parseModuleList(moduleList)
	chosen, err := chooseModules(modules, items, explicit, explicitSet, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	printHumanSelection(os.Stdout, chosen)
	if err := printTransactionFoundation(os.Stdout, chosen); err != nil {
		return err
	}
	if preview, previewErr := buildPayloadPreview(projectRoot, chosen); previewErr != nil {
		fmt.Fprintf(os.Stdout, "\nLocal payload preview unavailable: %v\n", previewErr)
	} else {
		printHumanPayloadPreview(os.Stdout, preview)
		if payloadOutput != "" {
			if err := emit(preview, payloadOutput); err != nil {
				return err
			}
			fmt.Printf("Payload preview report: %s\n", payloadOutput)
		}
	}
	if quartetRoot, requested := selectionRequestsQuartetComposition(chosen); requested {
		if composition, compositionErr := buildQuartetCompositionPreview(projectRoot, quartetRoot); compositionErr != nil {
			fmt.Fprintf(os.Stdout, "\nQuartet composition preflight unavailable: %v\n", compositionErr)
		} else {
			printHumanQuartetCompositionPreview(os.Stdout, composition)
		}
	}
	if output != "" {
		if err := emit(chosen, output); err != nil {
			return err
		}
		fmt.Printf("Selection report: %s\n", output)
	}
	fmt.Println("No game files were modified. Verified local translation artifacts and restoration composition inputs are connected in preview-only mode; commit remains disabled.")
	return nil
}

func commandDetect(args []string) error {
	flags := flag.NewFlagSet("detect", flag.ContinueOnError)
	var roots rootsFlag
	var output string
	var prompt bool
	flags.Var(&roots, "game-dir", "game directory; may be repeated")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&output, "json", "", "write JSON result to this file")
	flags.BoolVar(&prompt, "prompt", false, "ask for a path when automatic detection fails")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	items, err := detectWithFallback(specs, roots, prompt && stdinIsInteractive(), os.Stdin, os.Stdout)
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
	candidates, err := defaultDetectionCandidates(roots)
	if err != nil {
		return err
	}
	detections, err := detect.Detect(specs, candidates)
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
	flags.StringVar(&appID, "app-id", "series", "state namespace; retained for compatibility")
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
  start [--game-dir PATH] [--modules ID,ID|none] [--no-prompt] [--json FILE]
  version
  detect [--game-dir PATH] [--prompt] [--json FILE]
  inspect-bundle --bundle FILE
  plan --bundle FILE [--modules ID,ID] [--root PATH] [--json FILE]
  state-path [--app-id ID]
  payload-preview [--game-dir PATH] [--modules ID,ID|none] [--project-root PATH] [--json FILE]
  quartet-composition-preview [--game-dir PATH] [--project-root PATH] [--json FILE]
  transaction-self-test --work-dir PATH [--json FILE]
  quartet-profile-activate --project-root PATH --game-root PATH PROFILE_ID
  quartet-profile-status --project-root PATH --game-root PATH
  quartet-profile-rollback --project-root PATH --game-root PATH
  quartet-shader-profile-activate --project-root PATH --game-root PATH PROFILE_ID
  quartet-shader-profile-status --project-root PATH --game-root PATH
  quartet-shader-profile-rollback --project-root PATH --game-root PATH
  quartet-field-profile-activate --project-root PATH --game-root PATH PROFILE_ID
  quartet-field-profile-status --project-root PATH --game-root PATH
  quartet-field-profile-rollback --project-root PATH --game-root PATH
  quartet-local-profile-list --project-root PATH --game-root PATH

The general apply/repack engine remains gated until EBM/XML import and PAK rebuild
validation are complete. This development binary already validates bundle
manifests, identifies installations from structural game files, previews verified local payloads and creates deterministic plans.
Run the binary directly from a game directory to use the guided detector.
`)
}

var _ model.PatchPlan
