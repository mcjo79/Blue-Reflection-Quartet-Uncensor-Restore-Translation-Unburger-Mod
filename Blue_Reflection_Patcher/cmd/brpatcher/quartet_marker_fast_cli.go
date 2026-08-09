package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/plan/baseline"
	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	quartetMarkerFastStateType    = "br_quartet_title_marker_fast_test_state"
	quartetMarkerFastStateVersion = 1
	quartetMarkerFastTarget       = "Data/PACK00_04_01.PAK"
)

type quartetMarkerFastState struct {
	Type            string    `json:"type"`
	FormatVersion   int       `json:"format_version"`
	CreatedUTC      time.Time `json:"created_utc"`
	GameRoot        string    `json:"game_root"`
	TargetPath      string    `json:"target_path"`
	BackupPath      string    `json:"backup_path"`
	OriginalSHA256  string    `json:"original_sha256"`
	OriginalBytes   int64     `json:"original_bytes"`
	CandidateSHA256 string    `json:"candidate_sha256"`
	CandidateBytes  int64     `json:"candidate_bytes"`
	Label           string    `json:"label"`
	BuildSource     string    `json:"build_source"`
}

func commandQuartetMarkerFastTest(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("quartet marker fast test requires install or restore")
	}
	action := strings.ToLower(strings.TrimSpace(args[0]))
	flags := flag.NewFlagSet("quartet-marker-fast-test", flag.ContinueOnError)
	var roots rootsFlag
	var stateDir, label string
	flags.Var(&roots, "game-dir", "BLUE REFLECTION Quartet game directory")
	flags.StringVar(&stateDir, "state-dir", "", "private marker-test state directory")
	flags.StringVar(&label, "label", "UNBURGER / UNCENSOR / DLC", "marker label")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	if action != "install" && action != "restore" {
		return fmt.Errorf("quartet marker fast test action must be install or restore")
	}
	if strings.TrimSpace(stateDir) == "" {
		cwd, err := os.Getwd()
		if err != nil {
			return err
		}
		stateDir = filepath.Join(cwd, "MARKER_TEST_STATE")
	}
	absoluteState, err := filepath.Abs(stateDir)
	if err != nil {
		return err
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	items, err := detectWithFallback(specs, roots, stdinIsInteractive(), os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	var quartetRoots []string
	for _, item := range items {
		if item.TargetID == quartetTargetID {
			quartetRoots = append(quartetRoots, item.Root)
		}
	}
	if len(quartetRoots) != 1 {
		return fmt.Errorf("marker fast test requires exactly one BLUE REFLECTION Quartet installation; found %d", len(quartetRoots))
	}
	if action == "restore" {
		return restoreQuartetMarkerFastTest(quartetRoots[0], absoluteState)
	}
	return installQuartetMarkerFastTest(quartetRoots[0], absoluteState, strings.TrimSpace(label))
}

func installQuartetMarkerFastTest(gameRoot, stateDir, label string) error {
	if label == "" {
		return fmt.Errorf("marker label is empty")
	}
	statePath := filepath.Join(stateDir, "state.json")
	if _, err := os.Stat(statePath); err == nil {
		return fmt.Errorf("marker fast-test state already exists; restore it before another install: %s", statePath)
	} else if !os.IsNotExist(err) {
		return err
	}
	target := filepath.Join(gameRoot, filepath.FromSlash(quartetMarkerFastTarget))
	infoBefore, err := regularFastMarkerFile(target)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return err
	}
	backupPath := filepath.Join(stateDir, "PACK00_04_01.before-fast-test.PAK")
	fmt.Println("\n[MARKER FAST TEST] Backing up only Data/PACK00_04_01.PAK ...")
	originalHash, originalBytes, err := copyAndHashFastMarker(target, backupPath, infoBefore.Mode().Perm())
	if err != nil {
		return err
	}
	infoAfter, err := regularFastMarkerFile(target)
	if err != nil {
		return err
	}
	if infoAfter.Size() != infoBefore.Size() || !infoAfter.ModTime().Equal(infoBefore.ModTime()) {
		return fmt.Errorf("target changed while the fast-test backup was being created")
	}

	source, sourceKind, err := quartetMarkerBuildSource(gameRoot, target)
	if err != nil {
		return err
	}
	workDir, err := os.MkdirTemp(stateDir, "build-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(workDir)
	fmt.Printf("[MARKER FAST TEST] Building approved Quartet marker from %s ...\n", sourceKind)
	audit, candidate, err := br1rebuild.ApplyQuartetTitleMarker(workDir, source, label, func(progress br1rebuild.BuildProgress) {
		if progress.CurrentTotal > 0 {
			fmt.Printf("\r[MARKER FAST TEST] %-24s %6.1f%%", progress.Phase, 100*float64(progress.CurrentDone)/float64(progress.CurrentTotal))
		}
	})
	fmt.Print("\r")
	if err != nil {
		return err
	}
	candidateHash, candidateBytes, err := hashFastMarkerFile(candidate)
	if err != nil {
		return err
	}
	if audit.PatchedBlocks != 11000 {
		return fmt.Errorf("unexpected marker block count: %d", audit.PatchedBlocks)
	}
	fmt.Println("[MARKER FAST TEST] Installing only Data/PACK00_04_01.PAK ...")
	if err := replaceFastMarkerFile(candidate, target, candidateHash, candidateBytes, originalHash, originalBytes); err != nil {
		return err
	}
	state := quartetMarkerFastState{
		Type: quartetMarkerFastStateType, FormatVersion: quartetMarkerFastStateVersion, CreatedUTC: time.Now().UTC(),
		GameRoot: filepath.Clean(gameRoot), TargetPath: target, BackupPath: backupPath,
		OriginalSHA256: originalHash, OriginalBytes: originalBytes,
		CandidateSHA256: candidateHash, CandidateBytes: candidateBytes,
		Label: label, BuildSource: sourceKind,
	}
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		// The game file is already changed. Do not hide that fact; restore immediately.
		_ = replaceFastMarkerFile(backupPath, target, originalHash, originalBytes, candidateHash, candidateBytes)
		return fmt.Errorf("record marker fast-test state: %w", err)
	}
	fmt.Printf("[MARKER FAST TEST] Installed. Label: %s\n", label)
	fmt.Println("[MARKER FAST TEST] Start the game and inspect only the Quartet launcher. Then run RESTORE_MARKER.")
	return nil
}

