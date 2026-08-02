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

const localProfileStateType = "br_core_quartet_local_profile_state"

type localProfileState struct {
	Type                   string `json:"type"`
	FormatVersion          int    `json:"format_version"`
	Status                 string `json:"status"`
	TransactionID          string `json:"transaction_id"`
	ProfileID              string `json:"profile_id"`
	TargetRelativePath     string `json:"target_relative_path"`
	SourceRelativePath     string `json:"source_relative_path"`
	ManifestRelativePath   string `json:"manifest_relative_path,omitempty"`
	BackupRelativePath     string `json:"backup_relative_path"`
	BaselineSHA256         string `json:"baseline_sha256"`
	BaselineSize           int64  `json:"baseline_size,omitempty"`
	ActiveProfileSHA256    string `json:"active_profile_sha256"`
	ActiveProfileSize      int64  `json:"active_profile_size,omitempty"`
	ObservedBeforeSHA256   string `json:"observed_before_sha256"`
	ObservedBeforeSize     int64  `json:"observed_before_size"`
	RuntimeValidated       bool   `json:"runtime_validated"`
	WorkstreamID           string `json:"workstream_id,omitempty"`
	WorkstreamVersion      string `json:"workstream_version,omitempty"`
	CreatedUTC             string `json:"created_utc"`
	UpdatedUTC             string `json:"updated_utc"`
	LastCompletedOperation string `json:"last_completed_operation,omitempty"`
}

type localProfileTransactionReport struct {
	Type                 string `json:"type"`
	FormatVersion        int    `json:"format_version"`
	Status               string `json:"status"`
	Operation            string `json:"operation"`
	TransactionID        string `json:"transaction_id,omitempty"`
	ProfileID            string `json:"profile_id,omitempty"`
	TargetRelativePath   string `json:"target_relative_path"`
	ObservedTargetSHA256 string `json:"observed_target_sha256"`
	ExpectedTargetSHA256 string `json:"expected_target_sha256,omitempty"`
	BaselineSHA256       string `json:"baseline_sha256,omitempty"`
	BackupRelativePath   string `json:"backup_relative_path,omitempty"`
	RuntimeValidated     bool   `json:"runtime_validated"`
	StateStatus          string `json:"state_status"`
	ManifestPath         string `json:"manifest_path,omitempty"`
	GeneratedUTC         string `json:"generated_utc"`
	NextAction           string `json:"next_action"`
}

func commandDiscoveredProfileActivate(args []string, requiredTarget string) error {
	flags := flag.NewFlagSet("quartet-local-profile-activate", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 1 {
		return fmt.Errorf("exactly one profile ID is required")
	}
	return activateDiscoveredProfile(*ctx, requiredTarget, flags.Arg(0))
}

func commandDiscoveredProfileStatus(args []string, requiredTarget string) error {
	flags := flag.NewFlagSet("quartet-local-profile-status", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("status accepts no positional arguments")
	}
	return statusDiscoveredProfile(*ctx, requiredTarget)
}

func commandDiscoveredProfileRollback(args []string, requiredTarget string) error {
	flags := flag.NewFlagSet("quartet-local-profile-rollback", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("rollback accepts no positional arguments")
	}
	return rollbackDiscoveredProfile(*ctx, requiredTarget)
}

func commandDiscoveredProfileList(args []string) error {
	flags := flag.NewFlagSet("quartet-local-profile-list", flag.ContinueOnError)
	ctx := addProfileCommonFlags(flags)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return fmt.Errorf("list accepts no positional arguments")
	}
	return listDiscoveredProfiles(*ctx)
}

func normalizeLocalProfileContext(ctx profileCommandContext) (profileCommandContext, error) {
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
	if info, err := os.Stat(projectRoot); err != nil || !info.IsDir() {
		return ctx, fmt.Errorf("invalid project root: %s", projectRoot)
	}
	if info, err := os.Stat(gameRoot); err != nil || !info.IsDir() {
		return ctx, fmt.Errorf("invalid game root: %s", gameRoot)
	}
	ctx.ProjectRoot = filepath.Clean(projectRoot)
	ctx.GameRoot = filepath.Clean(gameRoot)
	ctx.ConfigPath = ""
	return ctx, nil
}

