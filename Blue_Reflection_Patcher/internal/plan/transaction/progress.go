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
	relativePath            string
	verifyCandidateBytes    int64
	stageBytes              int64
	targetBytes             int64
	verifyBackupSourceBytes int64
	backupBytes             int64
}

type prepareProgressTracker struct {
	callback  ProgressFunc
	plans     []prepareProgressPlan
	total     int64
	completed int64
}

func newPrepareProgressTracker(gameRoot string, changes []ChangeSpec, options PrepareOptions, callback ProgressFunc) *prepareProgressTracker {
	t := &prepareProgressTracker{callback: callback, plans: make([]prepareProgressPlan, len(changes))}
	for index, change := range changes {
		relative := filepath.ToSlash(strings.TrimSpace(change.RelativePath))
		target := filepath.Join(gameRoot, filepath.FromSlash(relative))
		candidateBytes := regularFileSize(change.StagedPath)
		targetBytes := regularFileSize(target)
		plan := prepareProgressPlan{
			relativePath: relative,
			stageBytes:   candidateBytes,
			targetBytes:  targetBytes,
		}
		if strings.TrimSpace(change.DesiredSHA256) == "" {
			plan.verifyCandidateBytes = candidateBytes
		}
		if strings.TrimSpace(change.VerifiedBackupPath) != "" {
			plan.verifyBackupSourceBytes = targetBytes
		}
		if !options.RequireHardlinkBackup {
			plan.backupBytes = targetBytes
		}
		t.total += plan.verifyCandidateBytes + plan.stageBytes + plan.targetBytes + plan.verifyBackupSourceBytes + plan.backupBytes
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
	case "verify_candidate":
		return plan.verifyCandidateBytes
	case "stage":
		return plan.stageBytes
	case "verify_staged", "verify_backup":
		return 0
	case "verify_current":
		return plan.targetBytes
	case "verify_backup_source":
		return plan.verifyBackupSourceBytes
	case "backup":
		return plan.backupBytes
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

// omitPhase removes work from the denominator when the filesystem completed a
// transfer without reading/writing the payload (hardlink/reflink). Unlike
// skipPhase, it must not pretend that multi-gigabyte I/O happened.
func (t *prepareProgressTracker) omitPhase(index int, phase string) {
	if t == nil || index < 0 || index >= len(t.plans) {
		return
	}
	amount := t.phaseTotal(index, phase)
	if amount <= 0 {
		t.emit(index, phase, 0, 0)
		return
	}
	plan := &t.plans[index]
	switch phase {
	case "verify_candidate":
		plan.verifyCandidateBytes = 0
	case "stage":
		plan.stageBytes = 0
	case "verify_current":
		plan.targetBytes = 0
	case "verify_backup_source":
		plan.verifyBackupSourceBytes = 0
	case "backup":
		plan.backupBytes = 0
	}
	t.total -= amount
	if t.total < t.completed {
		t.total = t.completed
	}
	t.emit(index, phase, 0, 0)
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
	if t.total == 0 {
		t.emit(index, "complete", 0, 0)
	} else {
		t.emit(index, "complete", 1, 1)
	}
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
			// The restore transfer verifies the backup bytes against OriginalSHA256
			// before the atomic rename. A separate full backup hash immediately
			// beforehand is redundant and doubles rollback read I/O.
			t.total += plan.targetBytes + plan.backupBytes
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
	case "restore":
		return plan.backupBytes
	case "verify_backup":
		return 0
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

func (t *progressTracker) omitPhase(index int, phase string) {
	if t == nil || index < 0 || index >= len(t.plans) {
		return
	}
	amount := t.phaseTotal(index, phase)
	if amount <= 0 {
		t.emit(index, phase, 0, 0)
		return
	}
	plan := &t.plans[index]
	switch phase {
	case "verify_current":
		plan.targetBytes = 0
	case "install":
		plan.sourceBytes = 0
	case "restore":
		plan.backupBytes = 0
	}
	t.total -= amount
	if t.total < t.completed {
		t.total = t.completed
	}
	t.emit(index, phase, 0, 0)
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
	if t.total == 0 {
		t.emit(index, "complete", 0, 0)
	} else {
		t.emit(index, "complete", 1, 1)
	}
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

// atomicInstallTrustedHardlink is used only by the same-process Prepare -> Commit
// fast path after both the live target and staged payload have been proven to be
// the exact same file identities/sizes/mtimes that Prepare hashed or created.
// A later/resumed process cannot take this path and falls back to SHA-256 I/O.
func (t *progressTracker) atomicInstallTrustedHardlink(index int, source, destination string, mode fs.FileMode, phase string) (string, bool, error) {
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return "", false, err
	}
	input, err := regularFile(source, "trusted transaction source")
	if err != nil {
		return "", false, err
	}
	temp, err := os.CreateTemp(filepath.Dir(destination), ".brpatch-link-*")
	if err != nil {
		return "", false, err
	}
	tempPath := temp.Name()
	if err := temp.Close(); err != nil {
		_ = os.Remove(tempPath)
		return "", false, err
	}
	if err := os.Remove(tempPath); err != nil {
		return "", false, err
	}
	if err := os.Link(input, tempPath); err != nil {
		return "", false, nil
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(tempPath)
		}
	}()
	srcInfo, err := os.Stat(input)
	if err != nil {
		return "", false, err
	}
	tmpInfo, err := os.Stat(tempPath)
	if err != nil {
		return "", false, err
	}
	if !os.SameFile(srcInfo, tmpInfo) || srcInfo.Size() != tmpInfo.Size() {
		return "", false, fmt.Errorf("trusted hardlink did not preserve source identity")
	}
	if err := os.Rename(tempPath, destination); err != nil {
		return "", false, err
	}
	ok = true
	if err := os.Chmod(destination, mode); err != nil {
		return "", false, err
	}
	if err := syncParent(destination); err != nil {
		return "", false, err
	}
	t.omitPhase(index, phase)
	return "hardlink", true, nil
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
	storageMethod := "hardlink"
	if linkErr := os.Link(input, tempPath); linkErr == nil {
		actual, hashErr := t.hashFile(index, tempPath, phase)
		if hashErr != nil {
			return "", hashErr
		}
		if actual != expectedSHA256 {
			return "", fmt.Errorf("hardlinked payload hash mismatch")
		}
	} else {
		cloned, err := tryReflinkRegularFile(input, tempPath, mode)
		if err != nil {
			return "", err
		}
		storageMethod = "reflink"
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
