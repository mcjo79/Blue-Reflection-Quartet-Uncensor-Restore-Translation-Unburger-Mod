package installstate

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/gamepath"

	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

const (
	StateType          = "br_active_installation_state"
	StateFormatVersion = 1
	StatusActive       = "active"
)

const (
	InspectionNotActive           = "not_active"
	InspectionMatchesInstalled    = "active_matches_installed"
	InspectionDisplacedToBaseline = "active_displaced_to_baseline"
	InspectionPartiallyDisplaced  = "active_partially_displaced"
	InspectionChangedUnclassified = "active_changed_unclassified"
	InspectionMissingOrChanged    = "active_missing_or_changed"
)

type FileRecord struct {
	RelativePath    string `json:"relative_path"`
	BaselineExisted bool   `json:"baseline_existed"`
	BaselineSHA256  string `json:"baseline_sha256,omitempty"`
	InstalledSHA256 string `json:"installed_sha256"`
	InstalledBytes  int64  `json:"installed_bytes"`
}

type State struct {
	Type                 string            `json:"type"`
	FormatVersion        int               `json:"format_version"`
	Status               string            `json:"status"`
	TargetID             string            `json:"target_id"`
	GameRoot             string            `json:"game_root"`
	ActivatedUTC         time.Time         `json:"activated_utc"`
	UpdatedUTC           time.Time         `json:"updated_utc"`
	TransactionID        string            `json:"transaction_id"`
	JournalPath          string            `json:"journal_path"`
	BaselineID           string            `json:"baseline_id"`
	BaselineFingerprint  string            `json:"baseline_fingerprint"`
	BaselineManifestPath string            `json:"baseline_manifest_path"`
	SelectedModules      []string          `json:"selected_modules"`
	Files                []FileRecord      `json:"files"`
	PreviousStatePath    string            `json:"previous_state_path,omitempty"`
	Metadata             map[string]string `json:"metadata,omitempty"`
}

type FileComparison struct {
	RelativePath     string `json:"relative_path"`
	CurrentState     string `json:"current_state"`
	CurrentSHA256    string `json:"current_sha256,omitempty"`
	InstalledSHA256  string `json:"installed_sha256"`
	BaselineSHA256   string `json:"baseline_sha256,omitempty"`
	MatchesInstalled bool   `json:"matches_installed"`
	MatchesBaseline  bool   `json:"matches_baseline"`
}

type Inspection struct {
	Status               string           `json:"status"`
	Active               bool             `json:"active"`
	StatePath            string           `json:"state_path,omitempty"`
	TransactionID        string           `json:"transaction_id,omitempty"`
	BaselineID           string           `json:"baseline_id,omitempty"`
	BaselineManifestPath string           `json:"baseline_manifest_path,omitempty"`
	PreviousStatePath    string           `json:"previous_state_path,omitempty"`
	SelectedModules      []string         `json:"selected_modules,omitempty"`
	Files                []FileComparison `json:"files"`
	Warnings             []string         `json:"warnings"`
}

func ActivePath(stateRoot string) string {
	return filepath.Join(stateRoot, "active_state.json")
}

func Load(stateRoot, targetID, gameRoot string) (State, bool, error) {
	stateRoot, err := filepath.Abs(stateRoot)
	if err != nil {
		return State{}, false, fmt.Errorf("resolve state root: %w", err)
	}
	gameRoot, err = cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return State{}, false, err
	}
	path := ActivePath(stateRoot)
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		return State{}, false, nil
	} else if err != nil {
		return State{}, false, fmt.Errorf("inspect active installation state: %w", err)
	}
	state, err := LoadPath(path, targetID, gameRoot)
	if err != nil {
		return State{}, false, err
	}
	return state, true, nil
}

// LoadPath reads one exact active/history state record and applies the same
// identity validation as Load. It is used when a managed update must walk the
// archived predecessor chain without hashing any game files.
func LoadPath(path, targetID, gameRoot string) (State, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return State{}, fmt.Errorf("resolve installation state path: %w", err)
	}
	gameRoot, err = cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return State{}, err
	}
	info, err := os.Lstat(abs)
	if err != nil {
		return State{}, fmt.Errorf("inspect installation state: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return State{}, fmt.Errorf("installation state is not a regular file: %s", abs)
	}
	data, err := os.ReadFile(abs)
	if err != nil {
		return State{}, err
	}
	var state State
	if err := json.Unmarshal(data, &state); err != nil {
		return State{}, fmt.Errorf("decode installation state: %w", err)
	}
	if err := validateState(state, targetID, gameRoot); err != nil {
		return State{}, err
	}
	return state, nil
}

