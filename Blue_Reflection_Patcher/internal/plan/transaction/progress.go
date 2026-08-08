package transaction

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

// ProgressEvent reports byte-accurate progress for a transaction operation.
// Overall progress includes the verification and installation/restore I/O that
// the transaction engine performs for every managed file.
type ProgressEvent struct {
	Operation         string
	Phase             string
	FileIndex         int
	FileCount         int
	RelativePath      string
	FileBytesDone     int64
	FileBytesTotal    int64
	OverallBytesDone  int64
	OverallBytesTotal int64
}

// ProgressFunc receives transaction progress updates. Callbacks must return
// quickly; transaction I/O is performed synchronously.
type ProgressFunc func(ProgressEvent)

type progressPlan struct {
	targetBytes int64
	sourceBytes int64
	backupBytes int64
}

type progressTracker struct {
	operation string
	journal   Journal
	callback  ProgressFunc
	plans     []progressPlan
	total     int64
	completed int64
}

type prepareProgressPlan struct {
	relativePath   string
	candidateBytes int64
	targetBytes    int64
}

type prepareProgressTracker struct {
	callback  ProgressFunc
	plans     []prepareProgressPlan
	total     int64
	completed int64
}

func newPrepareProgressTracker(gameRoot string, changes []ChangeSpec, callback ProgressFunc) *prepareProgressTracker {
	t := &prepareProgressTracker{callback: callback, plans: make([]prepareProgressPlan, len(changes))}
	for index, change := range changes {
		relative := filepath.ToSlash(strings.TrimSpace(change.RelativePath))
		target := filepath.Join(gameRoot, filepath.FromSlash(relative))
		plan := prepareProgressPlan{
			relativePath:   relative,
			candidateBytes: regularFileSize(change.StagedPath),
			targetBytes:    regularFileSize(target),
		}
		// Prepare performs one candidate verification, one staging transfer,
		// one staged verification, one current-target verification, one backup
		// transfer and one backup verification. Metadata-only clone/link phases
		// are counted as completed instantly when no byte copy is required.
		t.total += 3*plan.candidateBytes + 4*plan.targetBytes
		t.plans[index] = plan
	}
	return t
}

func (t *prepareProgressTracker) phaseTotal(index int, phase string) int64 {
	if t == nil || index < 0 || index >= len(t.plans) {
		return 0
	}
	plan := t.plans[index]
	switch phase {
	case "verify_candidate", "stage", "verify_staged":
		return plan.candidateBytes
	case "verify_current", "verify_backup_source", "backup", "verify_backup":
		return plan.targetBytes
	default:
		return 0
	}
}

func (t *prepareProgressTracker) emit(index int, phase string, done, total int64) {
	if t == nil || t.callback == nil {
		return
	}
	if done < 0 {
		done = 0
	}
	if total < 0 {
		total = 0
	}
	if total > 0 && done > total {
		done = total
	}
	overall := t.completed + done
	if t.total > 0 && overall > t.total {
		overall = t.total
	}
	relative := ""
	if index >= 0 && index < len(t.plans) {
		relative = t.plans[index].relativePath
	}
	t.callback(ProgressEvent{
		Operation:         "prepare",
		Phase:             phase,
		FileIndex:         index + 1,
		FileCount:         len(t.plans),
		RelativePath:      relative,
		FileBytesDone:     done,
		FileBytesTotal:    total,
		OverallBytesDone:  overall,
		OverallBytesTotal: t.total,
	})
}

func (t *prepareProgressTracker) finishPhase(index int, phase string) {
	total := t.phaseTotal(index, phase)
	t.emit(index, phase, total, total)
	t.completed += total
	if t.completed > t.total {
		t.completed = t.total
	}
}

func (t *prepareProgressTracker) skipPhase(index int, phase string) {
	t.finishPhase(index, phase)
}

