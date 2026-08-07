//go:build !windows

package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

func freeBytes(path string) (uint64, error) {
	var s syscall.Statfs_t
	if err := syscall.Statfs(path, &s); err != nil {
		return 0, err
	}
	return s.Bavail * uint64(s.Bsize), nil
}
func gameRunning(root string) (bool, string) {
	ents, err := os.ReadDir("/proc")
	if err != nil {
		return false, "process scan unavailable; /proc not readable"
	}
	for _, e := range ents {
		if _, er := strconv.Atoi(e.Name()); er != nil {
			continue
		}
		b, er := os.ReadFile(filepath.Join("/proc", e.Name(), "cmdline"))
		if er != nil {
			continue
		}
		s := strings.ToLower(strings.ReplaceAll(string(b), "\x00", " "))
		if strings.Contains(s, "blue reflection target.exe") || strings.Contains(s, "blue reflection target\\") {
			return true, fmt.Sprintf("Quartet process detected: pid %s", e.Name())
		}
	}
	return false, "no Quartet process detected"
}
