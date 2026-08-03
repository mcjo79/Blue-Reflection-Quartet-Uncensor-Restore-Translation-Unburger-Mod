package main

import (
	"flag"
	"fmt"
	"io"
	"os"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/catalog"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/targets"
)

func buildPayloadPreview(projectRoot string, selection model.SelectionResult) (payloadpreview.Preview, error) {
	base, err := stateRoot()
	if err != nil {
		return payloadpreview.Preview{}, err
	}
	return payloadpreview.Build(projectRoot, base, selection)
}

func commandPayloadPreview(args []string) error {
	flags := flag.NewFlagSet("payload-preview", flag.ContinueOnError)
	var roots rootsFlag
	var noPrompt bool
	var moduleList, output, projectRoot string
	flags.Var(&roots, "game-dir", "game directory; may be repeated")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.BoolVar(&noPrompt, "no-prompt", false, "use default modules and fail instead of prompting")
	flags.StringVar(&moduleList, "modules", "", "comma-separated module IDs; 'none' disables all modules")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified local build artifacts")
	flags.StringVar(&output, "json", "", "write payload preview JSON to this file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	prompt := !noPrompt && stdinIsInteractive()
	detections, err := detectWithFallback(specs, roots, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	if len(detections) == 0 {
		return fmt.Errorf("no supported installation detected; run from the game directory or pass --game-dir PATH")
	}
	modules, err := catalog.Load()
	if err != nil {
		return err
	}
	explicit, explicitSet := parseModuleList(moduleList)
	selected, err := chooseModules(modules, detections, explicit, explicitSet, prompt, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	preview, err := buildPayloadPreview(projectRoot, selected)
	if err != nil {
		return err
	}
	printHumanPayloadPreview(os.Stdout, preview)
	if output != "" {
		if err := emit(preview, output); err != nil {
			return err
		}
		fmt.Printf("Payload preview report: %s\n", output)
	}
	return nil
}

func printHumanPayloadPreview(out io.Writer, preview payloadpreview.Preview) {
	fmt.Fprintf(out, "\n%s%sLocal payload transaction preview%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, preview.Status)
	for _, target := range preview.Targets {
		fmt.Fprintf(out, "\n%s%s%s\n", ansiBold, target.DisplayName, ansiReset)
		fmt.Fprintf(out, "  Game:  %s\n", target.GameRoot)
		fmt.Fprintf(out, "  State: %s\n", target.StateDirectory)
		for _, module := range target.Modules {
			marker := ansiYellow + "[pending]" + ansiReset
			if module.Ready {
				marker = ansiGreen + ansiBold + "[ready]" + ansiReset
			}
			fmt.Fprintf(out, "  %s %s%s%s\n", marker, ansiBold, module.ModuleID, ansiReset)
			if module.Reason != "" {
				fmt.Fprintf(out, "      %s%s%s\n", ansiDim, module.Reason, ansiReset)
			}
			for _, artifact := range module.Artifacts {
				action := artifact.DesiredAction
				style := ansiGreen
				if action == "replace" {
					style = ansiYellow
				} else if action == "blocked" {
					style = ansiYellow + ansiBold
				}
				fmt.Fprintf(out, "      %s%-7s%s %s\n", style, action, ansiReset, artifact.RelativePath)
				if artifact.Error != "" {
					fmt.Fprintf(out, "              %s%s%s\n", ansiYellow, artifact.Error, ansiReset)
				}
			}
		}
	}
	fmt.Fprintf(out, "\n%sPreview only:%s no transaction was prepared and no game file was modified.\n", ansiBold, ansiReset)
	fmt.Fprintf(out, "%sQuartet composition payloads can be built locally with quartet-composition-build; transaction commit remains disabled.%s\n", ansiDim, ansiReset)
}
