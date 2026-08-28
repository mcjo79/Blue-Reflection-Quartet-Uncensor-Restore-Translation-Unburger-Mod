package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

func fatal(v string) {
	fmt.Fprintln(os.Stderr, "ERROR:", v)
	os.Exit(1)
}

func main() {
	fs := flag.NewFlagSet("unburger-canonical-source", flag.ExitOnError)
	importMode := fs.Bool("import", false, "import canonical wet-school source from a verified BLUE REFLECTION (2017) installation")
	verifyMode := fs.Bool("verify", false, "verify an existing local canonical wet-school source cache")
	source := fs.String("source", "", "BLUE REFLECTION (2017) source root for --import")
	output := fs.String("output", "", "local canonical source cache directory for --import")
	input := fs.String("input", "", "local canonical source cache directory for --verify")
	_ = fs.Parse(os.Args[1:])

	if (*importMode && *verifyMode) || (!*importMode && !*verifyMode) {
		fatal("choose exactly one of --import or --verify")
	}
	if *importMode {
		if *source == "" || *output == "" {
			fatal("--import requires --source and --output")
		}
		sourceAbs, _ := filepath.Abs(*source)
		outputAbs, _ := filepath.Abs(*output)
		manifest, err := br1rebuild.BuildWetSchoolCanonicalPayload(sourceAbs, outputAbs)
		if err != nil {
			fatal(err.Error())
		}
		fmt.Printf("Canonical UNCENSOR local source imported: PASS\n")
		fmt.Printf("capability=%s\n", manifest.Capability)
		fmt.Printf("members=%d\n", len(manifest.SourceMembers))
		fmt.Printf("fingerprint=%s\n", manifest.SourceFingerprint)
		return
	}
	if *input == "" {
		fatal("--verify requires --input")
	}
	inputAbs, _ := filepath.Abs(*input)
	if err := br1rebuild.ValidateWetSchoolCanonicalPayload(inputAbs); err != nil {
		fatal(err.Error())
	}
	fmt.Println("Canonical UNCENSOR local source cache: PASS")
}
