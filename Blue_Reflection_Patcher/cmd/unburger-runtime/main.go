package main

import (
	"flag"
	"fmt"
	"os"
	"strings"

	"local/blue-reflection-patcher/internal/runtimebundle"
)

func main() {
	fs := flag.NewFlagSet("unburger-runtime", flag.ExitOnError)
	input := fs.String("encrypt", "", "plain tar+Zstandard runtime image to encrypt")
	output := fs.String("output", "", "output encrypted .unburger path")
	verify := fs.String("verify", "", "verify one .unburger runtime bundle")
	version := fs.String("version", "", "print core version from one .unburger runtime bundle")
	_ = fs.Parse(os.Args[1:])

	modes := 0
	if strings.TrimSpace(*input) != "" {
		modes++
	}
	if strings.TrimSpace(*verify) != "" {
		modes++
	}
	if strings.TrimSpace(*version) != "" {
		modes++
	}
	if modes != 1 {
		fatal("choose exactly one of --encrypt, --verify or --version")
	}
	if strings.TrimSpace(*input) != "" {
		if strings.TrimSpace(*output) == "" {
			fatal("--encrypt requires --output")
		}
		if err := runtimebundle.EncryptRuntimeBundleV4(*input, *output); err != nil {
			fatal(err.Error())
		}
		if err := runtimebundle.VerifyBundleFile(*output); err != nil {
			fatal("encrypted runtime verification failed: " + err.Error())
		}
		v, err := runtimebundle.CoreVersion(*output)
		if err != nil {
			fatal(err.Error())
		}
		fmt.Printf("RUNTIME_BUNDLE=%s\nCORE_VERSION=%s\nFORMAT=encrypted-v4\n", *output, v)
		return
	}
	path := *verify
	if strings.TrimSpace(path) != "" {
		if err := runtimebundle.VerifyBundleFile(path); err != nil {
			fatal(err.Error())
		}
		v, err := runtimebundle.CoreVersion(path)
		if err != nil {
			fatal(err.Error())
		}
		fmt.Printf("VERIFY=PASS\nCORE_VERSION=%s\n", v)
		return
	}
	v, err := runtimebundle.CoreVersion(*version)
	if err != nil {
		fatal(err.Error())
	}
	fmt.Println(v)
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, "ERROR:", message)
	os.Exit(1)
}
