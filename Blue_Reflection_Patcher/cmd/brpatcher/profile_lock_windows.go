//go:build windows

package main

import (
	"fmt"
	"os"
	"path/filepath"
)

func acquireProfileLock(projectRoot string) (func(), error) {
	path := filepath.Join(projectRoot, ".local", "locks", "core_quartet_event_profile.windows.lock")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o600)
	if err != nil {
		if os.IsExist(err) {
			return nil, fmt.Errorf("another core event-profile transaction is active; remove stale lock only after confirming no transaction is running: %s", path)
		}
		return nil, err
	}
	if _, err := file.WriteString(fmt.Sprintf("pid=%d\nstarted=%s\n", os.Getpid(), utcNow())); err != nil {
		file.Close()
		_ = os.Remove(path)
		return nil, err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		_ = os.Remove(path)
		return nil, err
	}
	return func() {
		_ = file.Close()
		_ = os.Remove(path)
	}, nil
}