func activateDiscoveredProfile(raw profileCommandContext, requiredTarget, profileID string) error {
	ctx, err := normalizeLocalProfileContext(raw)
	if err != nil {
		return err
	}
	spec, ok := localProfileTargets[requiredTarget]
	if !ok {
		return fmt.Errorf("unsupported target: %s", requiredTarget)
	}
	registry, err := discoverLocalProfiles(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	profile, err := selectDiscoveredProfile(registry, profileID, requiredTarget)
	if err != nil {
		return err
	}

	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()

	if err := rejectOtherTargetTransaction(ctx.ProjectRoot, spec); err != nil {
		return err
	}
	statePath, err := secureJoin(ctx.ProjectRoot, spec.StatePath)
	if err != nil {
		return err
	}
	state, stateExists, err := readLocalProfileState(statePath, spec)
	if err != nil {
		return err
	}
	target, err := secureJoin(ctx.GameRoot, spec.RelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return fmt.Errorf("inspect installed target: %w", err)
	}

	if stateExists && isOpenProfileState(state.Status) {
		if state.ProfileID != profileID {
			return fmt.Errorf("profile %s already owns the open %s transaction; rollback first", state.ProfileID, spec.Kind)
		}
		if state.TargetRelativePath != spec.RelativePath {
			return fmt.Errorf("existing transaction targets %s, expected %s", state.TargetRelativePath, spec.RelativePath)
		}
		if state.Status == "active" {
			return fmt.Errorf("profile %s is already active", profileID)
		}
		if state.Status == "rolling_back" {
			return fmt.Errorf("rollback transaction is incomplete; run status, then rollback")
		}
		if currentHash == state.ActiveProfileSHA256 {
			state.Status = "active"
			state.UpdatedUTC = utcNow()
			state.LastCompletedOperation = "activation_recovered"
			if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
				return err
			}
			return writeLocalProfileReport(ctx.ProjectRoot, spec, localProfileTransactionReport{
				Type: spec.ReportType, FormatVersion: 2, Status: "ok", Operation: "activate_recovered",
				TransactionID: state.TransactionID, ProfileID: state.ProfileID, TargetRelativePath: spec.RelativePath,
				ObservedTargetSHA256: currentHash, ExpectedTargetSHA256: state.ActiveProfileSHA256,
				BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
				RuntimeValidated: state.RuntimeValidated, StateStatus: state.Status,
				ManifestPath: state.ManifestRelativePath, GeneratedUTC: utcNow(), NextAction: localProfileNextAction(spec, state.ProfileID),
			})
		}
		if currentHash != state.BaselineSHA256 || currentSize != effectiveBaselineSize(state) {
			return fmt.Errorf("prepared transaction target drifted: got %s (%d bytes)", currentHash, currentSize)
		}
		if err := verifyLocalStateBackup(ctx.ProjectRoot, state); err != nil {
			return err
		}
		if err := verifyDiscoveredProfileAgain(ctx.ProjectRoot, profile); err != nil {
			return err
		}
		return finishDiscoveredActivation(ctx, spec, profile, state, target, statePath)
	}

	manifest := profile.Manifest
	if currentHash != manifest.BaselineSHA256 || currentSize != manifest.BaselineSize {
		return fmt.Errorf("installed %s does not match the profile baseline: got %s (%d bytes), expected %s (%d bytes)", spec.RelativePath, currentHash, currentSize, manifest.BaselineSHA256, manifest.BaselineSize)
	}
	if err := verifyDiscoveredProfileAgain(ctx.ProjectRoot, profile); err != nil {
		return err
	}

	transaction := transactionID()
	targetKey := strings.NewReplacer("/", "_", "\\", "_", ".", "_").Replace(spec.RelativePath)
	backupRel := filepath.ToSlash(filepath.Join(".local", "backups", "core_unified_patcher", "quartet_local_profiles", targetKey, transaction, spec.RelativePath))
	backupPath, err := secureJoin(ctx.ProjectRoot, backupRel)
	if err != nil {
		return err
	}
	if err := copyFileDurable(target, backupPath, manifest.BaselineSHA256, manifest.BaselineSize, 0o600); err != nil {
		return fmt.Errorf("create core-managed backup: %w", err)
	}
	state = localProfileState{
		Type: localProfileStateType, FormatVersion: 2, Status: "prepared", TransactionID: transaction,
		ProfileID: profileID, TargetRelativePath: spec.RelativePath,
		SourceRelativePath: manifest.LocalProfilePath, ManifestRelativePath: profile.ManifestPath,
		BackupRelativePath: backupRel, BaselineSHA256: manifest.BaselineSHA256, BaselineSize: manifest.BaselineSize,
		ActiveProfileSHA256: manifest.ProfileSHA256, ActiveProfileSize: manifest.ProfileSize,
		ObservedBeforeSHA256: currentHash, ObservedBeforeSize: currentSize,
		RuntimeValidated: manifest.RuntimeValidated, WorkstreamID: manifest.WorkstreamID,
		WorkstreamVersion: manifest.WorkstreamVersion, CreatedUTC: utcNow(), UpdatedUTC: utcNow(),
	}
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return fmt.Errorf("record prepared transaction: %w", err)
	}
	return finishDiscoveredActivation(ctx, spec, profile, state, target, statePath)
}

