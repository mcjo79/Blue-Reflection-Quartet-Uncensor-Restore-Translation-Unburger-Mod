package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	shaderProfileConfigType = "br_quartet_restoration_shader_profiles"
	shaderProfileStateType  = "br_core_quartet_shader_profile_state"
	shaderProfileReportType = "br_core_quartet_shader_profile_transaction_report"
)

type quartetShaderProfileConfig struct {
	Type               string                 `json:"type"`
	FormatVersion      int                    `json:"format_version"`
	RequestToolVersion string                 `json:"request_tool_version"`
	TransactionOwner   string                 `json:"transaction_owner"`
	Status             string                 `json:"status"`
	TargetRelativePath string                 `json:"target_relative_path"`
	BaselineSHA256     string                 `json:"baseline_sha256"`
	BaselineSize       int64                  `json:"baseline_size"`
	Profiles           []quartetShaderProfile `json:"profiles"`
}

type quartetShaderProfile struct {
	ProfileID                            string `json:"profile_id"`
	RuleID                               string `json:"rule_id"`
	Domain                               string `json:"domain"`
	Priority                             string `json:"priority"`
	TestOrder                            int    `json:"test_order"`
	SourceRelativePath                   string `json:"source_relative_path"`
	SourceSHA256                         string `json:"source_sha256"`
	SourceSize                           int64  `json:"source_size"`
	ExpectedTargetSHA256BeforeActivation string `json:"expected_target_sha256_before_activation"`
	ExpectedTargetSHA256AfterActivation  string `json:"expected_target_sha256_after_activation"`
	ExpectedTargetSHA256BeforeRollback   string `json:"expected_target_sha256_before_rollback"`
	SelectedMembers                      int    `json:"selected_members"`
	RuntimeValidated                     bool   `json:"runtime_validated"`
}

