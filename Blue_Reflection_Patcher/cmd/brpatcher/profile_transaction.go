package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	profileConfigType = "br_quartet_restoration_event_profiles"
	profileStateType  = "br_core_quartet_event_profile_state"
	profileReportType = "br_core_quartet_event_profile_transaction_report"
)

type quartetProfileConfig struct {
	Type               string           `json:"type"`
	FormatVersion      int              `json:"format_version"`
	RequestToolVersion string           `json:"request_tool_version"`
	TransactionOwner   string           `json:"transaction_owner"`
	TargetRelativePath string           `json:"target_relative_path"`
	BaselineSHA256     string           `json:"baseline_sha256"`
	BaselineSize       int64            `json:"baseline_size"`
	Profiles           []quartetProfile `json:"profiles"`
}

type quartetProfile struct {
	ProfileID                            string `json:"profile_id"`
	Classification                       string `json:"classification"`
	Confidence                           string `json:"confidence"`
	SourceRelativePath                   string `json:"source_relative_path"`
	SourceSHA256                         string `json:"source_sha256"`
	SourceSize                           int64  `json:"source_size"`
	ExpectedTargetSHA256BeforeActivation string `json:"expected_target_sha256_before_activation"`
	ExpectedTargetSHA256AfterActivation  string `json:"expected_target_sha256_after_activation"`
	ExpectedTargetSHA256BeforeRollback   string `json:"expected_target_sha256_before_rollback"`
	SelectedMembers                      int    `json:"selected_members"`
}

type quartetProfileState struct {
	Type                   string `json:"type"`
	FormatVersion          int    `json:"format_version"`
	Status                 string `json:"status"`
	TransactionID          string `json:"transaction_id"`
	ProfileID              string `json:"profile_id"`
	Classification         string `json:"classification"`
	Confidence             string `json:"confidence"`
	TargetRelativePath     string `json:"target_relative_path"`
	SourceRelativePath     string `json:"source_relative_path"`
	BackupRelativePath     string `json:"backup_relative_path"`
	BaselineSHA256         string `json:"baseline_sha256"`
	ActiveProfileSHA256    string `json:"active_profile_sha256"`
	ObservedBeforeSHA256   string `json:"observed_before_sha256"`
	ObservedBeforeSize     int64  `json:"observed_before_size"`
	CreatedUTC             string `json:"created_utc"`
	UpdatedUTC             string `json:"updated_utc"`
	LastCompletedOperation string `json:"last_completed_operation,omitempty"`
}

type quartetProfileReport struct {
	Type                 string `json:"type"`
	FormatVersion        int    `json:"format_version"`
	Status               string `json:"status"`
	Operation            string `json:"operation"`
	TransactionID        string `json:"transaction_id,omitempty"`
	ProfileID            string `json:"profile_id,omitempty"`
	Classification       string `json:"classification,omitempty"`
	Confidence           string `json:"confidence,omitempty"`
	TargetRelativePath   string `json:"target_relative_path"`
	ObservedTargetSHA256 string `json:"observed_target_sha256"`
	ExpectedTargetSHA256 string `json:"expected_target_sha256,omitempty"`
	BaselineSHA256       string `json:"baseline_sha256"`
	BackupRelativePath   string `json:"backup_relative_path,omitempty"`
	StateStatus          string `json:"state_status"`
	GeneratedUTC         string `json:"generated_utc"`
	NextAction           string `json:"next_action"`
}

type profileCommandContext struct {
	ProjectRoot string
	GameRoot    string
	ConfigPath  string
}

