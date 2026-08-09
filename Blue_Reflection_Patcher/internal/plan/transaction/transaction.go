package transaction

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/archivepolicy"
	"local/blue-reflection-patcher/internal/plan/gamepath"
)

const (
	JournalType          = "br_file_transaction"
	JournalFormatVersion = 1
)

const (
	StatusPrepared    = "prepared"
	StatusCommitting  = "committing"
	StatusCommitted   = "committed"
	StatusRollingBack = "rolling_back"
	StatusRolledBack  = "rolled_back"
	StatusDiscarded   = "discarded"
)

type ChangeSpec struct {
	RelativePath           string
	StagedPath             string
	VerifiedBackupPath     string
	ExpectedOriginalSHA256 string
	// ExpectedOriginalSHA256 is an optional metadata-only active-state guard.
	// Prepare compares it with the SHA-256 it already computes for the live
	// target before making a rollback backup; it never adds another full read.
	// DesiredSHA256/DesiredBytes may be supplied by a caller that has just
	// verified a private candidate artifact. Prepare still verifies the live
	// target and commit still verifies the staged bytes while installing them.
	DesiredSHA256 string
	DesiredBytes  int64
}

type FileRecord struct {
	RelativePath           string `json:"relative_path"`
	OriginalExisted        bool   `json:"original_existed"`
	OriginalSHA256         string `json:"original_sha256,omitempty"`
	DesiredSHA256          string `json:"desired_sha256"`
	OriginalMode           uint32 `json:"original_mode,omitempty"`
	BackupPath             string `json:"backup_path,omitempty"`
	BackupStorageMethod    string `json:"backup_storage_method,omitempty"`
	StagedPath             string `json:"staged_path"`
	StagedStorageMethod    string `json:"staged_storage_method,omitempty"`
	InstalledStorageMethod string `json:"installed_storage_method,omitempty"`
	CommitState            string `json:"commit_state"`
	RollbackState          string `json:"rollback_state"`
}

type Journal struct {
	Type            string            `json:"type"`
	FormatVersion   int               `json:"format_version"`
	TransactionID   string            `json:"transaction_id"`
	Status          string            `json:"status"`
	CreatedUTC      time.Time         `json:"created_utc"`
	UpdatedUTC      time.Time         `json:"updated_utc"`
	GameRoot        string            `json:"game_root"`
	TransactionRoot string            `json:"transaction_root"`
	BackupRoot      string            `json:"backup_root,omitempty"`
	SelectedModules []string          `json:"selected_modules"`
	Files           []FileRecord      `json:"files"`
	Metadata        map[string]string `json:"metadata,omitempty"`
}

type Prepared struct {
	JournalPath string
	Journal     Journal
}

type PrepareOptions struct {
	Progress                        ProgressFunc
	RequireReflinkStaging           bool
	RequireHardlinkBackup           bool
	UseGameFilesystemBackupStore    bool
	UseSiblingFilesystemBackupStore bool
}

func NewID(now time.Time) (string, error) {
	var random [6]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", fmt.Errorf("generate transaction id: %w", err)
	}
	return now.UTC().Format("20060102T150405Z") + "-" + hex.EncodeToString(random[:]), nil
}

func Prepare(gameRoot, stateRoot string, changes []ChangeSpec, selectedModules []string, metadata map[string]string) (Prepared, error) {
	return PrepareWithOptions(gameRoot, stateRoot, changes, selectedModules, metadata, PrepareOptions{})
}

func PrepareWithProgress(gameRoot, stateRoot string, changes []ChangeSpec, selectedModules []string, metadata map[string]string, progress ProgressFunc) (Prepared, error) {
	return PrepareWithOptions(gameRoot, stateRoot, changes, selectedModules, metadata, PrepareOptions{Progress: progress})
}

