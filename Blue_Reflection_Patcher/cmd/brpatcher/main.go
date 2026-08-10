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
	"local/blue-reflection-patcher/internal/runtimebundle"
	"local/blue-reflection-patcher/internal/targets"
)

var version = "dev"

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
	case "quartet-composition-build":
		err = commandQuartetCompositionBuild(os.Args[2:])
	case "quartet-composition-lock-status":
		err = commandQuartetCompositionLockStatus(os.Args[2:])
	case "transaction-prepare":
		err = commandTransactionPrepare(os.Args[2:])
	case "baseline-status":
		err = commandBaselineStatus(os.Args[2:])
	case "installation-status":
		err = commandInstallationStatus(os.Args[2:])
	case "installation-reset-state":
		err = commandInstallationResetState(os.Args[2:])
	case "installation-remove":
		err = commandInstallationRemove(os.Args[2:])
	case "save-access":
		err = commandQuartetSaveAccess(os.Args[2:])
	case "quartet-marker-fast-test":
		err = commandQuartetMarkerFastTest(os.Args[2:])
	case "transaction-status":
		err = commandTransactionStatus(os.Args[2:])
	case "transaction-commit":
		err = commandTransactionCommit(os.Args[2:])
	case "transaction-rollback":
		err = commandTransactionRollback(os.Args[2:])
	case "transaction-discard":
		err = commandTransactionDiscard(os.Args[2:])
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

func boolCount(values ...bool) int {
	count := 0
	for _, value := range values {
		if value {
			count++
		}
	}
	return count
}

func consumeHiddenLegacyAssets(args []string) ([]string, string, error) {
	filtered := make([]string, 0, len(args))
	var value string
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--legacy-assets" {
			if i+1 >= len(args) || strings.TrimSpace(args[i+1]) == "" {
				return nil, "", fmt.Errorf("--legacy-assets requires a file or directory path")
			}
			if value != "" {
				return nil, "", fmt.Errorf("--legacy-assets may be supplied only once")
			}
			value = args[i+1]
			i++
			continue
		}
		if strings.HasPrefix(arg, "--legacy-assets=") {
			if value != "" {
				return nil, "", fmt.Errorf("--legacy-assets may be supplied only once")
			}
			value = strings.TrimSpace(strings.TrimPrefix(arg, "--legacy-assets="))
			if value == "" {
				return nil, "", fmt.Errorf("--legacy-assets requires a file or directory path")
			}
			continue
		}
		filtered = append(filtered, arg)
	}
	return filtered, value, nil
}