func (t *prepareProgressTracker) hashFile(index int, path, phase string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	total := t.phaseTotal(index, phase)
	if total == 0 {
		if info, statErr := file.Stat(); statErr == nil {
			total = info.Size()
		}
	}
	t.emit(index, phase, 0, total)
	hash := sha256.New()
	buffer := make([]byte, 4*1024*1024)
	var done int64
	for {
		n, readErr := file.Read(buffer)
		if n > 0 {
			if _, err := hash.Write(buffer[:n]); err != nil {
				return "", err
			}
			done += int64(n)
			t.emit(index, phase, done, total)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return "", readErr
		}
	}
	t.finishPhase(index, phase)
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func (t *prepareProgressTracker) copyVerified(index int, source, destination string, mode fs.FileMode, expectedSHA256, phase string) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return err
	}
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = output.Close()
		if !ok {
			_ = os.Remove(destination)
		}
	}()
	total := t.phaseTotal(index, phase)
	t.emit(index, phase, 0, total)
	hash := sha256.New()
	buffer := make([]byte, 4*1024*1024)
	var done int64
	for {
		n, readErr := input.Read(buffer)
		if n > 0 {
			if _, err := output.Write(buffer[:n]); err != nil {
				return err
			}
			if _, err := hash.Write(buffer[:n]); err != nil {
				return err
			}
			done += int64(n)
			t.emit(index, phase, done, total)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	if actual := hex.EncodeToString(hash.Sum(nil)); actual != expectedSHA256 {
		return fmt.Errorf("copied payload hash mismatch")
	}
	if err := output.Sync(); err != nil {
		return err
	}
	if err := output.Close(); err != nil {
		return err
	}
	t.finishPhase(index, phase)
	ok = true
	return syncParent(destination)
}

func (t *prepareProgressTracker) finish() {
	if t == nil || t.callback == nil {
		return
	}
	index := len(t.plans) - 1
	if index < 0 {
		index = 0
	}
	t.completed = t.total
	t.emit(index, "complete", 1, 1)
}

func newProgressTracker(operation string, journal Journal, callback ProgressFunc) *progressTracker {
	t := &progressTracker{operation: operation, journal: journal, callback: callback, plans: make([]progressPlan, len(journal.Files))}
	for index, record := range journal.Files {
		target, staged, backup, err := resolveRecordPaths(journal, record)
		if err != nil {
			continue
		}
		plan := progressPlan{targetBytes: regularFileSize(target)}
		switch operation {
		case "commit":
			plan.sourceBytes = regularFileSize(staged)
			t.total += plan.targetBytes + plan.sourceBytes
		case "rollback":
			if record.OriginalExisted {
				plan.backupBytes = regularFileSize(backup)
			}
			t.total += plan.targetBytes + plan.backupBytes + plan.backupBytes
		}
		t.plans[index] = plan
	}
	return t
}

func regularFileSize(path string) int64 {
	info, err := os.Lstat(path)
	if err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return 0
	}
	return info.Size()
}

func (t *progressTracker) phaseTotal(index int, phase string) int64 {
	if index < 0 || index >= len(t.plans) {
		return 0
	}
	plan := t.plans[index]
	switch phase {
	case "verify_current":
		return plan.targetBytes
	case "install":
		return plan.sourceBytes
	case "verify_backup", "restore":
		return plan.backupBytes
	default:
		return 0
	}
}

func (t *progressTracker) emit(index int, phase string, done, total int64) {
	if t == nil || t.callback == nil {
		return
	}
	if done < 0 {
		done = 0
	}
	if total < 0 {
		total = 0
	}
	if done > total && total > 0 {
		done = total
	}
	overall := t.completed + done
	if overall > t.total && t.total > 0 {
		overall = t.total
	}
	relative := ""
	if index >= 0 && index < len(t.journal.Files) {
		relative = t.journal.Files[index].RelativePath
	}
	t.callback(ProgressEvent{
		Operation: t.operation, Phase: phase,
		FileIndex: index + 1, FileCount: len(t.journal.Files), RelativePath: relative,
		FileBytesDone: done, FileBytesTotal: total,
		OverallBytesDone: overall, OverallBytesTotal: t.total,
	})
}