func PrepareWithOptions(gameRoot, stateRoot string, changes []ChangeSpec, selectedModules []string, metadata map[string]string, options PrepareOptions) (Prepared, error) {
	progress := options.Progress
	if len(changes) == 0 {
		return Prepared{}, fmt.Errorf("transaction requires at least one file change")
	}
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return Prepared{}, err
	}
	stateRoot, err = filepath.Abs(stateRoot)
	if err != nil {
		return Prepared{}, fmt.Errorf("resolve state root: %w", err)
	}
	id, err := NewID(time.Now())
	if err != nil {
		return Prepared{}, err
	}
	transactionRoot := filepath.Join(stateRoot, "transactions", id)
	if err := os.MkdirAll(filepath.Dir(transactionRoot), 0o755); err != nil {
		return Prepared{}, fmt.Errorf("create transaction parent: %w", err)
	}
	if err := os.Mkdir(transactionRoot, 0o700); err != nil {
		return Prepared{}, fmt.Errorf("create transaction root: %w", err)
	}
	backupRoot := ""
	if options.UseGameFilesystemBackupStore && options.UseSiblingFilesystemBackupStore {
		_ = os.RemoveAll(transactionRoot)
		return Prepared{}, fmt.Errorf("multiple external backup store policies requested")
	}
	if options.UseGameFilesystemBackupStore {
		backupRoot = legacyGameFilesystemBackupRoot(gameRoot, id)
	}
	if options.UseSiblingFilesystemBackupStore {
		backupRoot = siblingFilesystemBackupRoot(gameRoot, id)
	}
	if backupRoot != "" {
		backupParent := filepath.Dir(backupRoot)
		if err := os.MkdirAll(backupParent, 0o700); err != nil {
			_ = os.RemoveAll(transactionRoot)
			return Prepared{}, fmt.Errorf("create external backup parent: %w", err)
		}
		info, err := os.Lstat(backupParent)
		if err != nil {
			_ = os.RemoveAll(transactionRoot)
			return Prepared{}, fmt.Errorf("inspect external backup parent: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			_ = os.RemoveAll(transactionRoot)
			return Prepared{}, fmt.Errorf("external backup parent must be a real directory: %s", backupParent)
		}
		if err := os.Mkdir(backupRoot, 0o700); err != nil {
			_ = os.RemoveAll(transactionRoot)
			return Prepared{}, fmt.Errorf("create external backup root: %w", err)
		}
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(transactionRoot)
			if backupRoot != "" {
				_ = os.RemoveAll(backupRoot)
			}
		}
	}()

	ordered := append([]ChangeSpec(nil), changes...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].RelativePath < ordered[j].RelativePath })
	tracker := newPrepareProgressTracker(gameRoot, ordered, options, progress)
	seen := map[string]bool{}
	records := make([]FileRecord, 0, len(ordered))
	for index, change := range ordered {
		relative, err := cleanRelativePath(change.RelativePath)
		if err != nil {
			return Prepared{}, err
		}
		key := strings.ToLower(filepath.ToSlash(relative))
		if seen[key] {
			return Prepared{}, fmt.Errorf("duplicate transaction path: %s", relative)
		}
		seen[key] = true
		target, err := secureGameJoin(gameRoot, relative)
		if err != nil {
			return Prepared{}, err
		}
		stagedSource, err := regularFile(change.StagedPath, "staged file")
		if err != nil {
			return Prepared{}, err
		}
		desiredHash := strings.ToLower(strings.TrimSpace(change.DesiredSHA256))
		if desiredHash != "" {
			if len(desiredHash) != 64 {
				return Prepared{}, fmt.Errorf("invalid trusted candidate SHA-256 for %s", relative)
			}
			if _, err := hex.DecodeString(desiredHash); err != nil {
				return Prepared{}, fmt.Errorf("invalid trusted candidate SHA-256 for %s", relative)
			}
			if info, err := os.Stat(stagedSource); err != nil {
				return Prepared{}, err
			} else if change.DesiredBytes > 0 && info.Size() != change.DesiredBytes {
				return Prepared{}, fmt.Errorf("trusted candidate size drift: %s", relative)
			}
			tracker.skipPhase(index, "verify_candidate")
		} else {
			var err error
			desiredHash, err = tracker.hashFile(index, stagedSource, "verify_candidate")
			if err != nil {
				return Prepared{}, err
			}
		}
		stagedRelative := filepath.Join("staged", relative)
		stagedCopy := filepath.Join(transactionRoot, stagedRelative)
		if err := os.MkdirAll(filepath.Dir(stagedCopy), 0o700); err != nil {
			return Prepared{}, fmt.Errorf("stage %s: %w", relative, err)
		}
		cloned, err := tryReflinkRegularFile(stagedSource, stagedCopy, 0o600)
		if err != nil {
			return Prepared{}, fmt.Errorf("stage %s: %w", relative, err)
		}
		stagedStorageMethod := "reflink"
		if cloned {
			tracker.skipPhase(index, "stage")
		} else {
			if options.RequireReflinkStaging {
				return Prepared{}, fmt.Errorf("stage %s: reflink is required by prepare policy", relative)
			}
			stagedStorageMethod = "copy"
			if err := tracker.copyVerified(index, stagedSource, stagedCopy, 0o600, desiredHash, "stage"); err != nil {
				return Prepared{}, fmt.Errorf("stage %s: %w", relative, err)
			}
		}
		// Staging is either a filesystem clone of the just-verified private
		// candidate or a copy whose SHA-256 is checked while bytes are written.
		// Re-reading the complete staged file here adds no independent boundary.
		tracker.skipPhase(index, "verify_staged")

		record := FileRecord{
			RelativePath:        filepath.ToSlash(relative),
			DesiredSHA256:       desiredHash,
			StagedPath:          filepath.ToSlash(stagedRelative),
			StagedStorageMethod: stagedStorageMethod,
			CommitState:         "pending",
			RollbackState:       "pending",
		}
		info, statErr := os.Lstat(target)
		switch {
		case statErr == nil:
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				return Prepared{}, fmt.Errorf("target is not a regular file: %s", target)
			}
			record.OriginalExisted = true
			record.OriginalMode = uint32(info.Mode().Perm())
			record.OriginalSHA256, err = tracker.hashFile(index, target, "verify_current")
			if err != nil {
				return Prepared{}, err
			}
			expectedOriginal := strings.ToLower(strings.TrimSpace(change.ExpectedOriginalSHA256))
			if expectedOriginal != "" {
				if len(expectedOriginal) != 64 {
					return Prepared{}, fmt.Errorf("invalid expected current SHA-256 for %s", relative)
				}
				if _, err := hex.DecodeString(expectedOriginal); err != nil {
					return Prepared{}, fmt.Errorf("invalid expected current SHA-256 for %s", relative)
				}
				if record.OriginalSHA256 != expectedOriginal {
					return Prepared{}, fmt.Errorf("managed target changed before update: %s", relative)
				}
			}
			backupRelative := filepath.Join("backup", relative)
			backupBase := transactionRoot
			if backupRoot != "" {
				backupBase = backupRoot
			}
			backup := filepath.Join(backupBase, backupRelative)
			backupSource := target
			if strings.TrimSpace(change.VerifiedBackupPath) != "" {
				verified, verifyErr := regularFile(change.VerifiedBackupPath, "verified persistent baseline")
				if verifyErr != nil {
					return Prepared{}, verifyErr
				}
				verifiedHash, verifyErr := tracker.hashFile(index, verified, "verify_backup_source")
				if verifyErr != nil {
					return Prepared{}, verifyErr
				}
				if verifiedHash != record.OriginalSHA256 {
					return Prepared{}, fmt.Errorf("persistent baseline does not match current target: %s", relative)
				}
				backupSource = verified
			} else {
				tracker.skipPhase(index, "verify_backup_source")
			}
			if err := os.MkdirAll(filepath.Dir(backup), 0o700); err != nil {
				return Prepared{}, fmt.Errorf("backup %s: %w", relative, err)
			}
			backupStorageMethod := "hardlink"
			if err := os.Link(backupSource, backup); err == nil {
				tracker.skipPhase(index, "backup")
			} else {
				if options.RequireHardlinkBackup {
					return Prepared{}, fmt.Errorf("backup %s: hardlink is required by prepare policy", relative)
				}
				cloned, cloneErr := tryReflinkRegularFile(backupSource, backup, info.Mode().Perm())
				if cloneErr != nil {
					return Prepared{}, fmt.Errorf("backup %s: %w", relative, cloneErr)
				}
				backupStorageMethod = "reflink"
				if cloned {
					tracker.skipPhase(index, "backup")
				} else {
					backupStorageMethod = "copy"
					if err := tracker.copyVerified(index, backupSource, backup, info.Mode().Perm(), record.OriginalSHA256, "backup"); err != nil {
						return Prepared{}, fmt.Errorf("backup %s: %w", relative, err)
					}
				}
			}
			// A hardlink is the exact inode that was just hashed; a successful
			// reflink is an exact copy-on-write clone; a fallback copy is hashed
			// during transfer. Avoid a second full read of the rollback copy.
			backupInfo, statErr := os.Stat(backup)
			if statErr != nil || !backupInfo.Mode().IsRegular() || backupInfo.Size() != info.Size() {
				if statErr == nil {
					statErr = fmt.Errorf("rollback backup size/type mismatch")
				}
				return Prepared{}, fmt.Errorf("verify backup %s: %w", relative, statErr)
			}
			if backupStorageMethod == "hardlink" {
				sourceInfo, sourceStatErr := os.Stat(backupSource)
				if sourceStatErr != nil || !os.SameFile(sourceInfo, backupInfo) {
					if sourceStatErr == nil {
						sourceStatErr = fmt.Errorf("rollback hardlink does not reference the verified source inode")
					}
					return Prepared{}, fmt.Errorf("verify backup %s: %w", relative, sourceStatErr)
				}
			}
			tracker.skipPhase(index, "verify_backup")
			record.BackupPath = filepath.ToSlash(backupRelative)
			record.BackupStorageMethod = backupStorageMethod
		case errors.Is(statErr, os.ErrNotExist):
			if strings.TrimSpace(change.ExpectedOriginalSHA256) != "" {
				return Prepared{}, fmt.Errorf("managed target disappeared before update: %s", relative)
			}
			record.OriginalExisted = false
			tracker.skipPhase(index, "verify_current")
			tracker.skipPhase(index, "verify_backup_source")
			tracker.skipPhase(index, "backup")
			tracker.skipPhase(index, "verify_backup")
		case statErr != nil:
			return Prepared{}, fmt.Errorf("inspect target %s: %w", target, statErr)
		}
		records = append(records, record)
	}

	now := time.Now().UTC()
	journal := Journal{
		Type: JournalType, FormatVersion: JournalFormatVersion,
		TransactionID: id, Status: StatusPrepared, CreatedUTC: now, UpdatedUTC: now,
		GameRoot: gameRoot, TransactionRoot: transactionRoot, BackupRoot: backupRoot,
		SelectedModules: sortedUnique(selectedModules), Files: records,
		Metadata: cloneMetadata(metadata),
	}
	journalPath := filepath.Join(transactionRoot, "journal.json")
	if err := writeJournal(journalPath, journal); err != nil {
		return Prepared{}, err
	}
	cleanup = false
	tracker.finish()
	return Prepared{JournalPath: journalPath, Journal: journal}, nil
}