func commandStart(args []string) error {
	flags := flag.NewFlagSet("start", flag.ContinueOnError)
	var roots rootsFlag
	var noPrompt bool
	var moduleList, output, projectRoot, payloadOutput string
	var guidedPrepare, guidedInstall, guidedRemove, confirmed, buildLocal bool
	var legacySource, secondLightSource, dlcSources, legacySteam, legacySCLabels, legacySaveRoot string
	filteredArgs, legacyAssets, err := consumeHiddenLegacyAssets(args)
	if err != nil {
		return err
	}
	var legacyNoAuto, legacySyncSaves bool
	flags.Var(&roots, "game-dir", "game directory; may be repeated")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.BoolVar(&noPrompt, "no-prompt", false, "use default modules and fail instead of prompting for a game directory")
	flags.StringVar(&moduleList, "modules", "", "comma-separated module IDs; 'none' disables all modules")
	flags.StringVar(&output, "json", "", "write the selected desired state to this JSON file")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified local build artifacts")
	flags.StringVar(&payloadOutput, "payload-json", "", "write local payload transaction preview JSON to this file")
	flags.BoolVar(&guidedPrepare, "prepare", false, "prepare the verified selected payloads without modifying game files")
	flags.BoolVar(&guidedInstall, "install", false, "prepare and install the verified selected payloads")
	flags.BoolVar(&guidedRemove, "remove", false, "remove all patcher-installed modules and restore the persistent baseline")
	flags.BoolVar(&confirmed, "yes", false, "confirm game-file modification for non-interactive --install or --remove")
	flags.BoolVar(&buildLocal, "build-local", false, "rebuild current local Translation payloads before guided preparation or installation")
	flags.StringVar(&legacySource, "legacy-source", "", "BLUE REFLECTION (2017) game folder used when BLUE REFLECTION DLC restoration is selected")
	flags.StringVar(&secondLightSource, "second-light-source", "", "standalone BLUE REFLECTION: Second Light game folder used for Second Light DLC restoration")
	flags.StringVar(&dlcSources, "dlc-sources", "", "DLC source games for non-interactive use: blue_reflection,second_light (default: both)")
	flags.StringVar(&legacySteam, "legacy-steam", "", "Steam installation or Steam library folder used to locate BLUE REFLECTION (2017)")
	flags.BoolVar(&legacyNoAuto, "legacy-no-auto", false, "disable automatic Steam discovery for the BLUE REFLECTION (2017) source")
	flags.StringVar(&legacySCLabels, "legacy-sc-labels", "blank", "Simplified Chinese restored labels: blank or hant")
	flags.StringVar(&legacySaveRoot, "legacy-save-root", "", "Quartet save folder, one .pcsave file, or Wine/Proton prefix used for DLC save-access synchronization")
	flags.BoolVar(&legacySyncSaves, "legacy-sync-saves", false, "update restored costume and Tropical Island access in existing Quartet saves after install")
	if err := flags.Parse(filteredArgs); err != nil {
		return err
	}
	releaseRoot := strings.TrimSpace(projectRoot)
	if removed, pruneErr := runtimebundle.PruneOlderRuntimeBundles(releaseRoot); pruneErr != nil {
		return fmt.Errorf("prune older runtime bundles: %w", pruneErr)
	} else {
		for _, path := range removed {
			fmt.Printf("Removed older UNBURGER payload: %s\n", filepath.Base(path))
		}
	}
	var runtimeCleanup func()
	projectRoot, runtimeCleanup, err = runtimebundle.ResolveProjectRootTransient(projectRoot)
	if err != nil {
		return fmt.Errorf("resolve runtime bundle: %w", err)
	}
	defer runtimeCleanup()
	if boolCount(guidedPrepare, guidedInstall, guidedRemove) > 1 {
		return fmt.Errorf("--prepare, --install and --remove are mutually exclusive")
	}
	if confirmed && !guidedInstall && !guidedRemove {
		return fmt.Errorf("--yes is only valid with --install or --remove")
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
		return fmt.Errorf("no supported installation detected automatically; run from the game directory or pass --game-dir PATH")
	}
	// Automatic discovery may legitimately find more than one supported game
	// across Steam libraries. Guided start operates on one installation at a
	// time, so ask explicitly instead of accidentally composing a multi-target
	// selection. Repeated explicit --game-dir values retain the older advanced
	// multi-target behavior.
	if len(roots) == 0 && len(items) > 1 {
		if !prompt {
			return fmt.Errorf("multiple supported installations detected automatically; pass --game-dir PATH to choose one")
		}
		chosenGame, chooseErr := chooseDetectedInstallation(items, os.Stdin, os.Stdout)
		if chooseErr != nil {
			return chooseErr
		}
		items = []model.Detection{chosenGame}
	}
	printHumanDetections(os.Stdout, items)
	if guidedRemove {
		if !confirmed {
			return fmt.Errorf("non-interactive --remove modifies game files when a managed installation is active; pass --yes or use the interactive management menu")
		}
		if len(items) != 1 {
			return fmt.Errorf("--remove requires exactly one detected installation; found %d", len(items))
		}
		report, err := removeManagedInstallation(items[0].TargetID, items[0].DisplayName, items[0].Root)
		if err != nil {
			return err
		}
		printHumanInstallationRemove(os.Stdout, report)
		return nil
	}
	if prompt && len(items) == 1 {
		managementAction, _, managementErr := chooseGuidedInstallationManagement(items[0], os.Stdin, os.Stdout)
		if managementErr != nil {
			return managementErr
		}
		switch managementAction {
		case guidedManagementRemove:
			progress := newTransactionProgressRenderer(os.Stdout)
			progress.Status("rollback", "load_state", "Reading rollback metadata")
			report, removeErr := removeManagedInstallationWithProgress(items[0].TargetID, items[0].DisplayName, items[0].Root, progress.Callback)
			progress.Finish()
			if removeErr != nil {
				return removeErr
			}
			printHumanInstallationRemove(os.Stdout, report)
			return nil
		case guidedManagementCancel:
			fmt.Println("No game files were modified.")
			return nil
		}
	}
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
	if _, requested, legacyErr := selectionUsesIntegratedQuartetContent(chosen); legacyErr != nil {
		return legacyErr
	} else if requested {
		legacyResult, runErr := runQuartetContentGuided(chosen, legacyContentStartOptions{
			ProjectRoot: projectRoot, ReleaseRoot: releaseRoot, SourceRoot: legacySource, SecondLightSourceRoot: secondLightSource, DLCSourceGames: dlcSources, SteamRoot: legacySteam, AssetRoot: legacyAssets, DisableAutoSource: legacyNoAuto,
			SimplifiedLabels: legacySCLabels,
			SaveRoot:         legacySaveRoot, SyncSaves: legacySyncSaves, BuildLocal: buildLocal,
			Prepare: guidedPrepare, Install: guidedInstall, Confirmed: confirmed, Prompt: prompt,
		}, os.Stdout)
		if output != "" {
			if emitErr := emit(chosen, output); emitErr != nil {
				return emitErr
			}
		}
		if payloadOutput != "" {
			if emitErr := emit(legacyResult, payloadOutput); emitErr != nil {
				return emitErr
			}
		}
		return runErr
	}
	if _, requested, recordErr := selectionUsesRecordTranslation(chosen); recordErr != nil {
		return recordErr
	} else if requested {
		if _, releaseAvailable := recordTranslationBundleRoot(projectRoot); releaseAvailable {
			recordResult, runErr := runRecordTranslationGuided(chosen, projectRoot, guidedPrepare, guidedInstall, confirmed, prompt, os.Stdout)
			if output != "" {
				if emitErr := emit(chosen, output); emitErr != nil {
					return emitErr
				}
			}
			if payloadOutput != "" {
				if emitErr := emit(recordResult, payloadOutput); emitErr != nil {
					return emitErr
				}
			}
			return runErr
		}
	}
	preview, previewErr := buildPayloadPreview(projectRoot, chosen)
	if previewErr != nil {
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

	previewNeedsBuild := previewErr != nil || !previewReadyForGuidedAction(preview)
	buildRequested := buildLocal
	if buildRequested && !selectionSupportsLocalTranslationBuild(chosen) {
		return fmt.Errorf("--build-local supports Translation with optional Quartet Restoration and/or Legacy DLC")
	}
	if !buildRequested && previewNeedsBuild && prompt && localTranslationBuildAvailable(projectRoot, chosen) {
		buildRequested, err = chooseLocalTranslationBuild(os.Stdin, os.Stdout)
		if err != nil {
			return err
		}
	}
	if buildRequested {
		reportPath, buildErr := runLocalTranslationPreviewBuild(projectRoot, chosen, os.Stdout)
		if buildErr != nil {
			return buildErr
		}
		fmt.Printf("Local Translation build report: %s\n", reportPath)
		preview, previewErr = buildPayloadPreview(projectRoot, chosen)
		if previewErr != nil {
			return fmt.Errorf("local Translation build completed but payload preview is unavailable: %w", previewErr)
		}
		printHumanPayloadPreview(os.Stdout, preview)
		if payloadOutput != "" {
			if err := emit(preview, payloadOutput); err != nil {
				return err
			}
			fmt.Printf("Payload preview report: %s\n", payloadOutput)
		}
	}

	if quartetRoot, compositionModules, requested := selectionRequestsQuartetComposition(chosen); requested {
		if composition, compositionErr := buildQuartetModuleCompositionPreview(projectRoot, quartetRoot, compositionModules); compositionErr != nil {
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

	action := guidedActionCancel
	if guidedPrepare {
		action = guidedActionPrepare
	} else if guidedInstall {
		if !confirmed {
			return fmt.Errorf("non-interactive --install modifies game files; pass --yes or use the interactive action menu")
		}
		action = guidedActionInstall
	} else if prompt && previewErr == nil && previewReadyForGuidedAction(preview) {
		action, err = chooseGuidedPayloadAction(preview, os.Stdin, os.Stdout)
		if err != nil {
			return err
		}
	}
	if action != guidedActionCancel {
		if previewErr != nil {
			return fmt.Errorf("cannot execute selected action because payload preview is unavailable: %w", previewErr)
		}
		if _, err := executeGuidedPayloadAction(preview, action, os.Stdout); err != nil {
			return err
		}
		return nil
	}
	if previewErr == nil && previewReadyForGuidedAction(preview) {
		fmt.Println("No game files were modified. Run interactively to choose Install / update now, or use start --install --yes for automation.")
	} else {
		fmt.Println("No game files were modified. Resolve the reported payload readiness issue before installation.")
	}
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
  start [--game-dir PATH] [--modules ID,ID|none] [--project-root PATH] [--build-local] [--prepare|--install --yes|--remove --yes] [legacy-content source options] [--no-prompt] [--json FILE]
  version
  detect [--game-dir PATH] [--prompt] [--json FILE]
  inspect-bundle --bundle FILE
  plan --bundle FILE [--modules ID,ID] [--root PATH] [--json FILE]
  state-path [--app-id ID]
  payload-preview [--game-dir PATH] [--modules ID,ID|none] [--project-root PATH] [--json FILE]
  quartet-composition-preview [--game-dir PATH] [--project-root PATH] [--modules LIST] [--json FILE]
  quartet-composition-build [--game-dir PATH] [--project-root PATH] [--modules LIST] [--gust-pak PATH] [--timeout DURATION] [--json FILE]
  quartet-composition-lock-status [--project-root PATH] [--json FILE]
  transaction-prepare [--game-dir PATH] [--modules ID,ID|none] [--project-root PATH] [--json FILE]
  baseline-status [--game-dir PATH] [--json FILE]
  installation-status [--game-dir PATH] [--json FILE]
  installation-reset-state --game-dir PATH --adopt-current --yes [--json FILE]
  installation-remove --game-dir PATH --yes [--json FILE]
  save-access [--game-dir PATH] [--save-path PATH] [--converted-save-dressroom] [--yes] [--json FILE]
  transaction-status [--game-dir PATH] [--json FILE]
  transaction-commit --journal FILE --yes [--json FILE]
  transaction-rollback --journal FILE --yes [--json FILE]
  transaction-discard --journal FILE [--json FILE]
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

The guided start command detects the game, selects target-aware modules, previews verified payloads,
shows and manages an existing active installation, offers complete removal to the preserved baseline, offers a local rebuild when development payloads are missing or stale, and then offers Install / update now, Prepare only, or Cancel. Installation preserves versioned baselines,
stages verified payloads, commits atomically per file, records active state and remains rollback-capable.
Run the binary directly from a game directory to use the complete guided workflow.
`)
}

var _ model.PatchPlan