type quartetShaderProfileState struct {
	Type                   string `json:"type"`
	FormatVersion          int    `json:"format_version"`
	Status                 string `json:"status"`
	TransactionID          string `json:"transaction_id"`
	ProfileID              string `json:"profile_id"`
	RuleID                 string `json:"rule_id"`
	Domain                 string `json:"domain"`
	Priority               string `json:"priority"`
	TestOrder              int    `json:"test_order"`
	RuntimeValidated       bool   `json:"runtime_validated"`
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

type quartetShaderProfileReport struct {
	Type                 string `json:"type"`
	FormatVersion        int    `json:"format_version"`
	Status               string `json:"status"`
	Operation            string `json:"operation"`
	TransactionID        string `json:"transaction_id,omitempty"`
	ProfileID            string `json:"profile_id,omitempty"`
	RuleID               string `json:"rule_id,omitempty"`
	Domain               string `json:"domain,omitempty"`
	Priority             string `json:"priority,omitempty"`
	TestOrder            int    `json:"test_order,omitempty"`
	RuntimeValidated     bool   `json:"runtime_validated"`
	TargetRelativePath   string `json:"target_relative_path"`
	ObservedTargetSHA256 string `json:"observed_target_sha256"`
	ExpectedTargetSHA256 string `json:"expected_target_sha256,omitempty"`
	BaselineSHA256       string `json:"baseline_sha256"`
	BackupRelativePath   string `json:"backup_relative_path,omitempty"`
	StateStatus          string `json:"state_status"`
	GeneratedUTC         string `json:"generated_utc"`
	NextAction           string `json:"next_action"`
}

func commandQuartetShaderProfileActivate(args []string) error {
	flags := flag.NewFlagSet("quartet-shader-profile-activate", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 1 {
		return fmt.Errorf("exactly one shader profile ID is required")
	}
	return activateQuartetShaderProfile(*ctx, flags.Arg(0))
}

func commandQuartetShaderProfileStatus(args []string) error {
	flags := flag.NewFlagSet("quartet-shader-profile-status", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("quartet-shader-profile-status accepts no positional arguments")
	}
	return statusQuartetShaderProfile(*ctx)
}

func commandQuartetShaderProfileRollback(args []string) error {
	flags := flag.NewFlagSet("quartet-shader-profile-rollback", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("quartet-shader-profile-rollback accepts no positional arguments")
	}
	return rollbackQuartetShaderProfile(*ctx)
}

func normalizeShaderProfileContext(ctx profileCommandContext) (profileCommandContext, error) {
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
		configPath = filepath.Join(projectRoot, "config", "quartet_restoration_shader_profiles.json")
	} else if !filepath.IsAbs(configPath) {
		configPath = filepath.Join(projectRoot, configPath)
	}
	ctx.ProjectRoot = projectRoot
	ctx.GameRoot = gameRoot
	ctx.ConfigPath = filepath.Clean(configPath)
	return ctx, nil
}

func loadQuartetShaderProfileConfig(path string) (quartetShaderProfileConfig, error) {
	var config quartetShaderProfileConfig
	data, err := os.ReadFile(path)
	if err != nil {
		return config, fmt.Errorf("read shader profile config: %w", err)
	}
	if err := json.Unmarshal(data, &config); err != nil {
		return config, fmt.Errorf("parse shader profile config: %w", err)
	}
	if config.Type != shaderProfileConfigType || config.FormatVersion != 1 {
		return config, fmt.Errorf("unsupported shader profile config")
	}
	if config.TransactionOwner != "core_unified_patcher" {
		return config, fmt.Errorf("shader profile config has wrong transaction owner")
	}
	if config.TargetRelativePath != "Data/PACK10_01.PAK" {
		return config, fmt.Errorf("shader profile config targets unexpected archive: %s", config.TargetRelativePath)
	}
	if err := validateRelativePath(config.TargetRelativePath); err != nil {
		return config, fmt.Errorf("invalid shader target path: %w", err)
	}
	if err := validateSHA256(config.BaselineSHA256); err != nil || config.BaselineSize <= 0 {
		return config, fmt.Errorf("invalid shader baseline metadata")
	}
	if len(config.Profiles) == 0 {
		return config, fmt.Errorf("shader profile config contains no profiles")
	}
	seen := map[string]bool{}
	for _, profile := range config.Profiles {
		if profile.ProfileID == "" || seen[profile.ProfileID] {
			return config, fmt.Errorf("invalid or duplicate shader profile ID: %q", profile.ProfileID)
		}
		seen[profile.ProfileID] = true
		if profile.RuleID == "" || profile.Domain == "" || profile.Priority == "" || profile.TestOrder <= 0 {
			return config, fmt.Errorf("incomplete shader profile metadata for %s", profile.ProfileID)
		}
		if profile.RuntimeValidated {
			return config, fmt.Errorf("shader profile %s must remain runtime-unvalidated until an in-game scene test is recorded", profile.ProfileID)
		}
		if err := validateRelativePath(profile.SourceRelativePath); err != nil {
			return config, fmt.Errorf("invalid source path for %s: %w", profile.ProfileID, err)
		}
		if err := validateSHA256(profile.SourceSHA256); err != nil || profile.SourceSize <= 0 {
			return config, fmt.Errorf("invalid source metadata for %s", profile.ProfileID)
		}
		if profile.ExpectedTargetSHA256BeforeActivation != config.BaselineSHA256 ||
			profile.ExpectedTargetSHA256AfterActivation != profile.SourceSHA256 ||
			profile.ExpectedTargetSHA256BeforeRollback != profile.SourceSHA256 {
			return config, fmt.Errorf("inconsistent shader transaction hashes for %s", profile.ProfileID)
		}
	}
	return config, nil
}

func activateQuartetShaderProfile(raw profileCommandContext, profileID string) error {
	ctx, err := normalizeShaderProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetShaderProfileConfig(ctx.ConfigPath)
	if err != nil {
		return err
	}
	profile, err := findQuartetShaderProfile(config, profileID)
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
		return fmt.Errorf("inspect installed shader target: %w", err)
	}
	statePath := shaderProfileStatePath(ctx.ProjectRoot)
	state, stateExists, err := readShaderProfileState(statePath)
	if err != nil {
		return err
	}

	if stateExists && isOpenProfileState(state.Status) {
		if state.ProfileID != profile.ProfileID {
			return fmt.Errorf("shader profile %s already owns the open transaction; rollback first", state.ProfileID)
		}
		if state.Status == "active" {
			return fmt.Errorf("shader profile %s is already active", state.ProfileID)
		}
		if state.Status == "rolling_back" {
			return fmt.Errorf("shader rollback transaction is incomplete; run status, then rollback")
		}
		if state.Status == "activation_uncertain" {
			return fmt.Errorf("shader activation result is uncertain; run status and rollback if the active profile hash is installed")
		}
		if currentHash == state.ActiveProfileSHA256 {
			state.Status = "active"
			state.UpdatedUTC = utcNow()
			state.LastCompletedOperation = "activation_recovered"
			if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
				return err
			}
			return writeShaderProfileReport(ctx.ProjectRoot, quartetShaderProfileReport{
				Type: shaderProfileReportType, FormatVersion: 1, Status: "ok", Operation: "activate_recovered",
				TransactionID: state.TransactionID, ProfileID: state.ProfileID, RuleID: state.RuleID,
				Domain: state.Domain, Priority: state.Priority, TestOrder: state.TestOrder,
				RuntimeValidated: false, TargetRelativePath: state.TargetRelativePath,
				ObservedTargetSHA256: currentHash, ExpectedTargetSHA256: state.ActiveProfileSHA256,
				BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
				StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: shaderTestNextAction(state.ProfileID),
			})
		}
		if currentHash != config.BaselineSHA256 || currentSize != config.BaselineSize {
			return fmt.Errorf("prepared shader transaction target drifted: got %s (%d bytes)", currentHash, currentSize)
		}
		if err := verifyShaderStateBackup(ctx.ProjectRoot, state); err != nil {
			return err
		}
		if err := verifyShaderProfileSource(source, profile); err != nil {
			return err
		}
		return finishShaderProfileActivation(ctx, config, profile, state, source, target)
	}

	if currentHash != config.BaselineSHA256 || currentSize != config.BaselineSize {
		return fmt.Errorf("installed Data/PACK10_01.PAK is not the required stage-27 baseline: got %s (%d bytes); rerun restoration stages 27 and 28", currentHash, currentSize)
	}
	if err := verifyShaderProfileSource(source, profile); err != nil {
		return err
	}

	transactionID := transactionID()
	backupRel := filepath.ToSlash(filepath.Join(".local", "backups", "core_unified_patcher", "quartet_shader_profiles", transactionID, config.TargetRelativePath))
	backup, err := secureJoin(ctx.ProjectRoot, backupRel)
	if err != nil {
		return err
	}
	if err := copyFileDurable(target, backup, config.BaselineSHA256, config.BaselineSize, 0o600); err != nil {
		return fmt.Errorf("create core-managed shader backup: %w", err)
	}
	state = quartetShaderProfileState{
		Type: shaderProfileStateType, FormatVersion: 1, Status: "prepared", TransactionID: transactionID,
		ProfileID: profile.ProfileID, RuleID: profile.RuleID, Domain: profile.Domain,
		Priority: profile.Priority, TestOrder: profile.TestOrder, RuntimeValidated: false,
		TargetRelativePath: config.TargetRelativePath, SourceRelativePath: profile.SourceRelativePath,
		BackupRelativePath: backupRel, BaselineSHA256: config.BaselineSHA256,
		ActiveProfileSHA256: profile.SourceSHA256, ObservedBeforeSHA256: currentHash,
		ObservedBeforeSize: currentSize, CreatedUTC: utcNow(), UpdatedUTC: utcNow(),
	}
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return fmt.Errorf("record prepared shader transaction: %w", err)
	}
	return finishShaderProfileActivation(ctx, config, profile, state, source, target)
}