func ValidatePrepared(journalPath string) (Journal, error) {
	journal, err := Load(journalPath)
	if err != nil {
		return Journal{}, err
	}
	if journal.Status != StatusPrepared {
		return Journal{}, fmt.Errorf("cannot validate prepared transaction in status %s", journal.Status)
	}
	for _, record := range journal.Files {
		target, staged, backup, err := resolveRecordPaths(journal, record)
		if err != nil {
			return Journal{}, err
		}
		currentHash, exists, err := currentRegularHash(target)
		if err != nil {
			return Journal{}, err
		}
		if record.OriginalExisted {
			if !exists || currentHash != record.OriginalSHA256 {
				return Journal{}, fmt.Errorf("target changed after prepare: %s", record.RelativePath)
			}
			backupHash, err := hashFile(backup)
			if err != nil {
				return Journal{}, err
			}
			if backupHash != record.OriginalSHA256 {
				return Journal{}, fmt.Errorf("backup changed: %s", record.RelativePath)
			}
		} else if exists {
			return Journal{}, fmt.Errorf("new target appeared after prepare: %s", record.RelativePath)
		}
		stagedHash, err := hashFile(staged)
		if err != nil {
			return Journal{}, err
		}
		if stagedHash != record.DesiredSHA256 {
			return Journal{}, fmt.Errorf("staged payload changed: %s", record.RelativePath)
		}
	}
	return journal, nil
}

