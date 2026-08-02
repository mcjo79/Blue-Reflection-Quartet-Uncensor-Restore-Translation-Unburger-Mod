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
)

const (
	profileStateType        = "br_core_quartet_event_profile_state"
	profileReportType       = "br_core_quartet_event_profile_transaction_report"
	shaderProfileStateType  = "br_core_quartet_shader_profile_state"
	shaderProfileReportType = "br_core_quartet_shader_profile_transaction_report"
)

type profileCommandContext struct {
	ProjectRoot string
	GameRoot    string
	ConfigPath  string
}

func addProfileCommonFlags(flags *flag.FlagSet) *profileCommandContext {
	ctx := &profileCommandContext{}
	flags.StringVar(&ctx.ProjectRoot, "project-root", "", "Blue Reflection project root")
	flags.StringVar(&ctx.GameRoot, "game-root", "", "Blue Reflection Quartet game root")
	// Kept as a parsed compatibility flag for older scripted invocations. The
	// manifest importer deliberately ignores core-owned static profile configs.
	flags.StringVar(&ctx.ConfigPath, "config", "", "deprecated compatibility flag; local manifests are discovered automatically")
	return ctx
}

func validateSHA256(value string) error {
	if len(value) != 64 {
		return fmt.Errorf("SHA-256 must contain 64 hexadecimal characters")
	}
	_, err := hex.DecodeString(value)
	return err
}

func validateRelativePath(value string) error {
	if value == "" || filepath.IsAbs(value) {
		return fmt.Errorf("path must be relative")
	}
	cleaned := filepath.Clean(filepath.FromSlash(value))
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, ".."+string(os.PathSeparator)) {
		return fmt.Errorf("path escapes its root")
	}
	return nil
}

func secureJoin(root, relative string) (string, error) {
	if err := validateRelativePath(relative); err != nil {
		return "", err
	}
	root = filepath.Clean(root)
	joined := filepath.Join(root, filepath.FromSlash(relative))
	rel, err := filepath.Rel(root, joined)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return "", fmt.Errorf("path escapes root: %s", relative)
	}
	return joined, nil
}

func checkedFile(path string) (string, int64, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return "", 0, err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", 0, fmt.Errorf("not a regular non-symlink file: %s", path)
	}
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(hash.Sum(nil)), info.Size(), nil
}

func copyFileDurable(source, destination, expectedHash string, expectedSize int64, mode os.FileMode) error {
	if hash, size, err := checkedFile(source); err != nil || hash != expectedHash || size != expectedSize {
		if err != nil {
			return err
		}
		return fmt.Errorf("source changed: got %s (%d bytes)", hash, size)
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(destination), ".br-core-backup-*")
	if err != nil {
		return err
	}
	tempName := temporary.Name()
	defer os.Remove(tempName)
	input, err := os.Open(source)
	if err != nil {
		temporary.Close()
		return err
	}
	_, copyErr := io.Copy(temporary, input)
	closeInputErr := input.Close()
	if copyErr == nil {
		copyErr = closeInputErr
	}
	if copyErr == nil {
		copyErr = temporary.Chmod(mode)
	}
	if copyErr == nil {
		copyErr = temporary.Sync()
	}
	closeErr := temporary.Close()
	if copyErr == nil {
		copyErr = closeErr
	}
	if copyErr != nil {
		return copyErr
	}
	if hash, size, err := checkedFile(tempName); err != nil || hash != expectedHash || size != expectedSize {
		if err != nil {
			return err
		}
		return fmt.Errorf("temporary copy checksum mismatch")
	}
	if err := os.Rename(tempName, destination); err != nil {
		return err
	}
	return fsyncDirectory(filepath.Dir(destination))
}

func atomicReplaceVerified(source, target, sourceHash string, sourceSize int64, expectedCurrentHash, expectedAfterHash string) error {
	if hash, size, err := checkedFile(source); err != nil || hash != sourceHash || size != sourceSize {
		if err != nil {
			return err
		}
		return fmt.Errorf("source checksum mismatch immediately before copy")
	}
	targetInfo, err := os.Lstat(target)
	if err != nil {
		return err
	}
	if targetInfo.Mode()&os.ModeSymlink != 0 || !targetInfo.Mode().IsRegular() {
		return fmt.Errorf("target is not a regular non-symlink file")
	}
	temporary, err := os.CreateTemp(filepath.Dir(target), "."+filepath.Base(target)+".br-core-*")
	if err != nil {
		return err
	}
	tempName := temporary.Name()
	defer os.Remove(tempName)
	input, err := os.Open(source)
	if err != nil {
		temporary.Close()
		return err
	}
	_, copyErr := io.Copy(temporary, input)
	closeInputErr := input.Close()
	if copyErr == nil {
		copyErr = closeInputErr
	}
	if copyErr == nil {
		copyErr = temporary.Chmod(targetInfo.Mode().Perm())
	}
	if copyErr == nil {
		copyErr = temporary.Sync()
	}
	closeErr := temporary.Close()
	if copyErr == nil {
		copyErr = closeErr
	}
	if copyErr != nil {
		return copyErr
	}
	if hash, size, err := checkedFile(tempName); err != nil || hash != sourceHash || size != sourceSize {
		if err != nil {
			return err
		}
		return fmt.Errorf("same-filesystem temporary checksum mismatch")
	}
	currentHash, _, err := checkedFile(target)
	if err != nil {
		return err
	}
	if currentHash != expectedCurrentHash {
		return fmt.Errorf("target changed before atomic replacement: got %s", currentHash)
	}
	if err := os.Rename(tempName, target); err != nil {
		return err
	}
	if err := fsyncDirectory(filepath.Dir(target)); err != nil {
		return err
	}
	finalHash, _, err := checkedFile(target)
	if err != nil {
		return err
	}
	if finalHash != expectedAfterHash {
		return fmt.Errorf("post-replacement checksum mismatch: got %s", finalHash)
	}
	return nil
}

func fsyncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func writeJSONAtomic(path string, value any, mode os.FileMode) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary, err := os.CreateTemp(filepath.Dir(path), ".br-core-json-*")
	if err != nil {
		return err
	}
	tempName := temporary.Name()
	defer os.Remove(tempName)
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Chmod(mode); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(tempName, path); err != nil {
		return err
	}
	return fsyncDirectory(filepath.Dir(path))
}

func isOpenProfileState(status string) bool {
	return status == "active" || status == "prepared" || status == "rolling_back" || status == "activation_uncertain" || status == "rollback_uncertain"
}

func transactionID() string {
	return time.Now().UTC().Format("20060102T150405.000000000Z") + fmt.Sprintf("-%d", os.Getpid())
}

func utcNow() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}