func finishDiscoveredActivation(ctx profileCommandContext, spec localProfileTargetSpec, profile discoveredLocalProfile, state localProfileState, target, statePath string) error {
	manifest := profile.Manifest
	if err := atomicReplaceVerified(profile.SourcePath, target, manifest.ProfileSHA256, manifest.ProfileSize, manifest.BaselineSHA256, manifest.ProfileSHA256); err != nil {
		state.UpdatedUTC = utcNow()
		observed, _, inspectErr := checkedFile(target)
		if inspectErr == nil && observed == manifest.BaselineSHA256 {
			state.Status = "activation_failed"
		} else {
			state.Status = "activation_uncertain"
		}
		_ = writeJSONAtomic(statePath, state, 0o600)
		return fmt.Errorf("activate profile: %w", err)
	}
	state.Status = "active"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "activate"
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return fmt.Errorf("record active transaction: %w", err)
	}
	if err := writeLocalProfileReport(ctx.ProjectRoot, spec, localProfileTransactionReport{
		Type: spec.ReportType, FormatVersion: 2, Status: "ok", Operation: "activate",
		TransactionID: state.TransactionID, ProfileID: state.ProfileID, TargetRelativePath: spec.RelativePath,
		ObservedTargetSHA256: manifest.ProfileSHA256, ExpectedTargetSHA256: manifest.ProfileSHA256,
		BaselineSHA256: manifest.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		RuntimeValidated: manifest.RuntimeValidated, StateStatus: state.Status,
		ManifestPath: profile.ManifestPath, GeneratedUTC: utcNow(), NextAction: localProfileNextAction(spec, state.ProfileID),
	}); err != nil {
		return err
	}
	fmt.Printf("Activated %s profile: %s\nTarget: %s\nTransaction: %s\nInstalled SHA-256: %s\nRuntime validated: %t\n", spec.Kind, state.ProfileID, spec.RelativePath, state.TransactionID, manifest.ProfileSHA256, manifest.RuntimeValidated)
	return nil
}