func Activate(stateRoot, targetID, gameRoot, baselineManifestPath, journalPath string) (State, error) {
	stateRoot, err := filepath.Abs(stateRoot)
	if err != nil {
		return State{}, fmt.Errorf("resolve state root: %w", err)
	}
	gameRoot, err = cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return State{}, err
	}
	journal, err := transaction.Load(journalPath)
	if err != nil {
		return State{}, err
	}
	if journal.Status != transaction.StatusCommitted {
		return State{}, fmt.Errorf("active state requires a committed transaction; status=%s", journal.Status)
	}
	if filepath.Clean(journal.GameRoot) != gameRoot {
		return State{}, fmt.Errorf("committed transaction game root mismatch")
	}
	if metadataTarget := strings.TrimSpace(journal.Metadata["target_id"]); metadataTarget != "" && metadataTarget != targetID {
		return State{}, fmt.Errorf("committed transaction target mismatch: %s", metadataTarget)
	}
	manifest, err := baseline.LoadManifest(baselineManifestPath)
	if err != nil {
		return State{}, err
	}
	if manifest.TargetID != targetID || filepath.Clean(manifest.GameRoot) != gameRoot {
		return State{}, fmt.Errorf("baseline identity does not match installation")
	}
	baselineByPath := map[string]baseline.FileRecord{}
	for _, record := range manifest.Files {
		baselineByPath[strings.ToLower(filepath.ToSlash(record.RelativePath))] = record
	}
	records := make([]FileRecord, 0, len(journal.Files))
	for _, item := range journal.Files {
		key := strings.ToLower(filepath.ToSlash(item.RelativePath))
		base, ok := baselineByPath[key]
		if !ok {
			return State{}, fmt.Errorf("committed path is absent from persistent baseline: %s", item.RelativePath)
		}
		target, err := secureGameJoin(gameRoot, item.RelativePath)
		if err != nil {
			return State{}, err
		}
		info, err := os.Lstat(target)
		if err != nil {
			return State{}, fmt.Errorf("inspect committed target %s: %w", item.RelativePath, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
			return State{}, fmt.Errorf("committed target is not a regular file: %s", item.RelativePath)
		}
		size := info.Size()
		records = append(records, FileRecord{
			RelativePath: filepath.ToSlash(item.RelativePath), BaselineExisted: base.Existed,
			BaselineSHA256: base.SHA256, InstalledSHA256: item.DesiredSHA256, InstalledBytes: size,
		})
	}
	sort.Slice(records, func(i, j int) bool { return records[i].RelativePath < records[j].RelativePath })
	now := time.Now().UTC()
	state := State{
		Type: StateType, FormatVersion: StateFormatVersion, Status: StatusActive,
		TargetID: targetID, GameRoot: gameRoot, ActivatedUTC: now, UpdatedUTC: now,
		TransactionID: journal.TransactionID, JournalPath: absoluteClean(journalPath),
		BaselineID: manifest.BaselineID, BaselineFingerprint: manifest.Fingerprint,
		BaselineManifestPath: absoluteClean(baselineManifestPath),
		SelectedModules:      sortedUnique(journal.SelectedModules), Files: records,
		Metadata: cloneMetadata(journal.Metadata),
	}
	if previous, exists, loadErr := Load(stateRoot, targetID, gameRoot); loadErr != nil {
		return State{}, loadErr
	} else if exists {
		archivePath, archiveErr := archivePreviousState(stateRoot, previous)
		if archiveErr != nil {
			return State{}, archiveErr
		}
		// If a game update, verification or manual restore displaced every managed
		// file to the preserved baseline before this transaction was prepared, the
		// stale active state remains audit history but is not the rollback parent.
		// Rolling back the new install must return to the actual pre-commit baseline.
		if strings.TrimSpace(journal.Metadata["active_state_status"]) != InspectionDisplacedToBaseline {
			state.PreviousStatePath = archivePath
		}
	}
	if err := atomicJSON(ActivePath(stateRoot), state, 0o600); err != nil {
		return State{}, err
	}
	loaded, exists, err := Load(stateRoot, targetID, gameRoot)
	if err != nil || !exists {
		if err == nil {
			err = fmt.Errorf("active state disappeared after publication")
		}
		return State{}, err
	}
	return loaded, nil
}