func DiscardPrepared(journalPath string) (Journal, error) {
	journal, err := ValidatePrepared(journalPath)
	if err != nil {
		return Journal{}, err
	}
	staged, err := secureJoin(journal.TransactionRoot, "staged")
	if err != nil {
		return Journal{}, err
	}
	if err := os.RemoveAll(staged); err != nil {
		return Journal{}, fmt.Errorf("remove transaction staged payloads: %w", err)
	}
	if journal.BackupRoot != "" {
		if err := os.RemoveAll(journal.BackupRoot); err != nil {
			return Journal{}, fmt.Errorf("remove external transaction backups: %w", err)
		}
	} else {
		backup, err := secureJoin(journal.TransactionRoot, "backup")
		if err != nil {
			return Journal{}, err
		}
		if err := os.RemoveAll(backup); err != nil {
			return Journal{}, fmt.Errorf("remove transaction backups: %w", err)
		}
	}
	for index := range journal.Files {
		journal.Files[index].CommitState = "discarded"
		journal.Files[index].RollbackState = "not_needed"
	}
	journal.Status = StatusDiscarded
	journal.UpdatedUTC = time.Now().UTC()
	if err := writeJournal(journalPath, journal); err != nil {
		return Journal{}, err
	}
	return journal, nil
}

// UpdatePreparedMetadata atomically augments metadata for a prepared transaction.
// It is used when a durable rollback source is created by Prepare itself and the
// persistent baseline manifest is published immediately afterwards. Game files
// are still untouched at this point.
func UpdatePreparedMetadata(journalPath string, updates map[string]string) (Journal, error) {
	journal, err := Load(journalPath)
	if err != nil {
		return Journal{}, err
	}
	if journal.Status != StatusPrepared {
		return Journal{}, fmt.Errorf("cannot update transaction metadata in status %s", journal.Status)
	}
	if journal.Metadata == nil {
		journal.Metadata = map[string]string{}
	}
	for key, value := range updates {
		key = strings.TrimSpace(key)
		if key == "" {
			return Journal{}, fmt.Errorf("transaction metadata key is empty")
		}
		journal.Metadata[key] = value
	}
	if err := writeJournal(journalPath, journal); err != nil {
		return Journal{}, err
	}
	return journal, nil
}

