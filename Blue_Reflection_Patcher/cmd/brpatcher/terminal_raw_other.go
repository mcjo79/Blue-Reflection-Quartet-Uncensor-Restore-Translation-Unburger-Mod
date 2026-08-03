//go:build !linux && !windows

package main

import (
	"fmt"
	"os"
)

func terminalEnterRawMode(in *os.File, out *os.File) (func(), error) {
	return nil, fmt.Errorf("interactive arrow-key menu is not supported on this platform")
}