func commandQuartetProfileActivate(args []string) error {
	flags := flag.NewFlagSet("quartet-profile-activate", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 1 {
		return fmt.Errorf("exactly one profile ID is required")
	}
	return activateQuartetProfile(*ctx, flags.Arg(0))
}

func commandQuartetProfileStatus(args []string) error {
	flags := flag.NewFlagSet("quartet-profile-status", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("quartet-profile-status accepts no positional arguments")
	}
	return statusQuartetProfile(*ctx)
}

func commandQuartetProfileRollback(args []string) error {
	flags := flag.NewFlagSet("quartet-profile-rollback", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("quartet-profile-rollback accepts no positional arguments")
	}
	return rollbackQuartetProfile(*ctx)
}

func addProfileCommonFlags(flags *flag.FlagSet) *profileCommandContext {
	ctx := &profileCommandContext{}
	flags.StringVar(&ctx.ProjectRoot, "project-root", "", "Blue Reflection project root")
	flags.StringVar(&ctx.GameRoot, "game-root", "", "Blue Reflection Quartet game root")
	flags.StringVar(&ctx.ConfigPath, "config", "", "profile metadata JSON; defaults to project config")
	return ctx
}

func normalizeProfileContext(ctx profileCommandContext) (profileCommandContext, error) {
	if ctx.ProjectRoot == "" || ctx.GameRoot == "" {
		return ctx, fmt.Errorf("--project-root and --game-root are required")
	}
	projectRoot, err := filepath.Abs(ctx.ProjectRoot)
	if err != nil {
		return ctx, err
	}
	gameRoot, err := filepath.Abs(ctx.GameRoot)
	if err != nil {
		return ctx, err
	}
	projectRoot = filepath.Clean(projectRoot)
	gameRoot = filepath.Clean(gameRoot)
	if info, err := os.Stat(projectRoot); err != nil || !info.IsDir() {
		return ctx, fmt.Errorf("invalid project root: %s", projectRoot)
	}
	if info, err := os.Stat(gameRoot); err != nil || !info.IsDir() {
		return ctx, fmt.Errorf("invalid game root: %s", gameRoot)
	}
	configPath := ctx.ConfigPath
	if configPath == "" {
		configPath = filepath.Join(projectRoot, "config", "quartet_restoration_event_profiles.json")
	} else if !filepath.IsAbs(configPath) {
		configPath = filepath.Join(projectRoot, configPath)
	}
	ctx.ProjectRoot = projectRoot
	ctx.GameRoot = gameRoot
	ctx.ConfigPath = filepath.Clean(configPath)
	return ctx, nil
}

func loadQuartetProfileConfig(path string) (quartetProfileConfig, error) {
	var config quartetProfileConfig
	data, err := os.ReadFile(path)
	if err != nil {
		return config, fmt.Errorf("read profile config: %w", err)
	}
	if err := json.Unmarshal(data, &config); err != nil {
		return config, fmt.Errorf("parse profile config: %w", err)
	}
	if config.Type != profileConfigType || config.FormatVersion != 1 {
		return config, fmt.Errorf("unsupported profile config")
	}
	if config.TransactionOwner != "core_unified_patcher" {
		return config, fmt.Errorf("profile config has wrong transaction owner")
	}
	if err := validateRelativePath(config.TargetRelativePath); err != nil {
		return config, fmt.Errorf("invalid target path: %w", err)
	}
	if err := validateSHA256(config.BaselineSHA256); err != nil || config.BaselineSize <= 0 {
		return config, fmt.Errorf("invalid baseline metadata")
	}
	if len(config.Profiles) == 0 {
		return config, fmt.Errorf("profile config contains no profiles")
	}
	seen := map[string]bool{}
	for _, profile := range config.Profiles {
		if profile.ProfileID == "" || seen[profile.ProfileID] {
			return config, fmt.Errorf("invalid or duplicate profile ID: %q", profile.ProfileID)
		}
		seen[profile.ProfileID] = true
		if err := validateRelativePath(profile.SourceRelativePath); err != nil {
			return config, fmt.Errorf("invalid source path for %s: %w", profile.ProfileID, err)
		}
		if err := validateSHA256(profile.SourceSHA256); err != nil || profile.SourceSize <= 0 {
			return config, fmt.Errorf("invalid source metadata for %s", profile.ProfileID)
		}
		if profile.ExpectedTargetSHA256BeforeActivation != config.BaselineSHA256 ||
			profile.ExpectedTargetSHA256AfterActivation != profile.SourceSHA256 ||
			profile.ExpectedTargetSHA256BeforeRollback != profile.SourceSHA256 {
			return config, fmt.Errorf("inconsistent transaction hashes for %s", profile.ProfileID)
		}
	}
	return config, nil
}

func activateQuartetProfile(raw profileCommandContext, profileID string) error {
	ctx, err := normalizeProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetProfileConfig(ctx.ConfigPath)
	if err != nil {
		return err
	}
	profile, err := findQuartetProfile(config, profileID)
	if err != nil {
		return err
	}
	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()

	target, err := secureJoin(ctx.GameRoot, config.TargetRelativePath)
	if err != nil {
		return err
	}
	source, err := secureJoin(ctx.ProjectRoot, profile.SourceRelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return fmt.Errorf("inspect installed target: %w", err)
	}
	statePath := profileStatePath(ctx.ProjectRoot)
	state, stateExists, err := readProfileState(statePath)
	if err != nil {
		return err
	}

	if stateExists && (state.Status == "active" || state.Status == "prepared" || state.Status == "rolling_back" || state.Status == "activation_uncertain") {
		if state.ProfileID != profile.ProfileID {
			return fmt.Errorf("profile %s already owns the open transaction; rollback first", state.ProfileID)
		}
		if state.Status == "active" {
			return fmt.Errorf("profile %s is already active", state.ProfileID)
		}
		if state.Status == "rolling_back" {
			return fmt.Errorf("rollback transaction is incomplete; run status, then rollback")
		}
		if state.Status == "activation_uncertain" {
			return fmt.Errorf("activation result is uncertain; run status and rollback if the active profile hash is installed")
		}
		if currentHash == state.ActiveProfileSHA256 {
			state.Status = "active"
			state.UpdatedUTC = utcNow()
			state.LastCompletedOperation = "activation_recovered"
			if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
				return err
			}
			return writeProfileReport(ctx.ProjectRoot, quartetProfileReport{
				Type: profileReportType, FormatVersion: 1, Status: "ok", Operation: "activate_recovered",
				TransactionID: state.TransactionID, ProfileID: state.ProfileID, Classification: state.Classification,
				Confidence: state.Confidence, TargetRelativePath: state.TargetRelativePath,
				ObservedTargetSHA256: currentHash, ExpectedTargetSHA256: state.ActiveProfileSHA256,
				BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
				StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: "run the game test, then rollback",
			})
		}
		if currentHash != config.BaselineSHA256 || currentSize != config.BaselineSize {
			return fmt.Errorf("prepared transaction target drifted: got %s (%d bytes)", currentHash, currentSize)
		}
		if err := verifyStateBackup(ctx.ProjectRoot, state); err != nil {
			return err
		}
		if err := verifyProfileSource(source, profile); err != nil {
			return err
		}
		return finishProfileActivation(ctx, config, profile, state, source, target)
	}

	if currentHash != config.BaselineSHA256 || currentSize != config.BaselineSize {
		return fmt.Errorf("installed Data/PACK11.PAK is not the required stage-25 baseline: got %s (%d bytes); rerun restoration stages 25 and 26", currentHash, currentSize)
	}
	if err := verifyProfileSource(source, profile); err != nil {
		return err
	}

	transactionID := transactionID()
	backupRel := filepath.ToSlash(filepath.Join(".local", "backups", "core_unified_patcher", "quartet_event_profiles", transactionID, config.TargetRelativePath))
	backup, err := secureJoin(ctx.ProjectRoot, backupRel)
	if err != nil {
		return err
	}
	if err := copyFileDurable(target, backup, config.BaselineSHA256, config.BaselineSize, 0o600); err != nil {
		return fmt.Errorf("create core-managed backup: %w", err)
	}
	state = quartetProfileState{
		Type: profileStateType, FormatVersion: 1, Status: "prepared", TransactionID: transactionID,
		ProfileID: profile.ProfileID, Classification: profile.Classification, Confidence: profile.Confidence,
		TargetRelativePath: config.TargetRelativePath, SourceRelativePath: profile.SourceRelativePath,
		BackupRelativePath: backupRel, BaselineSHA256: config.BaselineSHA256,
		ActiveProfileSHA256: profile.SourceSHA256, ObservedBeforeSHA256: currentHash,
		ObservedBeforeSize: currentSize, CreatedUTC: utcNow(), UpdatedUTC: utcNow(),
	}
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return fmt.Errorf("record prepared transaction: %w", err)
	}
	return finishProfileActivation(ctx, config, profile, state, source, target)
}

