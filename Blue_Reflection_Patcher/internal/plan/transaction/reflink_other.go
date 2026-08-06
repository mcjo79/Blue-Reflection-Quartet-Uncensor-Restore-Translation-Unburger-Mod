//go:build !linux

package transaction

import "io/fs"

func tryReflinkRegularFile(source, destination string, mode fs.FileMode) (bool, error) {
	return false, nil
}