func rollbackDiscoveredProfile(raw profileCommandContext, requiredTarget string) error {
	ctx, err := normalizeLocalProfileContext(raw)
	if err != nil {
		return err
	}
	spec, ok := localProfileTargets[requiredTarget]
	if !ok {
		return fmt.Errorf("unsupported target: %s", requiredTarget)
	}
	unlock, err := acquireProfileLock(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	defer unlock()

	statePath, err := secureJoin(ctx.ProjectRoot, spec.StatePath)
	if err != nil {
		return err
	}
	state, exists, err := readLocalProfileState(statePath, spec)
	if err != nil {
		return err
	}
	if !exists {
		return fmt.Errorf("no %s profile transaction state exists", spec.Kind)
	}
	target, err := secureJoin(ctx.GameRoot, spec.RelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return fmt.Errorf("inspect installed target: %w", err)
	}
	if state.Status == "rolled_back" {
		if currentHash == state.BaselineSHA256 && currentSize == effectiveBaselineSize(state) {
			fmt.Printf("%s profile transaction is already rolled back; baseline verified.\n", spec.Kind)
			return nil
		}
		return fmt.Errorf("state says rolled_back but installed target does not match the recorded baseline")
	}
	if currentHash != state.ActiveProfileSHA256 || (state.ActiveProfileSize > 0 && currentSize != state.ActiveProfileSize) {
		return fmt.Errorf("rollback refused: installed %s no longer matches active profile %s; got %s (%d bytes)", spec.RelativePath, state.ProfileID, currentHash, currentSize)
	}
	if err := verifyLocalStateBackup(ctx.ProjectRoot, state); err != nil {
		return err
	}
	backupPath, err := secureJoin(ctx.ProjectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	state.Status = "rolling_back"
	state.UpdatedUTC = utcNow()
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	baselineSize := effectiveBaselineSize(state)
	if err := atomicReplaceVerified(backupPath, target, state.BaselineSHA256, baselineSize, state.ActiveProfileSHA256, state.BaselineSHA256); err != nil {
		state.Status = "rollback_uncertain"
		state.UpdatedUTC = utcNow()
		_ = writeJSONAtomic(statePath, state, 0o600)
		return fmt.Errorf("rollback profile: %w", err)
	}
	finalHash, finalSize, err := checkedFile(target)
	if err != nil {
		return err
	}
	if finalHash != state.BaselineSHA256 || finalSize != baselineSize {
		return fmt.Errorf("rollback result does not equal exact baseline")
	}
	state.Status = "rolled_back"
	state.UpdatedUTC = utcNow()
	state.LastCompletedOperation = "rollback"
	if err := writeJSONAtomic(statePath, state, 0o600); err != nil {
		return err
	}
	if err := writeLocalProfileReport(ctx.ProjectRoot, spec, localProfileTransactionReport{
		Type: spec.ReportType, FormatVersion: 2, Status: "ok", Operation: "rollback",
		TransactionID: state.TransactionID, ProfileID: state.ProfileID, TargetRelativePath: spec.RelativePath,
		ObservedTargetSHA256: finalHash, ExpectedTargetSHA256: state.BaselineSHA256,
		BaselineSHA256: state.BaselineSHA256, BackupRelativePath: state.BackupRelativePath,
		RuntimeValidated: state.RuntimeValidated, StateStatus: state.Status,
		ManifestPath: state.ManifestRelativePath, GeneratedUTC: utcNow(), NextAction: "baseline restored; another isolated profile may now be activated",
	}); err != nil {
		return err
	}
	fmt.Printf("Rolled back %s profile: %s\nTarget: %s\nBaseline SHA-256: %s\n", spec.Kind, state.ProfileID, spec.RelativePath, finalHash)
	return nil
}

func statusDiscoveredProfile(raw profileCommandContext, requiredTarget string) error {
	ctx, err := normalizeLocalProfileContext(raw)
	if err != nil {
		return err
	}
	spec, ok := localProfileTargets[requiredTarget]
	if !ok {
		return fmt.Errorf("unsupported target: %s", requiredTarget)
	}
	target, err := secureJoin(ctx.GameRoot, spec.RelativePath)
	if err != nil {
		return err
	}
	currentHash, currentSize, err := checkedFile(target)
	if err != nil {
		return fmt.Errorf("inspect installed target: %w", err)
	}
	statePath, err := secureJoin(ctx.ProjectRoot, spec.StatePath)
	if err != nil {
		return err
	}
	state, exists, err := readLocalProfileState(statePath, spec)
	if err != nil {
		return err
	}
	if !exists {
		registry, discoveryErr := discoverLocalProfiles(ctx.ProjectRoot)
		if discoveryErr != nil {
			return discoveryErr
		}
		baselineHash, baselineSize, consistent := baselineForTarget(registry, spec.RelativePath)
		status := "inactive_no_valid_profile_manifest"
		next := "generate valid quartet_restoration profile manifests"
		expected := ""
		if consistent {
			expected = baselineHash
			if currentHash == baselineHash && currentSize == baselineSize {
				status = "inactive_baseline_verified"
				next = "activate one discovered profile for this target"
			} else {
				status = "inactive_baseline_mismatch"
				next = "rebuild the restoration baseline/profile artifacts before activation"
			}
		}
		report := localProfileTransactionReport{
			Type: spec.ReportType, FormatVersion: 2, Status: status, Operation: "status",
			TargetRelativePath: spec.RelativePath, ObservedTargetSHA256: currentHash,
			ExpectedTargetSHA256: expected, BaselineSHA256: expected, RuntimeValidated: false,
			StateStatus: status, GeneratedUTC: utcNow(), NextAction: next,
		}
		if err := writeLocalProfileReport(ctx.ProjectRoot, spec, report); err != nil {
			return err
		}
		fmt.Printf("State: %s\nTarget: %s\nTarget SHA-256: %s\nTarget bytes: %d\n", status, spec.RelativePath, currentHash, currentSize)
		return nil
	}

	stateStatus := state.Status
	reportStatus := "ok"
	next := "inspect state before continuing"
	switch state.Status {
	case "active":
		if currentHash == state.ActiveProfileSHA256 && (state.ActiveProfileSize == 0 || currentSize == state.ActiveProfileSize) {
			next = localProfileNextAction(spec, state.ProfileID)
		} else {
			reportStatus = "drift"
			stateStatus = "active_target_mismatch"
			next = "do not rollback automatically; inspect the externally changed target"
		}
	case "prepared", "activation_uncertain":
		if currentHash == state.ActiveProfileSHA256 {
			next = "activation payload is installed; rerun activate to recover active state"
		} else if currentHash == state.BaselineSHA256 {
			next = "baseline remains installed; rerun activate or rollback to close the prepared transaction"
		} else {
			reportStatus = "drift"
			stateStatus = state.Status + "_target_mismatch"
			next = "inspect target and transaction backup"
		}
	case "rolling_back", "rollback_uncertain":
		if currentHash == state.BaselineSHA256 {
			next = "rerun rollback to record the completed baseline restoration"
		} else if currentHash == state.ActiveProfileSHA256 {
			next = "rerun rollback"
		} else {
			reportStatus = "drift"
			stateStatus = state.Status + "_target_mismatch"
			next = "inspect target and transaction backup"
		}
	case "rolled_back":
		if currentHash == state.BaselineSHA256 && currentSize == effectiveBaselineSize(state) {
			next = "baseline verified; another isolated profile may be activated"
		} else {
			reportStatus = "drift"
			stateStatus = "rolled_back_target_mismatch"
			next = "installed target changed after rollback"
		}
	default:
		reportStatus = "attention"
		next = "inspect unsupported transaction state"
	}
	if err := writeLocalProfileReport(ctx.ProjectRoot, spec, localProfileTransactionReport{
		Type: spec.ReportType, FormatVersion: 2, Status: reportStatus, Operation: "status",
		TransactionID: state.TransactionID, ProfileID: state.ProfileID, TargetRelativePath: spec.RelativePath,
		ObservedTargetSHA256: currentHash, BaselineSHA256: state.BaselineSHA256,
		RuntimeValidated: state.RuntimeValidated, StateStatus: stateStatus,
		BackupRelativePath: state.BackupRelativePath, ManifestPath: state.ManifestRelativePath,
		GeneratedUTC: utcNow(), NextAction: next,
	}); err != nil {
		return err
	}
	fmt.Printf("State: %s\nTarget: %s\nTarget SHA-256: %s\nTarget bytes: %d\nProfile: %s\nTransaction: %s\nRuntime validated: %t\n", stateStatus, spec.RelativePath, currentHash, currentSize, state.ProfileID, state.TransactionID, state.RuntimeValidated)
	if reportStatus == "drift" {
		return fmt.Errorf("transaction state or installed target has drifted")
	}
	return nil
}

func listDiscoveredProfiles(raw profileCommandContext) error {
	ctx, err := normalizeLocalProfileContext(raw)
	if err != nil {
		return err
	}
	registry, err := discoverLocalProfiles(ctx.ProjectRoot)
	if err != nil {
		return err
	}
	states := map[string]localProfileState{}
	stateExists := map[string]bool{}
	for target, spec := range localProfileTargets {
		statePath, joinErr := secureJoin(ctx.ProjectRoot, spec.StatePath)
		if joinErr != nil {
			return joinErr
		}
		state, exists, readErr := readLocalProfileState(statePath, spec)
		if readErr != nil {
			return readErr
		}
		states[target] = state
		stateExists[target] = exists
	}
	ids := make([]string, 0, len(registry.Profiles))
	for id := range registry.Profiles {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	fmt.Println("profile_id\ttarget\tlocal_file\truntime_validated\tactive\tbaseline")
	for _, id := range ids {
		profile := registry.Profiles[id]
		manifest := profile.Manifest
		spec := localProfileTargets[manifest.TargetRelativePath]
		targetPath, joinErr := secureJoin(ctx.GameRoot, spec.RelativePath)
		baselineStatus := "error"
		if joinErr == nil {
			hash, size, checkErr := checkedFile(targetPath)
			if checkErr == nil {
				if hash == manifest.BaselineSHA256 && size == manifest.BaselineSize {
					baselineStatus = "match"
				} else {
					baselineStatus = "mismatch"
				}
			} else if errors.Is(checkErr, os.ErrNotExist) {
				baselineStatus = "missing"
			}
		}
		active := "inactive"
		if stateExists[manifest.TargetRelativePath] {
			state := states[manifest.TargetRelativePath]
			if state.ProfileID == id && isOpenProfileState(state.Status) {
				active = state.Status
			}
		}
		fmt.Printf("%s\t%s\t%s\t%t\t%s\t%s\n", id, manifest.TargetRelativePath, profile.LocalStatus, manifest.RuntimeValidated, active, baselineStatus)
	}
	for _, issue := range registry.Issues {
		profileID := issue.ProfileID
		if profileID == "" {
			profileID = "<unknown>"
		}
		target := issue.TargetRelativePath
		if target == "" {
			target = "<unknown>"
		}
		fmt.Printf("%s\t%s\t%s\t%t\tinactive\tunknown\n", profileID, target, issue.Status, issue.RuntimeValidated)
	}
	if len(registry.Issues) > 0 {
		fmt.Println("\nRejected profile manifest details:")
		fmt.Println("profile_id\tmanifest\tstatus\terror")
		for _, issue := range registry.Issues {
			fmt.Printf("%s\t%s\t%s\t%s\n", issue.ProfileID, issue.ManifestPath, issue.Status, strings.ReplaceAll(issue.Error, "\t", " "))
		}
	}
	fmt.Printf("\nValid profiles: %d; rejected manifests: %d\n", len(registry.Profiles), len(registry.Issues))
	return nil
}

func selectDiscoveredProfile(registry localProfileRegistry, profileID, target string) (discoveredLocalProfile, error) {
	if profile, ok := registry.Profiles[profileID]; ok {
		if profile.Manifest.TargetRelativePath != target {
			return discoveredLocalProfile{}, fmt.Errorf("profile %q targets %s, not %s", profileID, profile.Manifest.TargetRelativePath, target)
		}
		return profile, nil
	}
	for _, issue := range registry.Issues {
		if issue.ProfileID == profileID {
			return discoveredLocalProfile{}, fmt.Errorf("profile %q was rejected: %s: %s", profileID, issue.Status, issue.Error)
		}
	}
	available := make([]string, 0)
	for id, profile := range registry.Profiles {
		if profile.Manifest.TargetRelativePath == target {
			available = append(available, id)
		}
	}
	sort.Strings(available)
	return discoveredLocalProfile{}, fmt.Errorf("unknown profile %q for %s; available: %s", profileID, target, strings.Join(available, ", "))
}

func verifyDiscoveredProfileAgain(projectRoot string, profile discoveredLocalProfile) error {
	refreshed, issue := loadLocalProfileManifest(projectRoot, filepath.Join(projectRoot, filepath.FromSlash(profile.ManifestPath)))
	if issue != nil {
		return fmt.Errorf("profile manifest or local file changed since discovery: %s: %s", issue.Status, issue.Error)
	}
	if refreshed.Manifest.ProfileID != profile.Manifest.ProfileID || refreshed.Manifest.TargetRelativePath != profile.Manifest.TargetRelativePath || refreshed.Manifest.ProfileSHA256 != profile.Manifest.ProfileSHA256 || refreshed.Manifest.ProfileSize != profile.Manifest.ProfileSize || refreshed.Manifest.BaselineSHA256 != profile.Manifest.BaselineSHA256 || refreshed.Manifest.BaselineSize != profile.Manifest.BaselineSize || refreshed.Manifest.LocalProfilePath != profile.Manifest.LocalProfilePath {
		return fmt.Errorf("profile manifest changed since discovery")
	}
	return nil
}

func rejectOtherTargetTransaction(projectRoot string, spec localProfileTargetSpec) error {
	otherSpec := localProfileTargetSpec{}
	for _, candidate := range localProfileTargets {
		if candidate.StatePath == spec.OtherState {
			otherSpec = candidate
			break
		}
	}
	if otherSpec.StatePath == "" {
		return nil
	}
	otherPath, err := secureJoin(projectRoot, otherSpec.StatePath)
	if err != nil {
		return err
	}
	state, exists, err := readLocalProfileState(otherPath, otherSpec)
	if err != nil {
		return fmt.Errorf("inspect other target transaction: %w", err)
	}
	if exists && isOpenProfileState(state.Status) {
		return fmt.Errorf("an isolated %s transaction is already open for %s (%s); rollback before activating a %s profile", otherSpec.Kind, state.ProfileID, state.Status, spec.Kind)
	}
	return nil
}

func readLocalProfileState(path string, spec localProfileTargetSpec) (localProfileState, bool, error) {
	var state localProfileState
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return state, false, nil
	}
	if err != nil {
		return state, false, err
	}
	if err := json.Unmarshal(data, &state); err != nil {
		return state, false, fmt.Errorf("parse %s transaction state: %w", spec.Kind, err)
	}
	validType := state.Type == localProfileStateType || (spec.Kind == "event" && state.Type == profileStateType) || (spec.Kind == "shader" && state.Type == shaderProfileStateType)
	if !validType || (state.FormatVersion != 1 && state.FormatVersion != 2) {
		return state, false, fmt.Errorf("unsupported %s transaction state", spec.Kind)
	}
	if state.TargetRelativePath == "" {
		state.TargetRelativePath = spec.RelativePath
	}
	if state.TargetRelativePath != spec.RelativePath {
		return state, false, fmt.Errorf("%s transaction state targets %s", spec.Kind, state.TargetRelativePath)
	}
	if state.BaselineSize == 0 {
		state.BaselineSize = state.ObservedBeforeSize
	}
	return state, true, nil
}

func verifyLocalStateBackup(projectRoot string, state localProfileState) error {
	path, err := secureJoin(projectRoot, state.BackupRelativePath)
	if err != nil {
		return err
	}
	hash, size, err := checkedFile(path)
	if err != nil {
		return fmt.Errorf("inspect transaction backup: %w", err)
	}
	if hash != state.BaselineSHA256 || size != effectiveBaselineSize(state) {
		return fmt.Errorf("transaction backup no longer matches the recorded baseline")
	}
	return nil
}

func effectiveBaselineSize(state localProfileState) int64 {
	if state.BaselineSize > 0 {
		return state.BaselineSize
	}
	return state.ObservedBeforeSize
}

func baselineForTarget(registry localProfileRegistry, target string) (string, int64, bool) {
	hash := ""
	var size int64
	found := false
	for _, profile := range registry.Profiles {
		if profile.Manifest.TargetRelativePath != target {
			continue
		}
		if !found {
			hash = profile.Manifest.BaselineSHA256
			size = profile.Manifest.BaselineSize
			found = true
			continue
		}
		if hash != profile.Manifest.BaselineSHA256 || size != profile.Manifest.BaselineSize {
			return "", 0, false
		}
	}
	return hash, size, found
}

func writeLocalProfileReport(projectRoot string, spec localProfileTargetSpec, report localProfileTransactionReport) error {
	latest, err := secureJoin(projectRoot, spec.ReportLatest)
	if err != nil {
		return err
	}
	if err := writeJSONAtomic(latest, report, 0o600); err != nil {
		return err
	}
	stamp := strings.NewReplacer(":", "", "-", "").Replace(report.GeneratedUTC)
	historyRel := filepath.ToSlash(filepath.Join(spec.ReportDir, stamp+"_"+report.Operation+".json"))
	history, err := secureJoin(projectRoot, historyRel)
	if err != nil {
		return err
	}
	return writeJSONAtomic(history, report, 0o600)
}

func localProfileNextAction(spec localProfileTargetSpec, profileID string) string {
	return fmt.Sprintf("run only the matching isolated %s runtime scene test for %s, exit the game, then rollback", spec.Kind, profileID)
}