func finishProfileActivation(ctx profileCommandContext, config quartetProfileConfig, profile quartetProfile, state quartetProfileState, source, target string) error {
	if err := atomicReplaceVerified(source, target, profile.SourceSHA256, profile.SourceSize, config.BaselineSHA256, profile.SourceSHA256); err != nil {
		state.UpdatedUTC = utcNow()
		observed, _, inspectErr := checkedFile(target)
		if inspectErr == nil && observed == config.BaselineSHA256 {
			state.Status = "activation_failed"
		} else {
			state.Status = "activation_uncertain"
		}
		_ = writeJSONAtomic(profileStatePath(ctx.ProjectRoot), state, 0o600)
		return fmt.Errorf("activate profile: %w", err)
	}
	state.Status = "active"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "activate"
	if err := writeJSONAtomic(profileStatePath(ctx.ProjectRoot), state, 0o600); err != nil {
		return fmt.Errorf("record active transaction: %w", err)
	}
	if err := writeProfileReport(ctx.ProjectRoot, quartetProfileReport{
		Type: profileReportType, FormatVersion: 1, Status: "ok", Operation: "activate",
		TransactionID: state.TransactionID, ProfileID: profile.ProfileID, Classification: profile.Classification,
		Confidence: profile.Confidence, TargetRelativePath: config.TargetRelativePath,
		ObservedTargetSHA256: profile.SourceSHA256, ExpectedTargetSHA256: profile.SourceSHA256,
		BaselineSHA256: config.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: "run the matching scene test, exit the game, then rollback",
	}); err != nil {
		return err
	}
	fmt.Printf("Activated profile: %s\nTransaction: %s\nInstalled SHA-256: %s\n", profile.ProfileID, state.TransactionID, profile.SourceSHA256)
	return nil
}

