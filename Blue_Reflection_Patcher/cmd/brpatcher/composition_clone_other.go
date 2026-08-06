//go:build !linux

package main

import "os"

func tryReflinkFile(source, destination string, mode os.FileMode) (bool, error) {
	return false, nil
}
