package main

import (
	"fmt"
	"os"
	"path/filepath"
)

func cloneOrCopyCompositionFile(source, destination, expectedHash string, expectedSize int64, mode os.FileMode) (string, error) {
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return "", err
	}
	cloned, err := tryReflinkFile(source, destination, mode)
	if err != nil {
		return "", err
	}
	if cloned {
		hash, size, err := checkedFile(destination)
		if err != nil {
			return "", err
		}
		if hash != expectedHash || size != expectedSize {
			_ = os.Remove(destination)
			return "", fmt.Errorf("reflinked composition file fingerprint mismatch")
		}
		return "reflink", nil
	}
	if err := copyFileDurable(source, destination, expectedHash, expectedSize, mode); err != nil {
		return "", err
	}
	return "copy", nil
}