func rollbackQuartetProfile(raw profileCommandContext) error {
	ctx, err := normalizeProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetProfileConfig(ctx.ConfigPath)
	if err != nil {
		return err
	}
	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()

	statePath := profileStatePath(ctx.ProjectRoot)
	state, exists, err := readProfileState(statePath)
	if err != nil {
		return err
	}
	if !exists {
		return fmt.Errorf("no core-managed event-profile transaction exists")
	}
	if state.Status != "active" && state.Status != "prepared" && state.Status != "rolling_back" && state.Status != "activation_uncertain" {
		return fmt.Errorf("no active profile can be rolled back; state is %s", state.Status)
	}
	target, err := secureJoin(ctx.GameRoot, state.TargetRelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return err
	}
	if state.Status == "rolling_back" && currentHash == state.BaselineSHA256 {
		state.Status = "rolled_back"
		state.UpdatedUTC = utcNow()
		state.LastCompletedOperation = "rollback_recovered"
		if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
			return err
		}
		return writeProfileReport(ctx.ProjectRoot, quartetProfileReport{
			Type: profileReportType, FormatVersion: 1, Status: "ok", Operation: "rollback_recovered",
			TransactionID: state.TransactionID, ProfileID: state.ProfileID,
			TargetRelativePath: state.TargetRelativePath, ObservedTargetSHA256: currentHash,
			ExpectedTargetSHA256: state.BaselineSHA256, BaselineSHA256: state.BaselineSHA256,
			BackupRelativePath: state.BackupRelativePath, StateStatus: state.Status,
			GeneratedUTC: utcNow(), NextAction: "baseline restored; another profile may now be activated",
		})
	}
	if currentHash != state.ActiveProfileSHA256 {
		return fmt.Errorf("rollback refused: installed PACK11 no longer matches active profile SHA-256; got %s (%d bytes), expected %s", currentHash, currentSize, state.ActiveProfileSHA256)
	}
	backup, err := secureJoin(ctx.ProjectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	backupHash, backupSize, err := checkedFile(backup)
	if err != nil {
		return fmt.Errorf("inspect rollback backup: %w", err)
	}
	if backupHash != state.BaselineSHA256 || backupSize != state.ObservedBeforeSize {
		return fmt.Errorf("rollback backup checksum mismatch: got %s (%d bytes)", backupHash, backupSize)
	}
	state.Status = "rolling_back"
	state.UpdatedUTC = utcNow()
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	if err := atomicReplaceVerified(backup, target, state.BaselineSHA256, state.ObservedBeforeSize, state.ActiveProfileSHA256, state.BaselineSHA256); err != nil {
		return fmt.Errorf("rollback profile: %w", err)
	}
	finalHash, finalSize, err := checkedFile(target)
	if err != nil {
		return err
	}
	if finalHash != config.BaselineSHA256 || finalSize != config.BaselineSize {
		return fmt.Errorf("rollback did not restore exact stage-25 baseline")
	}
	state.Status = "rolled_back"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "rollback"
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	if err := writeProfileReport(ctx.ProjectRoot, quartetProfileReport{
		Type: profileReportType, FormatVersion: 1, Status: "ok", Operation: "rollback",
		TransactionID: state.TransactionID, ProfileID: state.ProfileID, Classification: state.Classification,
		Confidence: state.Confidence, TargetRelativePath: state.TargetRelativePath,
		ObservedTargetSHA256: finalHash, ExpectedTargetSHA256: state.BaselineSHA256,
		BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: "baseline verified; activate the next profile only when ready",
	}); err != nil {
		return err
	}
	fmt.Printf("Rolled back profile: %s\nRestored SHA-256: %s\n", state.ProfileID, finalHash)
	return nil
}