func restoreQuartetMarkerFastTest(gameRoot, stateDir string) error {
	statePath := filepath.Join(stateDir, "state.json")
	data, err := os.ReadFile(statePath)
	if err != nil {
		return fmt.Errorf("read marker fast-test state: %w", err)
	}
	var state quartetMarkerFastState
	if err := json.Unmarshal(data, &state); err != nil {
		return fmt.Errorf("decode marker fast-test state: %w", err)
	}
	if state.Type != quartetMarkerFastStateType || state.FormatVersion != quartetMarkerFastStateVersion {
		return fmt.Errorf("unsupported marker fast-test state")
	}
	if filepath.Clean(state.GameRoot) != filepath.Clean(gameRoot) {
		return fmt.Errorf("marker fast-test state belongs to another game directory")
	}
	target := filepath.Join(gameRoot, filepath.FromSlash(quartetMarkerFastTarget))
	fmt.Println("\n[MARKER FAST TEST] Verifying current marker test PAK ...")
	currentHash, currentBytes, err := hashFastMarkerFile(target)
	if err != nil {
		return err
	}
	if currentHash != state.CandidateSHA256 || currentBytes != state.CandidateBytes {
		return fmt.Errorf("current PACK00_04_01.PAK changed after marker test; refusing automatic restore")
	}
	fmt.Println("[MARKER FAST TEST] Restoring only Data/PACK00_04_01.PAK ...")
	if err := replaceFastMarkerFile(state.BackupPath, target, state.OriginalSHA256, state.OriginalBytes, state.CandidateSHA256, state.CandidateBytes); err != nil {
		return err
	}
	if err := os.Remove(state.BackupPath); err != nil {
		return err
	}
	if err := os.Remove(statePath); err != nil {
		return err
	}
	_ = os.Remove(stateDir)
	fmt.Println("[MARKER FAST TEST] Restore complete. Previous PACK00_04_01.PAK is back byte-for-byte.")
	return nil
}