func PruneCommittedStaged(journalPath string) error {
	journal, err := Load(journalPath)
	if err != nil {
		return err
	}
	if journal.Status != StatusCommitted {
		return fmt.Errorf("cannot prune staged payload for transaction in status %s", journal.Status)
	}
	staged, err := secureJoin(journal.TransactionRoot, "staged")
	if err != nil {
		return err
	}
	if err := os.RemoveAll(staged); err != nil {
		return fmt.Errorf("remove committed staged payloads: %w", err)
	}
	return syncParent(staged)
}

func Commit(journalPath string) (Journal, error) {
	return CommitWithProgress(journalPath, nil)
}

func CommitWithProgress(journalPath string, progress ProgressFunc) (Journal, error) {
	journal, err := Load(journalPath)
	if err != nil {
		return Journal{}, err
	}
	if journal.Status == StatusCommitted {
		return journal, nil
	}
	if journal.Status != StatusPrepared && journal.Status != StatusCommitting {
		return Journal{}, fmt.Errorf("cannot commit transaction in status %s", journal.Status)
	}
	tracker := newProgressTracker("commit", journal, progress)
	journal.Status = StatusCommitting
	if err := writeJournal(journalPath, journal); err != nil {
		return Journal{}, err
	}
	for index := range journal.Files {
		record := &journal.Files[index]
		target, staged, _, err := resolveRecordPaths(journal, *record)
		if err != nil {
			return journal, err
		}
		currentHash, exists, err := tracker.currentRegularHash(index, target, "verify_current")
		if err != nil {
			return journal, err
		}
		if exists && currentHash == record.DesiredSHA256 {
			tracker.skipPhase(index, "install")
			record.InstalledStorageMethod = "already_present"
			record.CommitState = "committed"
			journal.UpdatedUTC = time.Now().UTC()
			if err := writeJournal(journalPath, journal); err != nil {
				return journal, err
			}
			continue
		}
		if record.OriginalExisted {
			if !exists || currentHash != record.OriginalSHA256 {
				return journal, fmt.Errorf("target changed after prepare: %s", record.RelativePath)
			}
		} else if exists {
			return journal, fmt.Errorf("new target appeared after prepare: %s", record.RelativePath)
		}
		mode := fs.FileMode(0o644)
		if record.OriginalExisted && record.OriginalMode != 0 {
			mode = fs.FileMode(record.OriginalMode)
		}
		installedStorageMethod, err := tracker.atomicInstallVerified(index, staged, target, mode, record.DesiredSHA256, "install")
		if err != nil {
			return journal, fmt.Errorf("commit %s: %w", record.RelativePath, err)
		}
		record.InstalledStorageMethod = installedStorageMethod
		record.CommitState = "committed"
		journal.UpdatedUTC = time.Now().UTC()
		if err := writeJournal(journalPath, journal); err != nil {
			return journal, err
		}
	}
	tracker.finish()
	journal.Status = StatusCommitted
	journal.UpdatedUTC = time.Now().UTC()
	if err := writeJournal(journalPath, journal); err != nil {
		return journal, err
	}
	return journal, nil
}