func ReconcileRollback(stateRoot, targetID, gameRoot, journalPath string) (State, bool, error) {
	return ReconcileRollbackWithProgress(stateRoot, targetID, gameRoot, journalPath, nil)
}

func ReconcileRollbackWithProgress(stateRoot, targetID, gameRoot, journalPath string, progress transaction.ProgressFunc) (State, bool, error) {
	stateRoot, err := filepath.Abs(stateRoot)
	if err != nil {
		return State{}, false, err
	}
	gameRoot, err = cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return State{}, false, err
	}
	current, exists, err := Load(stateRoot, targetID, gameRoot)
	if err != nil || !exists {
		return State{}, false, err
	}
	journal, err := transaction.Load(journalPath)
	if err != nil {
		return State{}, false, err
	}
	if journal.Status != transaction.StatusRolledBack {
		return State{}, false, fmt.Errorf("active state rollback reconciliation requires rolled_back journal; status=%s", journal.Status)
	}
	if current.TransactionID != journal.TransactionID {
		return State{}, false, fmt.Errorf("rolled-back transaction is not the active installation transaction")
	}
	if progress != nil {
		progress(transaction.ProgressEvent{Operation: "rollback", Phase: "reconcile_state", RelativePath: "Reconciling managed installation metadata"})
	}
	journalByPath := map[string]transaction.FileRecord{}
	for _, item := range journal.Files {
		journalByPath[strings.ToLower(filepath.ToSlash(item.RelativePath))] = item
	}
	if current.PreviousStatePath != "" {
		previous, err := loadArchivedState(current.PreviousStatePath, targetID, gameRoot)
		if err != nil {
			return State{}, false, err
		}
		// Paths restored by this journal have already been hash-verified while
		// materializing the atomic rollback replacement. Reuse that proof. Only
		// previous-state paths that were not part of the transaction need a disk
		// read here; this preserves safety for partial updates without rereading
		// every large file after a full rollback.
		for index, item := range previous.Files {
			key := strings.ToLower(filepath.ToSlash(item.RelativePath))
			if record, ok := journalByPath[key]; ok && record.OriginalExisted && record.OriginalSHA256 == item.InstalledSHA256 {
				continue
			}
			target, err := secureGameJoin(gameRoot, item.RelativePath)
			if err != nil {
				return State{}, false, err
			}
			onProgress := func(done, total int64) {
				if progress != nil {
					progress(transaction.ProgressEvent{Operation: "rollback", Phase: "verify_previous_state", FileIndex: index + 1, FileCount: len(previous.Files), RelativePath: item.RelativePath, FileBytesDone: done, FileBytesTotal: total, OverallBytesDone: done, OverallBytesTotal: total})
				}
			}
			hash, _, exists, err := currentRegularHashAndSizeWithProgress(target, onProgress)
			if err != nil {
				return State{}, false, err
			}
			if !exists || hash != item.InstalledSHA256 {
				return State{}, false, fmt.Errorf("rolled-back files do not match the previous active installation state: %s", item.RelativePath)
			}
		}
		previous.UpdatedUTC = time.Now().UTC()
		if err := atomicJSON(ActivePath(stateRoot), previous, 0o600); err != nil {
			return State{}, false, err
		}
		return previous, true, nil
	}
	manifest, err := baseline.LoadManifest(current.BaselineManifestPath)
	if err != nil {
		return State{}, false, err
	}
	if manifest.BaselineID != current.BaselineID || manifest.Fingerprint != current.BaselineFingerprint || manifest.TargetID != targetID || filepath.Clean(manifest.GameRoot) != filepath.Clean(gameRoot) {
		return State{}, false, fmt.Errorf("rolled-back persistent baseline metadata mismatch")
	}
	baselineRecords := map[string]baseline.FileRecord{}
	for _, item := range manifest.Files {
		baselineRecords[strings.ToLower(filepath.ToSlash(item.RelativePath))] = item
	}
	for index, item := range current.Files {
		key := strings.ToLower(filepath.ToSlash(item.RelativePath))
		base, ok := baselineRecords[key]
		if !ok {
			return State{}, false, fmt.Errorf("active managed path is absent from persistent baseline metadata: %s", item.RelativePath)
		}
		if record, covered := journalByPath[key]; covered {
			if base.Existed != record.OriginalExisted || (base.Existed && base.SHA256 != record.OriginalSHA256) {
				return State{}, false, fmt.Errorf("rollback journal original does not match persistent baseline metadata: %s", item.RelativePath)
			}
			continue
		}
		// Defensive fallback for old/partial state records. This should be rare,
		// but keeps reconciliation fail-closed if a managed path was not covered
		// by the transaction that was just rolled back.
		target, err := secureGameJoin(gameRoot, item.RelativePath)
		if err != nil {
			return State{}, false, err
		}
		onProgress := func(done, total int64) {
			if progress != nil {
				progress(transaction.ProgressEvent{Operation: "rollback", Phase: "verify_baseline_state", FileIndex: index + 1, FileCount: len(current.Files), RelativePath: item.RelativePath, FileBytesDone: done, FileBytesTotal: total, OverallBytesDone: done, OverallBytesTotal: total})
			}
		}
		hash, _, exists, err := currentRegularHashAndSizeWithProgress(target, onProgress)
		if err != nil {
			return State{}, false, err
		}
		if base.Existed {
			if !exists || hash != base.SHA256 {
				return State{}, false, fmt.Errorf("rolled-back files do not match the persistent baseline: %s", item.RelativePath)
			}
		} else if exists {
			return State{}, false, fmt.Errorf("rolled-back file should be absent according to baseline: %s", item.RelativePath)
		}
	}
	if err := os.Remove(ActivePath(stateRoot)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return State{}, false, err
	}
	return State{}, false, nil
}

