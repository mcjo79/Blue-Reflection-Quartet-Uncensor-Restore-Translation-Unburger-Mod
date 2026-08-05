package main

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const compositionLockOwnerGrace = 2 * time.Minute

type compositionBuildLock struct {
	Path          string
	Token         string
	Reclaimed     bool
	ReclaimReason string
	PreviousOwner string
}

type compositionBuildLockOwner struct {
	PID        int
	Started    string
	Token      string
	Hostname   string
	Executable string
}

type compositionBuildLockInspection struct {
	State         string
	Reclaim       bool
	Reason        string
	PreviousOwner string
}

var compositionProcessAliveCheck = compositionProcessAlive

func acquireCompositionBuildLock(projectRoot string) (compositionBuildLock, error) {
	path, err := secureJoin(projectRoot, quartetCompositionLockRelative)
	if err != nil {
		return compositionBuildLock{}, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return compositionBuildLock{}, err
	}

	reclaimed := false
	reclaimReason := ""
	previousOwner := ""
	for attempt := 0; attempt < 4; attempt++ {
		token := transactionID()
		if err := os.Mkdir(path, 0o700); err == nil {
			owner := compositionBuildLockOwner{
				PID:      os.Getpid(),
				Started:  time.Now().UTC().Format(time.RFC3339Nano),
				Token:    token,
				Hostname: localCompositionHostname(),
			}
			if executable, executableErr := os.Executable(); executableErr == nil {
				owner.Executable = filepath.Base(executable)
			}
			if err := writeCompositionBuildLockOwner(path, owner); err != nil {
				_ = os.RemoveAll(path)
				return compositionBuildLock{}, fmt.Errorf("write Quartet composition lock owner: %w", err)
			}
			return compositionBuildLock{
				Path:          path,
				Token:         token,
				Reclaimed:     reclaimed,
				ReclaimReason: reclaimReason,
				PreviousOwner: previousOwner,
			}, nil
		} else if !errors.Is(err, os.ErrExist) {
			return compositionBuildLock{}, err
		}

		inspection, inspectErr := inspectCompositionBuildLock(path, time.Now())
		if inspectErr != nil {
			return compositionBuildLock{}, inspectErr
		}
		if !inspection.Reclaim {
			return compositionBuildLock{}, fmt.Errorf(
				"another Quartet composition build is already active: %s (%s)",
				path,
				inspection.Reason,
			)
		}

		quarantine := fmt.Sprintf("%s.stale-%s", path, transactionID())
		if err := os.Rename(path, quarantine); err != nil {
			if errors.Is(err, os.ErrNotExist) {
				continue
			}
			return compositionBuildLock{}, fmt.Errorf("quarantine stale Quartet composition lock: %w", err)
		}
		if err := os.RemoveAll(quarantine); err != nil {
			return compositionBuildLock{}, fmt.Errorf("remove stale Quartet composition lock quarantine: %w", err)
		}
		reclaimed = true
		reclaimReason = inspection.Reason
		previousOwner = inspection.PreviousOwner
	}
	return compositionBuildLock{}, fmt.Errorf("could not acquire Quartet composition build lock after repeated races: %s", path)
}