func Rollback(journalPath string) (Journal, error) {
	return RollbackWithProgress(journalPath, nil)
}

func RollbackWithProgress(journalPath string, progress ProgressFunc) (Journal, error) {
	journal, err := Load(journalPath)
	if err != nil {
		return Journal{}, err
	}
	if journal.Status == StatusRolledBack {
		return journal, nil
	}
	switch journal.Status {
	case StatusPrepared, StatusCommitting, StatusCommitted, StatusRollingBack:
	default:
		return Journal{}, fmt.Errorf("cannot roll back transaction in status %s", journal.Status)
	}
	tracker := newProgressTracker("rollback", journal, progress)
	journal.Status = StatusRollingBack
	journal.UpdatedUTC = time.Now().UTC()
	if err := writeJournal(journalPath, journal); err != nil {
		return Journal{}, err
	}
	for index := len(journal.Files) - 1; index >= 0; index-- {
		record := &journal.Files[index]
		target, _, backup, err := resolveRecordPaths(journal, *record)
		if err != nil {
			return journal, err
		}
		currentHash, exists, err := tracker.currentRegularHash(index, target, "verify_current")
		if err != nil {
			return journal, err
		}
		if record.OriginalExisted && exists && currentHash == record.OriginalSHA256 {
			tracker.skipPhase(index, "verify_backup")
			tracker.skipPhase(index, "restore")
			record.RollbackState = "already_restored"
			record.CommitState = "rolled_back"
			journal.UpdatedUTC = time.Now().UTC()
			if err := writeJournal(journalPath, journal); err != nil {
				return journal, err
			}
			continue
		}
		if !record.OriginalExisted && !exists {
			tracker.skipPhase(index, "verify_backup")
			tracker.skipPhase(index, "restore")
			record.RollbackState = "already_removed"
			record.CommitState = "rolled_back"
			journal.UpdatedUTC = time.Now().UTC()
			if err := writeJournal(journalPath, journal); err != nil {
				return journal, err
			}
			continue
		}
		if record.CommitState != "committed" && currentHash != record.DesiredSHA256 {
			tracker.skipPhase(index, "verify_backup")
			tracker.skipPhase(index, "restore")
			record.RollbackState = "not_needed"
			continue
		}
		if !exists || currentHash != record.DesiredSHA256 {
			return journal, fmt.Errorf("refusing rollback because target changed after commit: %s", record.RelativePath)
		}
		if record.OriginalExisted {
			// atomicInstallVerified validates the rollback source while materializing
			// the temporary replacement and refuses the rename on any hash mismatch.
			// Do not read the same multi-gigabyte backup once more immediately before it.
			tracker.skipPhase(index, "verify_backup")
			mode := fs.FileMode(record.OriginalMode)
			if mode == 0 {
				mode = 0o644
			}
			if _, err := tracker.atomicInstallVerified(index, backup, target, mode, record.OriginalSHA256, "restore"); err != nil {
				return journal, fmt.Errorf("restore %s: %w", record.RelativePath, err)
			}
			record.RollbackState = "restored"
		} else {
			tracker.skipPhase(index, "verify_backup")
			tracker.skipPhase(index, "restore")
			if err := os.Remove(target); err != nil && !errors.Is(err, os.ErrNotExist) {
				return journal, fmt.Errorf("remove added file %s: %w", record.RelativePath, err)
			}
			if err := syncParent(target); err != nil {
				return journal, err
			}
			record.RollbackState = "removed"
		}
		record.CommitState = "rolled_back"
		journal.UpdatedUTC = time.Now().UTC()
		if err := writeJournal(journalPath, journal); err != nil {
			return journal, err
		}
	}
	tracker.finish()
	journal.Status = StatusRolledBack
	journal.UpdatedUTC = time.Now().UTC()
	if err := writeJournal(journalPath, journal); err != nil {
		return journal, err
	}
	return journal, nil
}

