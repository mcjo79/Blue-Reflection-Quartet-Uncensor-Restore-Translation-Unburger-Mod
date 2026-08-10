package main

import (
	"fmt"
	"os"
	"path/filepath"

	"local/blue-reflection-patcher/internal/workspace"
)

// newPublicWorkRoot prunes obsolete persistent payloads and creates one
// operation-scoped workspace in the platform work area. Linux deliberately uses
// the user cache filesystem instead of /tmp. Durable state remains small;
// multi-gigabyte rollback data is kept on the game filesystem only while it is
// still reachable from an active/recoverable transaction.
func newPublicWorkRoot(stateDir, prefix string) (string, func(), error) {
	return newPublicWorkRootWithStatus(stateDir, prefix, nil)
}

func newPublicWorkRootWithStatus(stateDir, prefix string, status func(string)) (string, func(), error) {
	if status != nil {
		status("Checking persistent patcher storage; obsolete payloads will be removed without hashing game files")
	}
	installationsDir := filepath.Dir(stateDir)
	entries, readErr := os.ReadDir(installationsDir)
	if readErr != nil && !os.IsNotExist(readErr) {
		return "", func() {}, fmt.Errorf("list obsolete patcher workspaces: %w", readErr)
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		installation := filepath.Join(installationsDir, entry.Name())
		if err := cleanupPersistentWorkingPayloads(installation); err != nil {
			return "", func() {}, err
		}
	}
	// stateDir may not be present in the directory listing yet on a first run.
	if err := cleanupPersistentWorkingPayloads(stateDir); err != nil {
		return "", func() {}, err
	}
	root, err := workspace.MkdirTemp(prefix)
	if err != nil {
		return "", func() {}, err
	}
	if status != nil {
		status(fmt.Sprintf("Transient workspace: %s (removed automatically when this operation ends)", root))
	}
	cleanup := func() { _ = os.RemoveAll(root) }
	return root, cleanup, nil
}

func cleanupPersistentWorkingPayloads(installation string) error {
	if _, err := compactInstallationStorage(installation); err != nil {
		return fmt.Errorf("compact persistent patcher storage: %w", err)
	}
	return nil
}

// newGameScopedPublicWorkRoot keeps the large candidate workspace on the same
// filesystem as the game whenever that filesystem is writable. This lets the
// transaction layer stage verified candidates with hardlinks/reflinks instead
// of copying tens of gigabytes through AppData/XDG cache. The directory is
// operation-scoped and removed at the end; stale build-only work from an
// interrupted earlier run is safe to prune before creating a new workspace.
func newGameScopedPublicWorkRootWithStatus(gameRoot, stateDir, prefix string, status func(string)) (string, func(), error) {
	if status != nil {
		status("Checking persistent patcher storage; obsolete payloads will be removed without hashing game files")
	}
	installationsDir := filepath.Dir(stateDir)
	entries, readErr := os.ReadDir(installationsDir)
	if readErr != nil && !os.IsNotExist(readErr) {
		return "", func() {}, fmt.Errorf("list obsolete patcher workspaces: %w", readErr)
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		if err := cleanupPersistentWorkingPayloads(filepath.Join(installationsDir, entry.Name())); err != nil {
			return "", func() {}, err
		}
	}
	if err := cleanupPersistentWorkingPayloads(stateDir); err != nil {
		return "", func() {}, err
	}

	gameRoot = filepath.Clean(gameRoot)
	workParent := filepath.Join(filepath.Dir(gameRoot), ".unburger-patcher-work", filepath.Base(gameRoot))
	if err := os.MkdirAll(workParent, 0o700); err == nil {
		// Nothing in this tree is durable transaction state. Prepared payloads are
		// copied/linked into the separate sibling transaction-staging store before
		// this workspace can be removed.
		if stale, readErr := os.ReadDir(workParent); readErr == nil {
			for _, entry := range stale {
				if entry.IsDir() {
					_ = os.RemoveAll(filepath.Join(workParent, entry.Name()))
				}
			}
		}
		if root, err := os.MkdirTemp(workParent, prefix); err == nil {
			if status != nil {
				status(fmt.Sprintf("Game-filesystem transient workspace: %s (zero-copy staging enabled when supported)", root))
			}
			cleanup := func() {
				_ = os.RemoveAll(root)
				_ = os.Remove(workParent)
				_ = os.Remove(filepath.Dir(workParent))
			}
			return root, cleanup, nil
		}
	}
	if status != nil {
		status("Game filesystem workspace is unavailable; falling back to the platform transient workspace")
	}
	return newPublicWorkRootWithStatus(stateDir, prefix, status)
}