func (t *progressTracker) finishPhase(index int, phase string) {
	total := t.phaseTotal(index, phase)
	t.emit(index, phase, total, total)
	t.completed += total
	if t.completed > t.total {
		t.completed = t.total
	}
}

func (t *progressTracker) skipPhase(index int, phase string) {
	t.finishPhase(index, phase)
}

func (t *progressTracker) finish() {
	if t == nil || t.callback == nil {
		return
	}
	index := len(t.journal.Files) - 1
	if index < 0 {
		index = 0
	}
	t.completed = t.total
	t.emit(index, "complete", 1, 1)
}

func (t *progressTracker) hashFile(index int, path, phase string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	total := t.phaseTotal(index, phase)
	if total == 0 {
		if info, statErr := file.Stat(); statErr == nil {
			total = info.Size()
		}
	}
	t.emit(index, phase, 0, total)
	hash := sha256.New()
	buffer := make([]byte, 4*1024*1024)
	var done int64
	for {
		n, readErr := file.Read(buffer)
		if n > 0 {
			if _, err := hash.Write(buffer[:n]); err != nil {
				return "", err
			}
			done += int64(n)
			t.emit(index, phase, done, total)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return "", readErr
		}
	}
	t.finishPhase(index, phase)
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func (t *progressTracker) currentRegularHash(index int, path, phase string) (string, bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		t.skipPhase(index, phase)
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", false, fmt.Errorf("transaction target is not a regular file: %s", path)
	}
	hash, err := t.hashFile(index, path, phase)
	return hash, true, err
}

func (t *progressTracker) atomicInstallVerified(index int, source, destination string, mode fs.FileMode, expectedSHA256, phase string) (string, error) {
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return "", err
	}
	temp, err := os.CreateTemp(filepath.Dir(destination), ".brpatch-*")
	if err != nil {
		return "", err
	}
	tempPath := temp.Name()
	if err := temp.Close(); err != nil {
		_ = os.Remove(tempPath)
		return "", err
	}
	if err := os.Remove(tempPath); err != nil {
		return "", err
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(tempPath)
		}
	}()

	input, err := regularFile(source, "verified transaction source")
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(expectedSHA256) == "" {
		return "", fmt.Errorf("expected SHA-256 is empty")
	}
	cloned, err := tryReflinkRegularFile(input, tempPath, mode)
	if err != nil {
		return "", err
	}
	storageMethod := "reflink"
	if cloned {
		actual, err := t.hashFile(index, tempPath, phase)
		if err != nil {
			return "", err
		}
		if actual != expectedSHA256 {
			return "", fmt.Errorf("reflinked payload hash mismatch")
		}
	} else {
		storageMethod = "copy"
		if err := t.copyRegularFileVerified(index, input, tempPath, mode, expectedSHA256, phase); err != nil {
			return "", err
		}
	}
	if err := os.Rename(tempPath, destination); err != nil {
		return "", err
	}
	ok = true
	if err := syncParent(destination); err != nil {
		return "", err
	}
	return storageMethod, nil
}

func (t *progressTracker) copyRegularFileVerified(index int, source, destination string, mode fs.FileMode, expectedSHA256, phase string) error {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return err
	}
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = output.Close()
		if !ok {
			_ = os.Remove(destination)
		}
	}()
	total := t.phaseTotal(index, phase)
	t.emit(index, phase, 0, total)
	hash := sha256.New()
	buffer := make([]byte, 4*1024*1024)
	var done int64
	for {
		n, readErr := input.Read(buffer)
		if n > 0 {
			if _, err := output.Write(buffer[:n]); err != nil {
				return err
			}
			if _, err := hash.Write(buffer[:n]); err != nil {
				return err
			}
			done += int64(n)
			t.emit(index, phase, done, total)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	if actual := hex.EncodeToString(hash.Sum(nil)); actual != expectedSHA256 {
		return fmt.Errorf("copied payload hash mismatch")
	}
	if err := output.Sync(); err != nil {
		return err
	}
	if err := output.Close(); err != nil {
		return err
	}
	t.finishPhase(index, phase)
	ok = true
	return syncParent(destination)
}