func Load(journalPath string) (Journal, error) {
	path, err := regularFile(journalPath, "transaction journal")
	if err != nil {
		return Journal{}, err
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return Journal{}, err
	}
	var journal Journal
	if err := json.Unmarshal(data, &journal); err != nil {
		return Journal{}, fmt.Errorf("decode transaction journal: %w", err)
	}
	if journal.Type != JournalType || journal.FormatVersion != JournalFormatVersion {
		return Journal{}, fmt.Errorf("unsupported transaction journal type/version")
	}
	root, err := filepath.Abs(journal.TransactionRoot)
	if err != nil {
		return Journal{}, err
	}
	if root != filepath.Dir(path) {
		return Journal{}, fmt.Errorf("journal transaction root mismatch")
	}
	gameRoot, err := cleanExistingDirectory(journal.GameRoot, "journal game root")
	if err != nil {
		return Journal{}, err
	}
	journal.GameRoot = gameRoot
	journal.TransactionRoot = root
	if journal.BackupRoot != "" {
		actualBackupRoot, err := filepath.Abs(journal.BackupRoot)
		if err != nil {
			return Journal{}, err
		}
		legacyRoot, err := filepath.Abs(legacyGameFilesystemBackupRoot(gameRoot, journal.TransactionID))
		if err != nil {
			return Journal{}, err
		}
		siblingRoot, err := filepath.Abs(siblingFilesystemBackupRoot(gameRoot, journal.TransactionID))
		if err != nil {
			return Journal{}, err
		}
		actualBackupRoot = filepath.Clean(actualBackupRoot)
		if actualBackupRoot != filepath.Clean(legacyRoot) && actualBackupRoot != filepath.Clean(siblingRoot) {
			return Journal{}, fmt.Errorf("journal backup root mismatch")
		}
		journal.BackupRoot = actualBackupRoot
	}
	for _, record := range journal.Files {
		if _, err := cleanRelativePath(record.RelativePath); err != nil {
			return Journal{}, err
		}
	}
	return journal, nil
}

func legacyGameFilesystemBackupRoot(gameRoot, transactionID string) string {
	return filepath.Join(gameRoot, ".unburger-patcher", "transaction-backups", transactionID)
}

func siblingFilesystemBackupRoot(gameRoot, transactionID string) string {
	return filepath.Join(filepath.Dir(gameRoot), ".unburger-patcher-transaction-backups", filepath.Base(gameRoot), transactionID)
}

func resolveRecordPaths(journal Journal, record FileRecord) (string, string, string, error) {
	target, err := secureGameJoin(journal.GameRoot, record.RelativePath)
	if err != nil {
		return "", "", "", err
	}
	staged, err := secureJoin(journal.TransactionRoot, record.StagedPath)
	if err != nil {
		return "", "", "", err
	}
	backup := ""
	if record.BackupPath != "" {
		backupBase := journal.TransactionRoot
		if journal.BackupRoot != "" {
			backupBase = journal.BackupRoot
		}
		backup, err = secureJoin(backupBase, record.BackupPath)
		if err != nil {
			return "", "", "", err
		}
	}
	return target, staged, backup, nil
}

func writeJournal(path string, journal Journal) error {
	journal.UpdatedUTC = time.Now().UTC()
	data, err := json.MarshalIndent(journal, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return atomicWriteBytes(path, data, 0o600)
}

func cleanExistingDirectory(path, label string) (string, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", fmt.Errorf("resolve %s: %w", label, err)
	}
	info, err := os.Lstat(absolute)
	if err != nil {
		return "", fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return "", fmt.Errorf("%s must not be a symlink: %s", label, absolute)
	}
	if !info.IsDir() {
		return "", fmt.Errorf("%s is not a directory: %s", label, absolute)
	}
	return filepath.Clean(absolute), nil
}

func cleanRelativePath(path string) (string, error) {
	if strings.TrimSpace(path) == "" || filepath.IsAbs(path) {
		return "", fmt.Errorf("invalid transaction relative path: %q", path)
	}
	clean := filepath.Clean(filepath.FromSlash(path))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("transaction path escapes root: %q", path)
	}
	if err := archivepolicy.RejectAnalyticalArchivePath(clean, "transaction"); err != nil {
		return "", err
	}
	return clean, nil
}

func secureJoin(root, relative string) (string, error) {
	clean, err := cleanRelativePath(relative)
	if err != nil {
		return "", err
	}
	joined := filepath.Join(root, clean)
	rel, err := filepath.Rel(root, joined)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("path escapes root: %q", relative)
	}
	return joined, nil
}

func secureGameJoin(root, relative string) (string, error) {
	resolved, _, err := gamepath.Resolve(root, relative)
	if err != nil {
		return "", err
	}
	return resolved, nil
}