// ClearDisplacedActiveState retires stale active metadata only when every managed
// path already matches the preserved baseline. It never writes game files.
func ClearDisplacedActiveState(stateRoot, targetID, gameRoot string) error {
	stateRoot, err := filepath.Abs(stateRoot)
	if err != nil {
		return err
	}
	state, exists, err := Load(stateRoot, targetID, gameRoot)
	if err != nil {
		return err
	}
	if !exists {
		return nil
	}
	inspection, err := Inspect(stateRoot, targetID, gameRoot)
	if err != nil {
		return err
	}
	if inspection.Status != InspectionDisplacedToBaseline {
		return fmt.Errorf("cannot clear active state unless all managed files match the preserved baseline; status=%s", inspection.Status)
	}
	if _, err := archivePreviousState(stateRoot, state); err != nil {
		return err
	}
	if err := os.Remove(ActivePath(stateRoot)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func Inspect(stateRoot, targetID, gameRoot string) (Inspection, error) {
	return InspectWithProgress(stateRoot, targetID, gameRoot, nil)
}

func InspectWithProgress(stateRoot, targetID, gameRoot string, progress transaction.ProgressFunc) (Inspection, error) {
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return Inspection{}, err
	}
	state, exists, err := Load(stateRoot, targetID, gameRoot)
	if err != nil {
		return Inspection{}, err
	}
	result := Inspection{Status: InspectionNotActive, Active: false, Files: []FileComparison{}, Warnings: []string{}}
	if !exists {
		return result, nil
	}
	result.Active = true
	result.StatePath = ActivePath(stateRoot)
	result.TransactionID = state.TransactionID
	result.BaselineID = state.BaselineID
	result.BaselineManifestPath = state.BaselineManifestPath
	result.PreviousStatePath = state.PreviousStatePath
	result.SelectedModules = append([]string(nil), state.SelectedModules...)
	var overallTotal int64
	for _, item := range state.Files {
		if item.InstalledBytes > 0 {
			overallTotal += item.InstalledBytes
		}
	}
	var overallDone int64
	installedMatches, baselineMatches, other, missing := 0, 0, 0, 0
	for index, item := range state.Files {
		target, err := secureGameJoin(gameRoot, item.RelativePath)
		if err != nil {
			return Inspection{}, err
		}
		onProgress := func(done, total int64) {
			if progress == nil {
				return
			}
			progress(transaction.ProgressEvent{
				Operation: "finalize", Phase: "verify_installed_state",
				FileIndex: index + 1, FileCount: len(state.Files), RelativePath: item.RelativePath,
				FileBytesDone: done, FileBytesTotal: total,
				OverallBytesDone: minInt64(overallDone+done, overallTotal), OverallBytesTotal: overallTotal,
			})
		}
		hash, size, exists, err := currentRegularHashAndSizeWithProgress(target, onProgress)
		if err != nil {
			return Inspection{}, err
		}
		if exists {
			overallDone += size
		}
		comparison := FileComparison{
			RelativePath: item.RelativePath, InstalledSHA256: item.InstalledSHA256,
			BaselineSHA256: item.BaselineSHA256,
		}
		if !exists {
			comparison.CurrentState = "missing"
			missing++
		} else {
			comparison.CurrentState = "file"
			comparison.CurrentSHA256 = hash
			comparison.MatchesInstalled = hash == item.InstalledSHA256
			comparison.MatchesBaseline = item.BaselineExisted && hash == item.BaselineSHA256
			switch {
			case comparison.MatchesInstalled:
				installedMatches++
			case comparison.MatchesBaseline:
				baselineMatches++
			default:
				other++
			}
		}
		if !item.BaselineExisted && !exists {
			comparison.MatchesBaseline = true
			baselineMatches++
			if missing > 0 {
				missing--
			}
		}
		result.Files = append(result.Files, comparison)
	}
	total := len(result.Files)
	switch {
	case total > 0 && installedMatches == total:
		result.Status = InspectionMatchesInstalled
	case total > 0 && baselineMatches == total:
		result.Status = InspectionDisplacedToBaseline
		result.Warnings = append(result.Warnings, "The files match the preserved baseline instead of the recorded installed state. A game update, verification, manual restore, or other replacement may have displaced the mod.")
	case other == 0 && missing == 0 && installedMatches > 0 && baselineMatches > 0:
		result.Status = InspectionPartiallyDisplaced
		result.Warnings = append(result.Warnings, "Some files match the installed mod state and others match the baseline. The installation is partially displaced and must not be updated automatically.")
	case missing > 0:
		result.Status = InspectionMissingOrChanged
		result.Warnings = append(result.Warnings, "One or more managed files are missing or no longer match either the installed state or baseline.")
	default:
		result.Status = InspectionChangedUnclassified
		result.Warnings = append(result.Warnings, "Managed files differ from both the recorded installed state and baseline. This may be a game update or an external modification; no automatic claim is made.")
	}
	return result, nil
}

func validateState(state State, targetID, gameRoot string) error {
	if state.Type != StateType || state.FormatVersion != StateFormatVersion || state.Status != StatusActive {
		return fmt.Errorf("unsupported active installation state type/version/status")
	}
	if state.TargetID != targetID || filepath.Clean(state.GameRoot) != filepath.Clean(gameRoot) {
		return fmt.Errorf("active installation state identity mismatch")
	}
	if strings.TrimSpace(state.TransactionID) == "" || strings.TrimSpace(state.BaselineManifestPath) == "" || len(state.Files) == 0 {
		return fmt.Errorf("active installation state is incomplete")
	}
	manifest, err := baseline.LoadManifest(state.BaselineManifestPath)
	if err != nil {
		return err
	}
	if manifest.BaselineID != state.BaselineID || manifest.Fingerprint != state.BaselineFingerprint || manifest.TargetID != targetID || filepath.Clean(manifest.GameRoot) != filepath.Clean(gameRoot) {
		return fmt.Errorf("active installation baseline mismatch")
	}
	seen := map[string]bool{}
	for _, item := range state.Files {
		clean, err := cleanRelativePath(item.RelativePath)
		if err != nil {
			return err
		}
		key := strings.ToLower(filepath.ToSlash(clean))
		if seen[key] {
			return fmt.Errorf("duplicate active installation path: %s", item.RelativePath)
		}
		seen[key] = true
		if len(item.InstalledSHA256) != 64 {
			return fmt.Errorf("invalid installed SHA-256 for %s", item.RelativePath)
		}
		if item.BaselineExisted && len(item.BaselineSHA256) != 64 {
			return fmt.Errorf("invalid baseline SHA-256 for %s", item.RelativePath)
		}
	}
	return nil
}

func archivePreviousState(stateRoot string, state State) (string, error) {
	root := filepath.Join(stateRoot, "active_state_history")
	if err := os.MkdirAll(root, 0o700); err != nil {
		return "", err
	}
	path := filepath.Join(root, state.TransactionID+".json")
	if _, err := os.Stat(path); err == nil {
		archived, err := loadArchivedState(path, state.TargetID, state.GameRoot)
		if err != nil {
			return "", err
		}
		if archived.TransactionID != state.TransactionID {
			return "", fmt.Errorf("active state history identity mismatch")
		}
		return path, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if err := atomicJSON(path, state, 0o400); err != nil {
		return "", err
	}
	return path, nil
}

func loadArchivedState(path, targetID, gameRoot string) (State, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return State{}, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return State{}, fmt.Errorf("archived active state is not a regular file: %s", path)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return State{}, err
	}
	var state State
	if err := json.Unmarshal(data, &state); err != nil {
		return State{}, err
	}
	if err := validateState(state, targetID, gameRoot); err != nil {
		return State{}, err
	}
	return state, nil
}

func matchesInstalled(gameRoot string, files []FileRecord) (bool, error) {
	for _, item := range files {
		target, err := secureGameJoin(gameRoot, item.RelativePath)
		if err != nil {
			return false, err
		}
		hash, _, exists, err := currentRegularHashAndSize(target)
		if err != nil {
			return false, err
		}
		if !exists || hash != item.InstalledSHA256 {
			return false, nil
		}
	}
	return true, nil
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
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return "", fmt.Errorf("%s must be a real directory: %s", label, absolute)
	}
	return filepath.Clean(absolute), nil
}

