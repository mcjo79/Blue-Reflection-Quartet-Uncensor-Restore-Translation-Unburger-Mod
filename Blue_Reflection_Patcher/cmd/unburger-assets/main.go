package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

func main() {
	fs := flag.NewFlagSet("unburger-assets", flag.ExitOnError)
	var source, output string
	var inspect bool
	fs.StringVar(&source, "source-root", "", "BLUE REFLECTION (2017) source game folder")
	fs.StringVar(&output, "output", "", "output .unburger-assets path")
	fs.BoolVar(&inspect, "inspect", false, "inspect and validate a .unburger-assets manifest")
	_ = fs.Parse(os.Args[1:])

	if inspect {
		if strings.TrimSpace(output) == "" {
			fatal("--inspect requires --output FILE")
		}
		manifest, err := br1rebuild.ReadSourceAssetManifest(output)
		if err != nil {
			fatal(err.Error())
		}
		blob, _ := json.MarshalIndent(manifest, "", "  ")
		fmt.Println(string(blob))
		return
	}
	if strings.TrimSpace(output) == "" {
		fatal("--output FILE is required")
	}
	if strings.TrimSpace(source) == "" {
		location, err := br1rebuild.LocateSourceInstall(br1rebuild.SourceLocator{AutoSteam: true})
		if err != nil {
			fatal("Steam autodetection failed: " + err.Error())
		}
		source = location.Root
	}
	absolute, err := filepath.Abs(output)
	if err != nil {
		fatal(err.Error())
	}
	manifest, err := br1rebuild.BuildSourceAssetBundle(source, absolute)
	if err != nil {
		fatal(err.Error())
	}
	info, err := os.Stat(absolute)
	if err != nil {
		fatal(err.Error())
	}
	fmt.Printf("ASSET_BUNDLE=%s\n", absolute)
	fmt.Printf("CAPABILITY=%s\n", manifest.Capability)
	fmt.Printf("SOURCE_FINGERPRINT=%s\n", manifest.SourceFingerprint)
	fmt.Printf("SOURCE_MEMBERS=%d\n", len(manifest.SourceMembers))
	fmt.Printf("BYTES=%d\n", info.Size())
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, "ERROR:", message)
	os.Exit(1)
}
