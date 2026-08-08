package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"local/blue-reflection-patcher/internal/translationbundle"
)

func main() {
	fs := flag.NewFlagSet("translation-pack", flag.ExitOnError)
	project := fs.String("project-root", "", "project root containing canonical Translation records")
	output := fs.String("output", "", "output record bundle path")
	report := fs.String("report", "", "optional build report path")
	_ = fs.Parse(os.Args[1:])
	if *project == "" || *output == "" {
		fmt.Fprintln(os.Stderr, "ERROR: --project-root and --output are required")
		os.Exit(2)
	}
	stats, err := translationbundle.Write(*project, *output)
	if err != nil {
		fmt.Fprintln(os.Stderr, "ERROR:", err)
		os.Exit(1)
	}
	if *report != "" {
		data, _ := json.MarshalIndent(struct {
			Type          string `json:"type"`
			FormatVersion int    `json:"format_version"`
			Status        string `json:"status"`
			translationbundle.BuildStats
		}{Type: "unburger_translation_record_pack_build", FormatVersion: 1, Status: "pass", BuildStats: stats}, "", "  ")
		if err := os.MkdirAll(filepath.Dir(*report), 0o755); err != nil {
			panic(err)
		}
		if err := os.WriteFile(*report, append(data, '\n'), 0o644); err != nil {
			panic(err)
		}
	}
	fmt.Printf("Translation %s: %d edited records across %d members\n", stats.TranslationVersion, stats.TotalRecords, stats.TotalMembers)
}
