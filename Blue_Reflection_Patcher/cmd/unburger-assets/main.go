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
	var source, output, anchors string
	var inspect, captureAnchors bool
	fs.StringVar(&source, "source-root", "", "BLUE REFLECTION (2017) source game folder")
	fs.StringVar(&output, "output", "", "output .unburger-assets path")
	fs.StringVar(&anchors, "anchors", "", "clean-source member anchor manifest")
	fs.BoolVar(&inspect, "inspect", false, "inspect and validate a .unburger-assets manifest")
	fs.BoolVar(&captureAnchors, "capture-anchor-proposal", false, "write a metadata-only clean-source anchor proposal")
	_ = fs.Parse(os.Args[1:])

	if inspect && captureAnchors {
		fatal("--inspect and --capture-anchor-proposal are mutually exclusive")
	}
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
	if captureAnchors {
		if strings.TrimSpace(output) == "" {
			fatal("--capture-anchor-proposal requires --output FILE")
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
		manifest, err := br1rebuild.WriteSourceAnchorProposal(source, absolute)
		if err != nil {
			fatal(err.Error())
		}
		fmt.Printf("ANCHOR_PROPOSAL=%s\n", absolute)
		fmt.Printf("CAPABILITY=%s\n", manifest.Capability)
		fmt.Printf("SOURCE_FINGERPRINT=%s\n", manifest.SourceFingerprint)
		fmt.Printf("SOURCE_MEMBERS=%d\n", len(manifest.SourceMembers))
		return
	}
	if strings.TrimSpace(output) == "" {
		fatal("--output FILE is required")
	}
	if strings.TrimSpace(anchors) == "" {
		fatal("--anchors FILE is required for .unburger-assets build")
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
	manifest, err := br1rebuild.BuildSourceAssetBundle(source, absolute, anchors)
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
