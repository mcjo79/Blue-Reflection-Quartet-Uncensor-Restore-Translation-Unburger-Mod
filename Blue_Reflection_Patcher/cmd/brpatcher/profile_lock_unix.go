//go:build !windows

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
)

func acquireProfileLock(projectRoot string) (func(), error) {
	path := filepath.Join(projectRoot, ".local", "locks", "core_quartet_event_profile.lock")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(file.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		return nil, fmt.Errorf("another core event-profile transaction is active")
	}
	if err := file.Truncate(0); err == nil {
		_, _ = file.WriteString(fmt.Sprintf("pid=%d\nstarted=%s\n", os.Getpid(), utcNow()))
		_ = file.Sync()
	}
	return func() {
		_ = syscall.Flock(int(file.Fd()), syscall.LOCK_UN)
		_ = file.Close()
	}, nil
}