func quartetMarkerBuildSource(gameRoot, currentTarget string) (string, string, error) {
	base, err := stateRoot()
	if err != nil {
		return "", "", err
	}
	stateDir := installationStateDirectory(base, quartetTargetID, gameRoot)
	active, exists, err := installstate.Load(stateDir, quartetTargetID, gameRoot)
	if err != nil {
		return "", "", err
	}
	if exists && strings.TrimSpace(active.BaselineManifestPath) != "" {
		manifest, storedPaths, err := baseline.LoadStoredPaths(active.BaselineManifestPath)
		if err != nil {
			return "", "", err
		}
		for _, record := range manifest.Files {
			if strings.EqualFold(filepath.ToSlash(record.RelativePath), quartetMarkerFastTarget) && record.Existed {
				source, ok := storedPaths[filepath.ToSlash(record.RelativePath)]
				if !ok || strings.TrimSpace(source) == "" {
					return "", "", fmt.Errorf("managed baseline PACK00_04_01.PAK has no resolved stored path")
				}
				hash, size, err := hashFastMarkerFile(source)
				if err != nil {
					return "", "", err
				}
				if hash != record.SHA256 || size != record.Bytes {
					return "", "", fmt.Errorf("managed baseline PACK00_04_01.PAK failed its recorded hash")
				}
				return source, "verified managed baseline", nil
			}
		}
	}
	// Older managed states may have been created before PACK00_04_01 became a
	// baseline member. Their committed transaction still retains the exact
	// pre-install rollback copy. Reuse that verified copy rather than trying to
	// parse a currently installed G1T that may contain the known bad marker.
	if exists && strings.TrimSpace(active.JournalPath) != "" {
		journal, err := transaction.Load(active.JournalPath)
		if err != nil {
			return "", "", err
		}
		for _, record := range journal.Files {
			if !strings.EqualFold(filepath.ToSlash(record.RelativePath), quartetMarkerFastTarget) || !record.OriginalExisted || strings.TrimSpace(record.BackupPath) == "" {
				continue
			}
			hash, _, err := hashFastMarkerFile(record.BackupPath)
			if err != nil {
				return "", "", err
			}
			if hash != record.OriginalSHA256 {
				return "", "", fmt.Errorf("managed rollback PACK00_04_01.PAK failed its recorded hash")
			}
			return record.BackupPath, "verified managed rollback copy", nil
		}
	}
	return currentTarget, "current game PAK", nil
}

func regularFastMarkerFile(path string) (os.FileInfo, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("not a regular non-symlink file: %s", path)
	}
	return info, nil
}

func hashFastMarkerFile(path string) (string, int64, error) {
	info, err := regularFastMarkerFile(path)
	if err != nil {
		return "", 0, err
	}
	input, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer input.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, input); err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(hash.Sum(nil)), info.Size(), nil
}

func copyAndHashFastMarker(source, destination string, mode os.FileMode) (string, int64, error) {
	sourceInfo, err := regularFastMarkerFile(source)
	if err != nil {
		return "", 0, err
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return "", 0, err
	}
	input, err := os.Open(source)
	if err != nil {
		return "", 0, err
	}
	defer input.Close()
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return "", 0, err
	}
	hash := sha256.New()
	written, copyErr := io.Copy(io.MultiWriter(output, hash), input)
	if copyErr == nil {
		copyErr = output.Sync()
	}
	closeErr := output.Close()
	if copyErr == nil {
		copyErr = closeErr
	}
	if copyErr != nil {
		_ = os.Remove(destination)
		return "", 0, copyErr
	}
	if written != sourceInfo.Size() {
		_ = os.Remove(destination)
		return "", 0, fmt.Errorf("short marker fast-test copy: %d/%d", written, sourceInfo.Size())
	}
	return hex.EncodeToString(hash.Sum(nil)), written, nil
}

func replaceFastMarkerFile(source, target, sourceHash string, sourceBytes int64, expectedCurrentHash string, expectedCurrentBytes int64) error {
	currentHash, currentBytes, err := hashFastMarkerFile(target)
	if err != nil {
		return err
	}
	if currentHash != expectedCurrentHash || currentBytes != expectedCurrentBytes {
		return fmt.Errorf("target changed before marker fast-test replacement")
	}
	targetInfo, err := regularFastMarkerFile(target)
	if err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(target), ".unburger-marker-fast-*")
	if err != nil {
		return err
	}
	tempPath := temp.Name()
	if err := temp.Close(); err != nil {
		os.Remove(tempPath)
		return err
	}
	os.Remove(tempPath)
	copiedHash, copiedBytes, err := copyAndHashFastMarker(source, tempPath, targetInfo.Mode().Perm())
	if err != nil {
		return err
	}
	defer os.Remove(tempPath)
	if copiedHash != sourceHash || copiedBytes != sourceBytes {
		return fmt.Errorf("marker fast-test source changed during copy")
	}
	swap := target + ".unburger-marker-fast-swap"
	if _, err := os.Lstat(swap); err == nil {
		return fmt.Errorf("stale marker fast-test swap exists: %s", swap)
	} else if !os.IsNotExist(err) {
		return err
	}
	if err := os.Rename(target, swap); err != nil {
		return fmt.Errorf("move current marker target aside: %w", err)
	}
	installed := false
	defer func() {
		if !installed {
			_ = os.Rename(swap, target)
		}
	}()
	if err := os.Rename(tempPath, target); err != nil {
		return fmt.Errorf("install marker fast-test PAK: %w", err)
	}
	installed = true
	if err := os.Remove(swap); err != nil {
		return fmt.Errorf("remove marker fast-test swap after successful replacement: %w", err)
	}
	return fsyncDirectory(filepath.Dir(target))
}