func inspectCompositionBuildLock(path string, now time.Time) (compositionBuildLockInspection, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return compositionBuildLockInspection{}, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return compositionBuildLockInspection{}, fmt.Errorf("Quartet composition lock is not a regular directory: %s", path)
	}

	owner, ownerInfo, err := readCompositionBuildLockOwner(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			if compositionLockAge(info.ModTime(), now) < compositionLockOwnerGrace {
				return compositionBuildLockInspection{
					State:  "ambiguous",
					Reason: "owner metadata is not available yet; refusing unsafe reclamation",
				}, nil
			}
			return compositionBuildLockInspection{
				State:   "stale_reclaimable",
				Reclaim: true,
				Reason:  "owner metadata is missing and the lock is older than the safety grace period",
			}, nil
		}
		return compositionBuildLockInspection{}, err
	}

	previousOwner := summarizeCompositionBuildLockOwner(owner)
	if owner.PID <= 0 {
		if compositionLockAge(ownerInfo.ModTime(), now) < compositionLockOwnerGrace {
			return compositionBuildLockInspection{
				State:         "ambiguous",
				Reason:        "owner metadata is malformed but recent; refusing unsafe reclamation",
				PreviousOwner: previousOwner,
			}, nil
		}
		return compositionBuildLockInspection{
			State:         "stale_reclaimable",
			Reclaim:       true,
			Reason:        "owner metadata is malformed and older than the safety grace period",
			PreviousOwner: previousOwner,
		}, nil
	}

	localHost := localCompositionHostname()
	if owner.Hostname != "" && localHost != "" && !strings.EqualFold(owner.Hostname, localHost) {
		return compositionBuildLockInspection{
			State:         "ambiguous",
			Reason:        fmt.Sprintf("owner host %q differs from local host %q; refusing unsafe reclamation", owner.Hostname, localHost),
			PreviousOwner: previousOwner,
		}, nil
	}

	alive, err := compositionProcessAliveCheck(owner.PID)
	if err != nil {
		return compositionBuildLockInspection{}, fmt.Errorf("verify Quartet composition lock owner pid %d: %w", owner.PID, err)
	}
	if alive {
		return compositionBuildLockInspection{
			State:         "active",
			Reason:        fmt.Sprintf("owner pid %d is still running", owner.PID),
			PreviousOwner: previousOwner,
		}, nil
	}
	return compositionBuildLockInspection{
		State:         "stale_reclaimable",
		Reclaim:       true,
		Reason:        fmt.Sprintf("owner pid %d is no longer running", owner.PID),
		PreviousOwner: previousOwner,
	}, nil
}

func writeCompositionBuildLockOwner(lockPath string, owner compositionBuildLockOwner) error {
	ownerPath := filepath.Join(lockPath, "owner")
	data := strings.Join([]string{
		fmt.Sprintf("pid=%d", owner.PID),
		"started=" + owner.Started,
		"token=" + owner.Token,
		"hostname=" + owner.Hostname,
		"executable=" + owner.Executable,
		"",
	}, "\n")
	return os.WriteFile(ownerPath, []byte(data), 0o600)
}

func readCompositionBuildLockOwner(lockPath string) (compositionBuildLockOwner, os.FileInfo, error) {
	ownerPath := filepath.Join(lockPath, "owner")
	info, err := os.Lstat(ownerPath)
	if err != nil {
		return compositionBuildLockOwner{}, nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return compositionBuildLockOwner{}, nil, fmt.Errorf("Quartet composition lock owner is not a regular non-symlink file: %s", ownerPath)
	}
	file, err := os.Open(ownerPath)
	if err != nil {
		return compositionBuildLockOwner{}, nil, err
	}
	defer file.Close()

	owner := compositionBuildLockOwner{}
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 1024), 16*1024)
	for scanner.Scan() {
		key, value, ok := strings.Cut(scanner.Text(), "=")
		if !ok {
			continue
		}
		switch strings.TrimSpace(key) {
		case "pid":
			owner.PID, _ = strconv.Atoi(strings.TrimSpace(value))
		case "started":
			owner.Started = strings.TrimSpace(value)
		case "token":
			owner.Token = strings.TrimSpace(value)
		case "hostname":
			owner.Hostname = strings.TrimSpace(value)
		case "executable":
			owner.Executable = strings.TrimSpace(value)
		}
	}
	if err := scanner.Err(); err != nil {
		return compositionBuildLockOwner{}, nil, err
	}
	return owner, info, nil
}

func releaseCompositionBuildLock(lock compositionBuildLock) {
	if lock.Path == "" || lock.Token == "" {
		return
	}
	owner, _, err := readCompositionBuildLockOwner(lock.Path)
	if err != nil || owner.Token != lock.Token {
		return
	}
	_ = os.RemoveAll(lock.Path)
}

func summarizeCompositionBuildLockOwner(owner compositionBuildLockOwner) string {
	values := []string{fmt.Sprintf("pid=%d", owner.PID)}
	if owner.Started != "" {
		values = append(values, "started="+owner.Started)
	}
	if owner.Hostname != "" {
		values = append(values, "hostname="+owner.Hostname)
	}
	if owner.Executable != "" {
		values = append(values, "executable="+owner.Executable)
	}
	return strings.Join(values, ",")
}

func compositionLockAge(modified, now time.Time) time.Duration {
	if modified.After(now) {
		return 0
	}
	return now.Sub(modified)
}

func localCompositionHostname() string {
	hostname, err := os.Hostname()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(hostname)
}
