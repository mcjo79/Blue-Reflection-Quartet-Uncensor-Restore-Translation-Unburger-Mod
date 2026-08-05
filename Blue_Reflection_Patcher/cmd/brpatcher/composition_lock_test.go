package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func withCompositionAliveCheck(t *testing.T, check func(int) (bool, error)) {
	t.Helper()
	previous := compositionProcessAliveCheck
	compositionProcessAliveCheck = check
	t.Cleanup(func() { compositionProcessAliveCheck = previous })
}

func compositionTestLockPath(t *testing.T, projectRoot string) string {
	t.Helper()
	path, err := secureJoin(projectRoot, quartetCompositionLockRelative)
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func writeCompositionTestOwner(t *testing.T, path string, text string) {
	t.Helper()
	if err := os.MkdirAll(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "owner"), []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestAcquireCompositionBuildLockBlocksLiveOwner(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	writeCompositionTestOwner(t, lockPath, "pid=44001\nstarted=2026-08-06T07:00:00Z\n")
	withCompositionAliveCheck(t, func(pid int) (bool, error) {
		if pid != 44001 {
			t.Fatalf("unexpected pid: %d", pid)
		}
		return true, nil
	})

	_, err := acquireCompositionBuildLock(projectRoot)
	if err == nil || !strings.Contains(err.Error(), "still running") {
		t.Fatalf("live owner was not blocked: %v", err)
	}
	if _, statErr := os.Stat(lockPath); statErr != nil {
		t.Fatalf("live lock was modified: %v", statErr)
	}
}

func TestAcquireCompositionBuildLockReclaimsDeadLegacyOwner(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	writeCompositionTestOwner(t, lockPath, "pid=44002\nstarted=2026-08-06T07:00:00Z\n")
	withCompositionAliveCheck(t, func(pid int) (bool, error) { return false, nil })

	lock, err := acquireCompositionBuildLock(projectRoot)
	if err != nil {
		t.Fatal(err)
	}
	if !lock.Reclaimed || !strings.Contains(lock.ReclaimReason, "no longer running") {
		t.Fatalf("stale lock was not reported as reclaimed: %+v", lock)
	}
	owner, _, err := readCompositionBuildLockOwner(lock.Path)
	if err != nil {
		t.Fatal(err)
	}
	if owner.Token == "" || owner.PID != os.Getpid() {
		t.Fatalf("new owner metadata is incomplete: %+v", owner)
	}
	releaseCompositionBuildLock(lock)
	if _, err := os.Stat(lockPath); !os.IsNotExist(err) {
		t.Fatalf("owned lock was not released: %v", err)
	}
}

func TestAcquireCompositionBuildLockBlocksRecentMalformedOwner(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	writeCompositionTestOwner(t, lockPath, "started=not-enough\n")

	_, err := acquireCompositionBuildLock(projectRoot)
	if err == nil || !strings.Contains(err.Error(), "malformed but recent") {
		t.Fatalf("recent malformed lock was not safely blocked: %v", err)
	}
}

func TestAcquireCompositionBuildLockReclaimsOldMalformedOwner(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	writeCompositionTestOwner(t, lockPath, "started=not-enough\n")
	old := time.Now().Add(-compositionLockOwnerGrace - time.Minute)
	if err := os.Chtimes(lockPath, old, old); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(filepath.Join(lockPath, "owner"), old, old); err != nil {
		t.Fatal(err)
	}

	lock, err := acquireCompositionBuildLock(projectRoot)
	if err != nil {
		t.Fatal(err)
	}
	if !lock.Reclaimed || !strings.Contains(lock.ReclaimReason, "malformed") {
		t.Fatalf("old malformed lock was not reclaimed: %+v", lock)
	}
	releaseCompositionBuildLock(lock)
}

func TestAcquireCompositionBuildLockRejectsSymlinkPath(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	if err := os.MkdirAll(filepath.Dir(lockPath), 0o700); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(projectRoot, "outside")
	if err := os.Mkdir(target, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, lockPath); err != nil {
		t.Fatal(err)
	}

	_, err := acquireCompositionBuildLock(projectRoot)
	if err == nil || !strings.Contains(err.Error(), "not a regular directory") {
		t.Fatalf("symlink lock path was not rejected: %v", err)
	}
}

func TestReleaseCompositionBuildLockPreservesReplacementOwner(t *testing.T) {
	projectRoot := t.TempDir()
	lock, err := acquireCompositionBuildLock(projectRoot)
	if err != nil {
		t.Fatal(err)
	}
	replacement := compositionBuildLockOwner{
		PID: os.Getpid(), Started: time.Now().UTC().Format(time.RFC3339Nano),
		Token: "replacement-token", Hostname: localCompositionHostname(),
	}
	if err := writeCompositionBuildLockOwner(lock.Path, replacement); err != nil {
		t.Fatal(err)
	}
	releaseCompositionBuildLock(lock)
	if _, err := os.Stat(lock.Path); err != nil {
		t.Fatalf("replacement lock was removed: %v", err)
	}
}

func TestQuartetCompositionLockStatusReportUnlocked(t *testing.T) {
	projectRoot := t.TempDir()
	report, err := buildQuartetCompositionLockStatusReport(projectRoot, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if report.Status != "unlocked" || report.Reclaimable || report.Owner != nil {
		t.Fatalf("unexpected unlocked report: %+v", report)
	}
}

func TestQuartetCompositionLockStatusReportActiveAndStale(t *testing.T) {
	projectRoot := t.TempDir()
	lockPath := compositionTestLockPath(t, projectRoot)
	writeCompositionTestOwner(t, lockPath, "pid=44003\nstarted=2026-08-06T07:00:00Z\n")

	withCompositionAliveCheck(t, func(pid int) (bool, error) { return true, nil })
	active, err := buildQuartetCompositionLockStatusReport(projectRoot, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if active.Status != "active" || active.Reclaimable || active.Owner == nil {
		t.Fatalf("unexpected active report: %+v", active)
	}

	compositionProcessAliveCheck = func(pid int) (bool, error) { return false, nil }
	stale, err := buildQuartetCompositionLockStatusReport(projectRoot, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if stale.Status != "stale_reclaimable" || !stale.Reclaimable {
		t.Fatalf("unexpected stale report: %+v", stale)
	}
}