func statusQuartetProfile(raw profileCommandContext) error {
	ctx, err := normalizeProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetProfileConfig(ctx.ConfigPath)
	if err != nil {
		return err
	}
	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()
	target, err := secureJoin(ctx.GameRoot, config.TargetRelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return err
	}
	state, exists, err := readProfileState(profileStatePath(ctx.ProjectRoot))
	if err != nil {
		return err
	}
	report := quartetProfileReport{
		Type: profileReportType, FormatVersion: 1, Status: "ok", Operation: "status",
		TargetRelativePath: config.TargetRelativePath, ObservedTargetSHA256: currentHash,
		BaselineSHA256: config.BaselineSHA256, GeneratedUTC: utcNow(),
	}
	if !exists {
		if currentHash == config.BaselineSHA256 && currentSize == config.BaselineSize {
			report.StateStatus = "inactive_baseline_verified"
			report.ExpectedTargetSHA256 = config.BaselineSHA256
			report.NextAction = "activate the high-confidence profile first"
		} else {
			report.Status = "drift"
			report.StateStatus = "no_state_target_not_baseline"
			report.NextAction = "rerun restoration stages 25 and 26 before activation"
		}
	} else {
		report.TransactionID = state.TransactionID
		report.ProfileID = state.ProfileID
		report.Classification = state.Classification
		report.Confidence = state.Confidence
		report.BackupRelativePath = state.BackupRelativePath
		report.StateStatus = state.Status
		switch state.Status {
		case "active":
			report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
			if currentHash == state.ActiveProfileSHA256 {
				report.NextAction = "exit the game after testing, then rollback"
			} else {
				report.Status = "drift"
				report.NextAction = "do not rollback automatically; installed PACK11 changed after activation"
			}
		case "prepared":
			if currentHash == state.ActiveProfileSHA256 {
				report.StateStatus = "prepared_target_active_recoverable"
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "rerun activation for the same profile to finalize state, or rollback"
			} else if currentHash == state.BaselineSHA256 {
				report.StateStatus = "prepared_target_baseline_resumeable"
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "rerun activation for the same profile"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "rolling_back":
			if currentHash == state.BaselineSHA256 {
				report.StateStatus = "rolling_back_target_baseline_recoverable"
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "rerun rollback to finalize state"
			} else if currentHash == state.ActiveProfileSHA256 {
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "rerun rollback"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "activation_uncertain":
			if currentHash == state.ActiveProfileSHA256 {
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "rollback is checksum-gated and may be used to recover"
			} else if currentHash == state.BaselineSHA256 {
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "baseline remains installed; inspect the failed transaction before retrying"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "rolled_back":
			report.ExpectedTargetSHA256 = state.BaselineSHA256
			if currentHash == state.BaselineSHA256 {
				report.NextAction = "baseline verified; another profile may be activated"
			} else {
				report.Status = "drift"
				report.NextAction = "rerun restoration stages 25 and 26"
			}
		default:
			report.Status = "attention"
			report.NextAction = "inspect state and target before continuing"
		}
	}
	if err := writeProfileReport(ctx.ProjectRoot, report); err != nil {
		return err
	}
	fmt.Printf("State: %s\nTarget SHA-256: %s\nTarget bytes: %d\n", report.StateStatus, currentHash, currentSize)
	if report.ProfileID != "" {
		fmt.Printf("Profile: %s\nTransaction: %s\n", report.ProfileID, report.TransactionID)
	}
	if report.Status == "drift" {
		return fmt.Errorf("transaction state or installed target has drifted")
	}
	return nil
}

func findQuartetProfile(config quartetProfileConfig, profileID string) (quartetProfile, error) {
	for _, profile := range config.Profiles {
		if profile.ProfileID == profileID {
			return profile, nil
		}
	}
	ids := make([]string, 0, len(config.Profiles))
	for _, profile := range config.Profiles {
		ids = append(ids, profile.ProfileID)
	}
	sort.Strings(ids)
	return quartetProfile{}, fmt.Errorf("unknown profile %q; available: %s", profileID, strings.Join(ids, ", "))
}

func verifyProfileSource(path string, profile quartetProfile) error {
	hash, size, err := checkedFile(path)
	if err != nil {
		return fmt.Errorf("inspect local profile source: %w", err)
	}
	if hash != profile.SourceSHA256 || size != profile.SourceSize {
		return fmt.Errorf("local profile source checksum mismatch for %s: got %s (%d bytes)", profile.ProfileID, hash, size)
	}
	return nil
}

func verifyStateBackup(projectRoot string, state quartetProfileState) error {
	path, err := secureJoin(projectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	hash, size, err := checkedFile(path)
	if err != nil {
		return fmt.Errorf("inspect transaction backup: %w", err)
	}
	if hash != state.BaselineSHA256 || size != state.ObservedBeforeSize {
		return fmt.Errorf("transaction backup no longer matches recorded baseline")
	}
	return nil
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

func readProfileState(path string) (quartetProfileState, bool, error) {
	var state quartetProfileState
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, false, nil
	}
	if err != nil {
		return state, false, err
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return state, false, fmt.Errorf("parse transaction state: %w", err)
	}
	if state.Type != profileStateType || state.FormatVersion != 1 {
		return state, false, fmt.Errorf("unsupported transaction state")
	}
	return state, true, nil
}

func writeProfileReport(projectRoot string, report quartetProfileReport) error {
	latest := filepath.Join(projectRoot, ".local", "reports", "core", "BR_QUARTET_EVENT_PROFILE_TRANSACTION_REPORT.json")
	if err := writeJSONAtomic(latest, report, 0o600); err != nil {
		return err
	}
	stamp := strings.ReplaceAll(report.GeneratedUTC, ":", "")
	stamp = strings.ReplaceAll(stamp, "-", "")
	history := filepath.Join(projectRoot, ".local", "reports", "core", "quartet_event_profiles", stamp+"_"+report.Operation+".json")
	return writeJSONAtomic(history, report, 0o600)
}

func profileStatePath(projectRoot string) string {
	return filepath.Join(projectRoot, ".local", "state", "core_unified_patcher", "quartet_event_profile.json")
}

func transactionID() string {
	return time.Now().UTC().Format("20060102T150405.000000000Z") + fmt.Sprintf("-%d", os.Getpid())
}

func utcNow() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}