func regularFile(path, label string) (string, error) {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(absolute)
	if err != nil {
		return "", fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", fmt.Errorf("%s is not a regular file: %s", label, absolute)
	}
	return absolute, nil
}

func currentRegularHash(path string) (string, bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", false, fmt.Errorf("transaction target is not a regular file: %s", path)
	}
	hash, err := hashFile(path)
	return hash, true, err
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func linkCloneOrCopyRegularFile(source, destination string, mode fs.FileMode) (string, error) {
	input, err := regularFile(source, "backup source")
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return "", err
	}
	if err := os.Link(input, destination); err == nil {
		if err := syncParent(destination); err != nil {
			return "", err
		}
		return "hardlink", nil
	}
	return cloneOrCopyRegularFile(input, destination, mode)
}

func cloneOrCopyRegularFile(source, destination string, mode fs.FileMode) (string, error) {
	input, err := regularFile(source, "copy-on-write source")
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return "", err
	}
	cloned, err := tryReflinkRegularFile(input, destination, mode)
	if err != nil {
		return "", err
	}
	if cloned {
		return "reflink", nil
	}
	if err := copyRegularFile(input, destination, mode); err != nil {
		return "", err
	}
	return "copy", nil
}

func copyRegularFile(source, destination string, mode fs.FileMode) error {
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
	if _, err := io.Copy(output, input); err != nil {
		return err
	}
	if err := output.Sync(); err != nil {
		return err
	}
	if err := output.Close(); err != nil {
		return err
	}
	ok = true
	return syncParent(destination)
}

func cloneOrCopyRegularFileVerified(source, destination string, mode fs.FileMode, expectedSHA256 string) (string, error) {
	input, err := regularFile(source, "verified copy-on-write source")
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(expectedSHA256) == "" {
		return "", fmt.Errorf("expected SHA-256 is empty")
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return "", err
	}
	cloned, err := tryReflinkRegularFile(input, destination, mode)
	if err != nil {
		return "", err
	}
	if cloned {
		actual, err := hashFile(destination)
		if err != nil {
			_ = os.Remove(destination)
			return "", err
		}
		if actual != expectedSHA256 {
			_ = os.Remove(destination)
			return "", fmt.Errorf("reflinked payload hash mismatch")
		}
		return "reflink", nil
	}
	if err := copyRegularFileVerified(input, destination, mode, expectedSHA256); err != nil {
		return "", err
	}
	return "copy", nil
}

func copyRegularFileVerified(source, destination string, mode fs.FileMode, expectedSHA256 string) error {
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
	hash := sha256.New()
	if _, err := io.Copy(io.MultiWriter(output, hash), input); err != nil {
		return err
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
	ok = true
	return syncParent(destination)
}

func atomicInstallVerified(source, destination string, mode fs.FileMode, expectedSHA256 string) (string, error) {
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
	storageMethod, err := cloneOrCopyRegularFileVerified(source, tempPath, mode, expectedSHA256)
	if err != nil {
		return "", err
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

func atomicInstall(source, destination string, mode fs.FileMode) (string, error) {
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
	storageMethod, err := cloneOrCopyRegularFile(source, tempPath, mode)
	if err != nil {
		return "", err
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

func atomicWriteBytes(path string, data []byte, mode fs.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".journal-*")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	ok := false
	defer func() {
		_ = temp.Close()
		if !ok {
			_ = os.Remove(tempPath)
		}
	}()
	if err := temp.Chmod(mode); err != nil {
		return err
	}
	if _, err := temp.Write(data); err != nil {
		return err
	}
	if err := temp.Sync(); err != nil {
		return err
	}
	if err := temp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempPath, path); err != nil {
		return err
	}
	ok = true
	return syncParent(path)
}

func syncParent(path string) error {
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer directory.Close()
	if err := directory.Sync(); err != nil {
		// Directory fsync is not supported by Windows. The file itself has
		// already been synced before the atomic rename.
		if runtime.GOOS == "windows" || errors.Is(err, os.ErrInvalid) {
			return nil
		}
		return err
	}
	return nil
}

func sortedUnique(values []string) []string {
	seen := map[string]bool{}
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" && !seen[value] {
			seen[value] = true
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}

func cloneMetadata(values map[string]string) map[string]string {
	if len(values) == 0 {
		return nil
	}
	result := make(map[string]string, len(values))
	for key, value := range values {
		result[key] = value
	}
	return result
}