func finishShaderProfileActivation(ctx profileCommandContext, config quartetShaderProfileConfig, profile quartetShaderProfile, state quartetShaderProfileState, source, target string) error {
	if err := atomicReplaceVerified(source, target, profile.SourceSHA256, profile.SourceSize, config.BaselineSHA256, profile.SourceSHA256); err != nil {
		state.UpdatedUTC = utcNow()
		observed, _, inspectErr := checkedFile(target)
		if inspectErr == nil && observed == config.BaselineSHA256 {
			state.Status = "activation_failed"
		} else {
			state.Status = "activation_uncertain"
		}
		_ = writeJSONAtomic(shaderProfileStatePath(ctx.ProjectRoot), state, 0o600)
		return fmt.Errorf("activate shader profile: %w", err)
	}
	state.Status = "active"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "activate"
	if err := writeJSONAtomic(shaderProfileStatePath(ctx.ProjectRoot), state, 0o600); err != nil {
		return fmt.Errorf("record active shader transaction: %w", err)
	}
	if err := writeShaderProfileReport(ctx.ProjectRoot, quartetShaderProfileReport{
		Type: shaderProfileReportType, FormatVersion: 1, Status: "ok", Operation: "activate",
		TransactionID: state.TransactionID, ProfileID: profile.ProfileID, RuleID: profile.RuleID,
		Domain: profile.Domain, Priority: profile.Priority, TestOrder: profile.TestOrder,
		RuntimeValidated: false, TargetRelativePath: config.TargetRelativePath,
		ObservedTargetSHA256: profile.SourceSHA256, ExpectedTargetSHA256: profile.SourceSHA256,
		BaselineSHA256: config.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: shaderTestNextAction(profile.ProfileID),
	}); err != nil {
		return err
	}
	fmt.Printf("Activated shader profile: %s\nTransaction: %s\nInstalled SHA-256: %s\nRuntime validated: false\n", profile.ProfileID, state.TransactionID, profile.SourceSHA256)
	return nil
}