func cleanRelativePath(path string) (string, error) {
	if strings.TrimSpace(path) == "" || filepath.IsAbs(path) {
		return "", fmt.Errorf("invalid active-state relative path: %q", path)
	}
	clean := filepath.Clean(filepath.FromSlash(path))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("active-state path escapes root: %q", path)
	}
	return clean, nil
}

func secureGameJoin(root, relative string) (string, error) {
	resolved, _, err := gamepath.Resolve(root, relative)
	if err != nil {
		return "", err
	}
	return resolved, nil
}

func currentRegularHashAndSize(path string) (string, int64, bool, error) {
	return currentRegularHashAndSizeWithProgress(path, nil)
}

func currentRegularHashAndSizeWithProgress(path string, progress func(done, total int64)) (string, int64, bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", 0, false, nil
	}
	if err != nil {
		return "", 0, false, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", 0, false, fmt.Errorf("managed target is not a regular file: %s", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", 0, false, err
	}
	defer file.Close()
	hash := sha256.New()
	buffer := make([]byte, 4*1024*1024)
	var done int64
	if progress != nil {
		progress(0, info.Size())
	}
	for {
		n, readErr := file.Read(buffer)
		if n > 0 {
			_, _ = hash.Write(buffer[:n])
			done += int64(n)
			if progress != nil {
				progress(done, info.Size())
			}
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return "", 0, false, readErr
		}
	}
	return hex.EncodeToString(hash.Sum(nil)), done, true, nil
}

func minInt64(a, b int64) int64 {
	if b <= 0 || a < b {
		return a
	}
	return b
}

func atomicJSON(path string, value any, mode fs.FileMode) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".tmp-active-state-")
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
	return nil
}

func absoluteClean(path string) string {
	absolute, err := filepath.Abs(path)
	if err != nil {
		return filepath.Clean(path)
	}
	return filepath.Clean(absolute)
}

func sortedUnique(values []string) []string {
	seen := map[string]bool{}
	var result []string
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" || seen[value] {
			continue
		}
		seen[value] = true
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func cloneMetadata(source map[string]string) map[string]string {
	if len(source) == 0 {
		return nil
	}
	result := make(map[string]string, len(source))
	for key, value := range source {
		result[key] = value
	}
	return result
}
