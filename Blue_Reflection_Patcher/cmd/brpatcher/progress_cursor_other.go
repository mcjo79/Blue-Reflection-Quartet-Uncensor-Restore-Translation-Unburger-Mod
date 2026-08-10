//go:build !windows

package main

import "io"

func captureNativeProgressCursor(io.Writer) (int16, int16, bool) {
	return 0, 0, false
}

func restoreNativeProgressCursor(io.Writer, int16, int16) bool {
	return false
}