func rollbackQuartetShaderProfile(raw profileCommandContext) error {
	ctx, err := normalizeShaderProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetShaderProfileConfig(ctx.ConfigPath)
	if err != nil {
		return err
	}
	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()

	statePath := shaderProfileStatePath(ctx.ProjectRoot)
	state, exists, err := readShaderProfileState(statePath)
	if err != nil {
		return err
	}
	if !exists {
		return fmt.Errorf("no core-managed shader-profile transaction exists")
	}
	if !isOpenProfileState(state.Status) {
		return fmt.Errorf("no active shader profile can be rolled back; state is %s", state.Status)
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
		return writeShaderProfileReport(ctx.ProjectRoot, quartetShaderProfileReport{
			Type: shaderProfileReportType, FormatVersion: 1, Status: "ok", Operation: "rollback_recovered",
			TransactionID: state.TransactionID, ProfileID: state.ProfileID, RuleID: state.RuleID,
			Domain: state.Domain, Priority: state.Priority, TestOrder: state.TestOrder,
			RuntimeValidated: false, TargetRelativePath: state.TargetRelativePath,
			ObservedTargetSHA256: currentHash, ExpectedTargetSHA256: state.BaselineSHA256,
			BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
			StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: "stage-27 baseline restored; the next shader profile may now be activated",
		})
	}
	if currentHash != state.ActiveProfileSHA256 {
		return fmt.Errorf("rollback refused: installed PACK10_01 no longer matches active shader profile SHA-256; got %s (%d bytes), expected %s", currentHash, currentSize, state.ActiveProfileSHA256)
	}
	backup, err := secureJoin(ctx.ProjectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	backupHash, backupSize, err := checkedFile(backup)
	if err != nil {
		return fmt.Errorf("inspect shader rollback backup: %w", err)
	}
	if backupHash != state.BaselineSHA256 || backupSize != state.ObservedBeforeSize {
		return fmt.Errorf("shader rollback backup checksum mismatch: got %s (%d bytes)", backupHash, backupSize)
	}
	state.Status = "rolling_back"
	state.UpdatedUTC = utcNow()
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	if err := atomicReplaceVerified(backup, target, state.BaselineSHA256, state.ObservedBeforeSize, state.ActiveProfileSHA256, state.BaselineSHA256); err != nil {
		return fmt.Errorf("rollback shader profile: %w", err)
	}
	finalHash, finalSize, err := checkedFile(target)
	if err != nil {
		return err
	}
	if finalHash != config.BaselineSHA256 || finalSize != config.BaselineSize {
		return fmt.Errorf("shader rollback did not restore exact stage-27 baseline")
	}
	state.Status = "rolled_back"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "rollback"
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	if err := writeShaderProfileReport(ctx.ProjectRoot, quartetShaderProfileReport{
		Type: shaderProfileReportType, FormatVersion: 1, Status: "ok", Operation: "rollback",
		TransactionID: state.TransactionID, ProfileID: state.ProfileID, RuleID: state.RuleID,
		Domain: state.Domain, Priority: state.Priority, TestOrder: state.TestOrder,
		RuntimeValidated: false, TargetRelativePath: state.TargetRelativePath,
		ObservedTargetSHA256: finalHash, ExpectedTargetSHA256: state.BaselineSHA256,
		BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		StateStatus: state.Status, GeneratedUTC: utcNow(), NextAction: "exact stage-27 baseline verified; activate the next shader profile only when ready",
	}); err != nil {
		return err
	}
	fmt.Printf("Rolled back shader profile: %s\nRestored SHA-256: %s\n", state.ProfileID, finalHash)
	return nil
}

func statusQuartetShaderProfile(raw profileCommandContext) error {
	ctx, err := normalizeShaderProfileContext(raw)
	if err != nil {
		return err
	}
	config, err := loadQuartetShaderProfileConfig(ctx.ConfigPath)
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
	state, exists, err := readShaderProfileState(shaderProfileStatePath(ctx.ProjectRoot))
	if err != nil {
		return err
	}
	report := quartetShaderProfileReport{
		Type: shaderProfileReportType, FormatVersion: 1, Status: "ok", Operation: "status",
		RuntimeValidated: false, TargetRelativePath: config.TargetRelativePath,
		ObservedTargetSHA256: currentHash, BaselineSHA256: config.BaselineSHA256, GeneratedUTC: utcNow(),
	}
	if !exists {
		if currentHash == config.BaselineSHA256 && currentSize == config.BaselineSize {
			report.StateStatus = "inactive_baseline_verified"
			report.ExpectedTargetSHA256 = config.BaselineSHA256
			report.NextAction = "ensure no event profile is active, then activate height_fog_shader_original_code first"
		} else {
			report.Status = "drift"
			report.StateStatus = "no_state_target_not_baseline"
			report.NextAction = "rerun restoration stages 27 and 28 before shader activation"
		}
	} else {
		report.TransactionID = state.TransactionID
		report.ProfileID = state.ProfileID
		report.RuleID = state.RuleID
		report.Domain = state.Domain
		report.Priority = state.Priority
		report.TestOrder = state.TestOrder
		report.BackupRelativePath = state.BackupRelativePath
		report.StateStatus = state.Status
		switch state.Status {
		case "active":
			report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
			if currentHash == state.ActiveProfileSHA256 {
				report.NextAction = shaderTestNextAction(state.ProfileID)
			} else {
				report.Status = "drift"
				report.NextAction = "do not rollback automatically; installed PACK10_01 changed after shader activation"
			}
		case "prepared":
			if currentHash == state.ActiveProfileSHA256 {
				report.StateStatus = "prepared_target_active_recoverable"
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "rerun activation for the same shader profile to finalize state, or rollback"
			} else if currentHash == state.BaselineSHA256 {
				report.StateStatus = "prepared_target_baseline_resumeable"
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "rerun activation for the same shader profile"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "rolling_back":
			if currentHash == state.BaselineSHA256 {
				report.StateStatus = "rolling_back_target_baseline_recoverable"
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "rerun shader rollback to finalize state"
			} else if currentHash == state.ActiveProfileSHA256 {
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "rerun shader rollback"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "activation_uncertain":
			if currentHash == state.ActiveProfileSHA256 {
				report.ExpectedTargetSHA256 = state.ActiveProfileSHA256
				report.NextAction = "shader rollback is checksum-gated and may be used to recover"
			} else if currentHash == state.BaselineSHA256 {
				report.ExpectedTargetSHA256 = state.BaselineSHA256
				report.NextAction = "stage-27 baseline remains installed; inspect the failed transaction before retrying"
			} else {
				report.Status = "drift"
				report.NextAction = "manual inspection required"
			}
		case "rolled_back":
			report.ExpectedTargetSHA256 = state.BaselineSHA256
			if currentHash == state.BaselineSHA256 && currentSize == config.BaselineSize {
				report.NextAction = "exact stage-27 baseline verified; another shader profile may be activated"
			} else {
				report.Status = "drift"
				report.NextAction = "rerun restoration stages 27 and 28"
			}
		default:
			report.Status = "attention"
			report.NextAction = "inspect shader state and target before continuing"
		}
	}
	if err := writeShaderProfileReport(ctx.ProjectRoot, report); err != nil {
		return err
	}
	fmt.Printf("Shader state: %s\nTarget SHA-256: %s\nTarget bytes: %d\nRuntime validated: false\n", report.StateStatus, currentHash, currentSize)
	if report.ProfileID != "" {
		fmt.Printf("Shader profile: %s\nTransaction: %s\n", report.ProfileID, report.TransactionID)
	}
	if report.Status == "drift" {
		return fmt.Errorf("shader transaction state or installed target has drifted")
	}
	return nil
}

func findQuartetShaderProfile(config quartetShaderProfileConfig, profileID string) (quartetShaderProfile, error) {
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
	return quartetShaderProfile{}, fmt.Errorf("unknown shader profile %q; available: %s", profileID, strings.Join(ids, ", "))
}

func verifyShaderProfileSource(path string, profile quartetShaderProfile) error {
	hash, size, err := checkedFile(path)
	if err != nil {
		return fmt.Errorf("inspect local shader profile source: %w", err)
	}
	if hash != profile.SourceSHA256 || size != profile.SourceSize {
		return fmt.Errorf("local shader profile source checksum mismatch for %s: got %s (%d bytes)", profile.ProfileID, hash, size)
	}
	return nil
}

func verifyShaderStateBackup(projectRoot string, state quartetShaderProfileState) error {
	path, err := secureJoin(projectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	hash, size, err := checkedFile(path)
	if err != nil {
		return fmt.Errorf("inspect shader transaction backup: %w", err)
	}
	if hash != state.BaselineSHA256 || size != state.ObservedBeforeSize {
		return fmt.Errorf("shader transaction backup no longer matches recorded baseline")
	}
	return nil
}

func readShaderProfileState(path string) (quartetShaderProfileState, bool, error) {
	var state quartetShaderProfileState
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, false, nil
	}
	if err != nil {
		return state, false, err
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return state, false, fmt.Errorf("parse shader transaction state: %w", err)
	}
	if state.Type != shaderProfileStateType || state.FormatVersion != 1 {
		return state, false, fmt.Errorf("unsupported shader transaction state")
	}
	return state, true, nil
}

func writeShaderProfileReport(projectRoot string, report quartetShaderProfileReport) error {
	latest := filepath.Join(projectRoot, ".local", "reports", "core", "BR_QUARTET_SHADER_PROFILE_TRANSACTION_REPORT.json")
	if err := writeJSONAtomic(latest, report, 0o600); err != nil {
		return err
	}
	stamp := strings.ReplaceAll(report.GeneratedUTC, ":", "")
	stamp = strings.ReplaceAll(stamp, "-", "")
	history := filepath.Join(projectRoot, ".local", "reports", "core", "quartet_shader_profiles", stamp+"_"+report.Operation+".json")
	return writeJSONAtomic(history, report, 0o600)
}

func shaderProfileStatePath(projectRoot string) string {
	return filepath.Join(projectRoot, ".local", "state", "core_unified_patcher", "quartet_shader_profile.json")
}

func isOpenProfileState(status string) bool {
	return status == "active" || status == "prepared" || status == "rolling_back" || status == "activation_uncertain"
}

func shaderTestNextAction(profileID string) string {
	switch profileID {
	case "height_fog_shader_original_code":
		return "with no event profile active, test a scene with visible steam or height fog, exit the game, then rollback"
	case "water_shader_swater_original_code":
		return "with no event profile active, test a pool or other visibly active swater surface, exit the game, then rollback"
	default:
		return "run only the matching isolated shader scene test, exit the game, then rollback"
	}
}
