package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
	"local/blue-reflection-patcher/internal/targets"
)

const (
	quartetCompositionBuildType       = "br_quartet_translation_restoration_composition_build"
	quartetCompositionBuildVersion    = 4
	quartetCompositionOutputRelative  = ".local/build/composition/blue_reflection_quartet"
	quartetCompositionReportRelative  = ".local/reports/core/BR_QUARTET_COMPOSITION_BUILD_REPORT.json"
	quartetCompositionEmbeddedReport  = "BR_QUARTET_COMPOSITION_BUILD_REPORT.json"
	quartetCompositionLockRelative    = ".local/locks/core_quartet_composition.lock"
	quartetCompositionDefaultTimeout  = 45 * time.Minute
	quartetCompositionToolOutputLimit = 256 * 1024
)

type compositionBuildMember struct {
	InternalPath       string   `json:"internal_path"`
	SHA256             string   `json:"sha256"`
	Bytes              int64    `json:"bytes"`
	SourceProfileIDs   []string `json:"source_profile_ids"`
	SourceModuleIDs    []string `json:"source_module_ids,omitempty"`
	TranslationChanged bool     `json:"translation_changed"`
}

type compositionOverlaySource struct {
	Member     compositionBuildMember
	SourcePath string
}

type compositionBuildProfileInput struct {
	ProfileID          string `json:"profile_id"`
	ManifestPath       string `json:"manifest_path"`
	ManifestSHA256     string `json:"manifest_sha256"`
	ManifestBytes      int64  `json:"manifest_bytes"`
	PayloadPath        string `json:"payload_path"`
	PayloadSHA256      string `json:"payload_sha256"`
	PayloadBytes       int64  `json:"payload_bytes"`
	TargetRelativePath string `json:"target_relative_path"`
	BaselineSHA256     string `json:"baseline_sha256"`
	BaselineBytes      int64  `json:"baseline_bytes"`
	RuntimeValidated   bool   `json:"runtime_validated"`
}

type compositionBuildArchive struct {
	ArchiveRelativePath        string                   `json:"archive_relative_path"`
	Mode                       string                   `json:"mode"`
	BaseSourceKind             string                   `json:"base_source_kind"`
	BaseSourcePath             string                   `json:"base_source_path"`
	BaseSHA256                 string                   `json:"base_sha256"`
	BaseBytes                  int64                    `json:"base_bytes"`
	InstalledBaselinePath      string                   `json:"installed_baseline_path,omitempty"`
	InstalledBaselineSHA256    string                   `json:"installed_baseline_sha256,omitempty"`
	InstalledBaselineBytes     int64                    `json:"installed_baseline_bytes,omitempty"`
	ProfileIDs                 []string                 `json:"profile_ids"`
	TranslationChangedMembers  []string                 `json:"translation_changed_members"`
	OverlayMembers             []compositionBuildMember `json:"overlay_members"`
	ListedEntryCount           int                      `json:"listed_entry_count"`
	ReextractedEntryCount      int                      `json:"reextracted_entry_count"`
	UnchangedMemberCount       int                      `json:"unchanged_member_count"`
	OutputPath                 string                   `json:"output_path"`
	OutputSHA256               string                   `json:"output_sha256"`
	OutputBytes                int64                    `json:"output_bytes"`
	FullReextractVerified      bool                     `json:"full_reextract_verified"`
	ManifestDeclarationChecked bool                     `json:"manifest_declaration_checked"`
	Status                     string                   `json:"status"`
	Warnings                   []string                 `json:"warnings"`
}

type compositionBuildLegacyDLCInput struct {
	ManifestPath           string   `json:"manifest_path"`
	ManifestSHA256         string   `json:"manifest_sha256"`
	ManifestBytes          int64    `json:"manifest_bytes"`
	FamilyID               string   `json:"family_id"`
	Generation             int      `json:"generation"`
	Members                []string `json:"members"`
	TransactionGroup       string   `json:"transaction_group"`
	WorkstreamVersion      string   `json:"workstream_version"`
	ProvenanceEvidencePath string   `json:"provenance_evidence_path"`
	ProvenanceEvidenceHash string   `json:"provenance_evidence_sha256"`
	ArchiveRelativePath    string   `json:"archive_relative_path"`
	CandidatePath          string   `json:"candidate_path"`
	CandidateSHA256        string   `json:"candidate_sha256"`
	CandidateBytes         int64    `json:"candidate_bytes"`
	BaselinePath           string   `json:"baseline_path"`
	BaselineSHA256         string   `json:"baseline_sha256"`
	BaselineBytes          int64    `json:"baseline_bytes"`
	AddedMembers           []string `json:"added_members"`
	ChangedMembers         []string `json:"changed_members"`
	RemovedMembers         []string `json:"removed_members"`
}

type quartetCompositionBuildReport struct {
	Type                          string                           `json:"type"`
	FormatVersion                 int                              `json:"format_version"`
	Status                        string                           `json:"status"`
	GeneratedUTC                  time.Time                        `json:"generated_utc"`
	ProjectRoot                   string                           `json:"project_root"`
	GameRoot                      string                           `json:"game_root"`
	TargetID                      string                           `json:"target_id"`
	CommitEnabled                 bool                             `json:"commit_enabled"`
	PreflightStatus               string                           `json:"preflight_status"`
	CompositionPolicy             string                           `json:"composition_policy"`
	SelectedModules               []string                         `json:"selected_modules"`
	GustPakPath                   string                           `json:"gust_pak_path"`
	GustPakSHA256                 string                           `json:"gust_pak_sha256"`
	GustPakBytes                  int64                            `json:"gust_pak_bytes"`
	OutputRoot                    string                           `json:"output_root"`
	EmbeddedReportPath            string                           `json:"embedded_report_path"`
	TranslationLooseReportPath    string                           `json:"translation_loose_report_path"`
	TranslationLooseReportSHA256  string                           `json:"translation_loose_report_sha256"`
	TranslationLooseReportBytes   int64                            `json:"translation_loose_report_bytes"`
	TranslationRepackReportPath   string                           `json:"translation_repack_report_path"`
	TranslationRepackReportSHA256 string                           `json:"translation_repack_report_sha256"`
	TranslationRepackReportBytes  int64                            `json:"translation_repack_report_bytes"`
	ProductionProfileIDs          []string                         `json:"production_profile_ids"`
	RuntimeTestProfileIDs         []string                         `json:"runtime_test_profile_ids"`
	SelectedProfileIDs            []string                         `json:"selected_profile_ids"`
	RestorationProfilePolicy      string                           `json:"restoration_profile_policy"`
	RuntimeTestOnly               bool                             `json:"runtime_test_only"`
	ProfileInputs                 []compositionBuildProfileInput   `json:"profile_inputs"`
	LegacyDLCInputs               []compositionBuildLegacyDLCInput `json:"legacy_dlc_inputs"`
	Archives                      []compositionBuildArchive        `json:"archives"`
	PublishedArchiveCount         int                              `json:"published_archive_count"`
	ComposedArchiveCount          int                              `json:"composed_archive_count"`
	PassthroughArchiveCount       int                              `json:"passthrough_archive_count"`
	FullReextractCount            int                              `json:"full_reextract_count"`
	Errors                        []string                         `json:"errors"`
	Warnings                      []string                         `json:"warnings"`
	CompositionLockReclaimed      bool                             `json:"composition_lock_reclaimed"`
	CompositionLockReclaimReason  string                           `json:"composition_lock_reclaim_reason,omitempty"`
	CompositionLockPreviousOwner  string                           `json:"composition_lock_previous_owner,omitempty"`
}

type compositionArchiveTool interface {
	Identity() (string, string, int64, error)
	List(archive string, timeout time.Duration) ([]string, []string, error)
	Extract(archive, destination string, timeout time.Duration) (compositionExtractedArchive, error)
	Repack(manifestPath, workingDirectory string, timeout time.Duration) (string, []string, error)
}

type compositionExtractedArchive struct {
	Root         string
	ManifestPath string
	Entries      []string
	LogTail      []string
}

type gustPakArchiveTool struct {
	Path string
}

type tailCapture struct {
	limit int
	data  []byte
}

func (capture *tailCapture) Write(data []byte) (int, error) {
	capture.data = append(capture.data, data...)
	if len(capture.data) > capture.limit {
		capture.data = append([]byte{}, capture.data[len(capture.data)-capture.limit:]...)
	}
	return len(data), nil
}

func (capture *tailCapture) Lines() []string {
	text := strings.TrimSpace(string(capture.data))
	if text == "" {
		return []string{}
	}
	return strings.Split(text, "\n")
}

func (tool gustPakArchiveTool) Identity() (string, string, int64, error) {
	hash, size, err := checkedFile(tool.Path)
	return tool.Path, hash, size, err
}

func (tool gustPakArchiveTool) List(archive string, timeout time.Duration) ([]string, []string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	command := exec.CommandContext(ctx, tool.Path, "-l", archive)
	command.Stdin = nil
	var stdout bytes.Buffer
	stderr := &tailCapture{limit: quartetCompositionToolOutputLimit}
	command.Stdout = &stdout
	command.Stderr = stderr
	if err := command.Run(); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, stderr.Lines(), fmt.Errorf("gust_pak list timed out after %s: %s", timeout, archive)
		}
		return nil, stderr.Lines(), fmt.Errorf("gust_pak list failed for %s: %w: %s", archive, err, strings.Join(stderr.Lines(), "\n"))
	}
	entries, err := parseGustPakListing(stdout.String())
	if err != nil {
		return nil, append(lastLines(stdout.String(), 20), stderr.Lines()...), err
	}
	return entries, append(lastLines(stdout.String(), 20), stderr.Lines()...), nil
}

func (tool gustPakArchiveTool) Extract(archive, destination string, timeout time.Duration) (compositionExtractedArchive, error) {
	if err := os.MkdirAll(destination, 0o700); err != nil {
		return compositionExtractedArchive{}, err
	}
	entries, listingTail, err := tool.List(archive, timeout)
	if err != nil {
		return compositionExtractedArchive{}, err
	}
	inputName := filepath.Base(archive)
	localArchive := filepath.Join(destination, inputName)
	hash, size, err := checkedFile(archive)
	if err != nil {
		return compositionExtractedArchive{}, err
	}
	if err := copyFileDurable(archive, localArchive, hash, size, 0o600); err != nil {
		return compositionExtractedArchive{}, fmt.Errorf("stage archive for extraction: %w", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	command := exec.CommandContext(ctx, tool.Path, inputName)
	command.Dir = destination
	command.Stdin = nil
	capture := &tailCapture{limit: quartetCompositionToolOutputLimit}
	command.Stdout = capture
	command.Stderr = capture
	if err := command.Run(); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return compositionExtractedArchive{}, fmt.Errorf("gust_pak extract timed out after %s: %s", timeout, archive)
		}
		return compositionExtractedArchive{}, fmt.Errorf("gust_pak extract failed for %s: %w: %s", archive, err, strings.Join(capture.Lines(), "\n"))
	}
	if err := os.Remove(localArchive); err != nil {
		return compositionExtractedArchive{}, fmt.Errorf("remove staged input archive: %w", err)
	}
	manifest, err := findExtractionManifest(destination, inputName)
	if err != nil {
		return compositionExtractedArchive{}, err
	}
	if _, err := hashCompositionMembers(destination, entries); err != nil {
		return compositionExtractedArchive{}, fmt.Errorf("validate extracted archive members: %w", err)
	}
	return compositionExtractedArchive{
		Root: destination, ManifestPath: manifest, Entries: entries,
		LogTail: append(listingTail, capture.Lines()...),
	}, nil
}

func (tool gustPakArchiveTool) Repack(manifestPath, workingDirectory string, timeout time.Duration) (string, []string, error) {
	before, err := rootPakFiles(workingDirectory)
	if err != nil {
		return "", nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	command := exec.CommandContext(ctx, tool.Path, filepath.Base(manifestPath))
	command.Dir = workingDirectory
	command.Stdin = nil
	capture := &tailCapture{limit: quartetCompositionToolOutputLimit}
	command.Stdout = capture
	command.Stderr = capture
	if err := command.Run(); err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return "", capture.Lines(), fmt.Errorf("gust_pak repack timed out after %s: %s", timeout, manifestPath)
		}
		return "", capture.Lines(), fmt.Errorf("gust_pak repack failed for %s: %w: %s", manifestPath, err, strings.Join(capture.Lines(), "\n"))
	}
	after, err := rootPakFiles(workingDirectory)
	if err != nil {
		return "", capture.Lines(), err
	}
	var created []string
	for path := range after {
		if !before[path] {
			created = append(created, path)
		}
	}
	sort.Strings(created)
	if len(created) != 1 {
		return "", capture.Lines(), fmt.Errorf("gust_pak created %d PAK files, expected exactly one: %s", len(created), strings.Join(created, ", "))
	}
	return created[0], capture.Lines(), nil
}

func commandQuartetCompositionBuild(args []string) error {
	flags := flag.NewFlagSet("quartet-composition-build", flag.ContinueOnError)
	var roots rootsFlag
	var projectRoot, gustPak, output, moduleList, profilePolicy string
	var timeout time.Duration
	flags.Var(&roots, "game-dir", "BLUE REFLECTION Quartet game directory")
	flags.Var(&roots, "root", "alias for --game-dir")
	flags.StringVar(&projectRoot, "project-root", "", "project root containing verified translation and restoration builds")
	flags.StringVar(&gustPak, "gust-pak", "", "path to gust_pak/gust_pak.exe; optional when configured locally")
	flags.StringVar(&output, "json", "", "also write the composition build report to this file")
	flags.StringVar(&moduleList, "modules", "blue_reflection_translation,quartet_restoration", "comma-separated Quartet modules to compose")
	flags.StringVar(&profilePolicy, "restoration-profile-policy", restorationProfilePolicyRuntimeValidated, "Restoration profile policy: runtime-validated or all-current-candidates-for-runtime-test")
	flags.DurationVar(&timeout, "timeout", quartetCompositionDefaultTimeout, "timeout for each gust_pak operation")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if timeout <= 0 {
		return fmt.Errorf("--timeout must be positive")
	}
	specs, err := targets.Load()
	if err != nil {
		return err
	}
	items, err := detectWithFallback(specs, roots, false, os.Stdin, os.Stdout)
	if err != nil {
		return err
	}
	var quartet []model.Detection
	for _, item := range items {
		if item.TargetID == quartetTargetID {
			quartet = append(quartet, item)
		}
	}
	if len(quartet) != 1 {
		return fmt.Errorf("expected exactly one detected BLUE REFLECTION Quartet installation, found %d", len(quartet))
	}
	resolvedProject, err := payloadpreview.ResolveProjectRoot(projectRoot)
	if err != nil {
		return err
	}
	resolvedProject, err = filepath.Abs(resolvedProject)
	if err != nil {
		return err
	}
	resolvedTool, err := resolveGustPakPath(resolvedProject, gustPak)
	if err != nil {
		return err
	}
	modules, err := normalizeQuartetCompositionModules([]string{moduleList})
	if err != nil {
		return err
	}
	policy, err := normalizeRestorationProfilePolicy(profilePolicy)
	if err != nil {
		return err
	}
	if err := validateRestorationProfilePolicyForModules(policy, modules); err != nil {
		return err
	}
	report, buildErr := buildQuartetModuleCompositionWithPolicy(resolvedProject, quartet[0].Root, modules, policy, gustPakArchiveTool{Path: resolvedTool}, timeout)
	defaultReport := filepath.Join(resolvedProject, filepath.FromSlash(quartetCompositionReportRelative))
	if writeErr := writeJSONAtomic(defaultReport, report, 0o600); writeErr != nil {
		if buildErr != nil {
			return fmt.Errorf("%v; additionally failed to write build report: %w", buildErr, writeErr)
		}
		return fmt.Errorf("write composition build report: %w", writeErr)
	}
	if output != "" {
		absoluteOutput, err := filepath.Abs(output)
		if err != nil {
			return err
		}
		if filepath.Clean(absoluteOutput) != filepath.Clean(defaultReport) {
			if err := writeJSONAtomic(absoluteOutput, report, 0o600); err != nil {
				return fmt.Errorf("write requested composition build report: %w", err)
			}
		}
	}
	printHumanQuartetCompositionBuild(os.Stdout, report)
	fmt.Printf("Composition build report: %s\n", defaultReport)
	if buildErr != nil {
		return buildErr
	}
	return nil
}

func buildQuartetComposition(projectRoot, gameRoot string, tool compositionArchiveTool, timeout time.Duration) (quartetCompositionBuildReport, error) {
	report := quartetCompositionBuildReport{
		Type: quartetCompositionBuildType, FormatVersion: quartetCompositionBuildVersion,
		Status: "failed", GeneratedUTC: time.Now().UTC(), TargetID: quartetTargetID,
		CommitEnabled:               false,
		CompositionPolicy:           "verify installed restoration baselines, prove translation archives differ only at declared translation members, prove each profile differs only at manifest-declared members, overlay by member, fully re-extract composed archives, publish locally without touching the game installation",
		SelectedModules:             []string{quartetTranslationModule, quartetRestorationModule},
		OutputRoot:                  filepath.ToSlash(quartetCompositionOutputRelative),
		EmbeddedReportPath:          filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, quartetCompositionEmbeddedReport)),
		TranslationLooseReportPath:  filepath.ToSlash(translationLooseReportRelative),
		TranslationRepackReportPath: filepath.ToSlash(translationRepackReportRelative),
		ProductionProfileIDs:        []string{}, RuntimeTestProfileIDs: []string{}, SelectedProfileIDs: []string{}, ProfileInputs: []compositionBuildProfileInput{}, LegacyDLCInputs: []compositionBuildLegacyDLCInput{}, Archives: []compositionBuildArchive{}, Errors: []string{}, Warnings: []string{},
		RestorationProfilePolicy: restorationProfilePolicyRuntimeValidated, RuntimeTestOnly: false,
	}
	projectRoot, err := filepath.Abs(projectRoot)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	gameRoot, err = filepath.Abs(gameRoot)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	report.ProjectRoot, report.GameRoot = projectRoot, gameRoot
	looseReportPath, err := secureJoin(projectRoot, translationLooseReportRelative)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	report.TranslationLooseReportSHA256, report.TranslationLooseReportBytes, err = checkedFile(looseReportPath)
	if err != nil {
		report.Errors = append(report.Errors, fmt.Sprintf("fingerprint translation loose report: %v", err))
		return report, err
	}
	repackReportPath, err := secureJoin(projectRoot, translationRepackReportRelative)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	report.TranslationRepackReportSHA256, report.TranslationRepackReportBytes, err = checkedFile(repackReportPath)
	if err != nil {
		report.Errors = append(report.Errors, fmt.Sprintf("fingerprint translation repack report: %v", err))
		return report, err
	}
	toolPath, toolHash, toolSize, err := tool.Identity()
	if err != nil {
		report.Errors = append(report.Errors, fmt.Sprintf("validate archive tool: %v", err))
		return report, fmt.Errorf("validate archive tool: %w", err)
	}
	report.GustPakPath, report.GustPakSHA256, report.GustPakBytes = toolPath, toolHash, toolSize

	preflight, err := buildQuartetCompositionPreview(projectRoot, gameRoot)
	if err != nil {
		report.Errors = append(report.Errors, fmt.Sprintf("composition preflight: %v", err))
		return report, fmt.Errorf("composition preflight: %w", err)
	}
	report.PreflightStatus = preflight.Status
	if preflight.Status != "ready_for_composition_build" {
		err := fmt.Errorf("composition preflight status is %s, expected ready_for_composition_build", preflight.Status)
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}

	registry, err := discoverLocalProfiles(projectRoot)
	if err != nil {
		report.Errors = append(report.Errors, fmt.Sprintf("discover restoration profiles: %v", err))
		return report, err
	}
	eligibleProfiles := map[string]discoveredLocalProfile{}
	for _, profile := range preflight.Profiles {
		if !profile.ProductionEligible {
			continue
		}
		item, ok := registry.Profiles[profile.ProfileID]
		if !ok {
			err := fmt.Errorf("preflight-selected profile disappeared from registry: %s", profile.ProfileID)
			report.Errors = append(report.Errors, err.Error())
			return report, err
		}
		eligibleProfiles[profile.ProfileID] = item
		report.ProductionProfileIDs = append(report.ProductionProfileIDs, profile.ProfileID)
		report.SelectedProfileIDs = append(report.SelectedProfileIDs, profile.ProfileID)
		manifestAbsolute, pathErr := secureJoin(projectRoot, item.ManifestPath)
		if pathErr != nil {
			err := fmt.Errorf("resolve profile manifest %s: %w", profile.ProfileID, pathErr)
			report.Errors = append(report.Errors, err.Error())
			return report, err
		}
		manifestHash, manifestBytes, hashErr := checkedFile(manifestAbsolute)
		if hashErr != nil {
			err := fmt.Errorf("fingerprint profile manifest %s: %w", profile.ProfileID, hashErr)
			report.Errors = append(report.Errors, err.Error())
			return report, err
		}
		payloadHash, payloadBytes, hashErr := checkedFile(item.SourcePath)
		if hashErr != nil {
			err := fmt.Errorf("fingerprint profile payload %s: %w", profile.ProfileID, hashErr)
			report.Errors = append(report.Errors, err.Error())
			return report, err
		}
		report.ProfileInputs = append(report.ProfileInputs, compositionBuildProfileInput{
			ProfileID:    profile.ProfileID,
			ManifestPath: filepath.ToSlash(item.ManifestPath), ManifestSHA256: manifestHash, ManifestBytes: manifestBytes,
			PayloadPath: relativeDisplayPath(projectRoot, item.SourcePath), PayloadSHA256: payloadHash, PayloadBytes: payloadBytes,
			TargetRelativePath: item.Manifest.TargetRelativePath,
			BaselineSHA256:     item.Manifest.BaselineSHA256, BaselineBytes: item.Manifest.BaselineSize,
			RuntimeValidated: item.Manifest.RuntimeValidated,
		})
	}
	sort.Strings(report.ProductionProfileIDs)
	sort.Strings(report.SelectedProfileIDs)
	sort.Slice(report.ProfileInputs, func(i, j int) bool { return report.ProfileInputs[i].ProfileID < report.ProfileInputs[j].ProfileID })
	if len(eligibleProfiles) == 0 {
		err := fmt.Errorf("composition preflight selected no production-eligible restoration profiles")
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}

	lock, err := acquireCompositionBuildLock(projectRoot)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	report.CompositionLockReclaimed = lock.Reclaimed
	report.CompositionLockReclaimReason = lock.ReclaimReason
	report.CompositionLockPreviousOwner = lock.PreviousOwner
	defer releaseCompositionBuildLock(lock)

	outputRoot, err := secureJoin(projectRoot, quartetCompositionOutputRelative)
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	outputParent := filepath.Dir(outputRoot)
	if err := os.MkdirAll(outputParent, 0o700); err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	stagingRoot, err := os.MkdirTemp(outputParent, ".blue_reflection_quartet-compose-*")
	if err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	published := false
	defer func() {
		if !published {
			_ = os.RemoveAll(stagingRoot)
		}
	}()

	translationByArchive := map[string]compositionTranslationBase{}
	for _, base := range preflight.TranslationBases {
		if base.Verified {
			translationByArchive[foldCompositionPath(base.ArchiveRelativePath)] = base
		}
	}
	profilesByArchive := map[string][]discoveredLocalProfile{}
	canonicalArchivePath := map[string]string{}
	for _, id := range report.ProductionProfileIDs {
		profile := eligibleProfiles[id]
		key := foldCompositionPath(profile.Manifest.TargetRelativePath)
		profilesByArchive[key] = append(profilesByArchive[key], profile)
		canonicalArchivePath[key] = profile.Manifest.TargetRelativePath
	}
	for key := range profilesByArchive {
		sort.Slice(profilesByArchive[key], func(i, j int) bool {
			return profilesByArchive[key][i].Manifest.ProfileID < profilesByArchive[key][j].Manifest.ProfileID
		})
	}

	archiveKeys := make([]string, 0, len(translationByArchive)+len(profilesByArchive))
	seen := map[string]bool{}
	for key, base := range translationByArchive {
		seen[key] = true
		archiveKeys = append(archiveKeys, key)
		canonicalArchivePath[key] = base.ArchiveRelativePath
	}
	for key := range profilesByArchive {
		if !seen[key] {
			archiveKeys = append(archiveKeys, key)
		}
	}
	sort.Slice(archiveKeys, func(i, j int) bool {
		return canonicalArchivePath[archiveKeys[i]] < canonicalArchivePath[archiveKeys[j]]
	})

	workRoot := filepath.Join(stagingRoot, ".work")
	if err := os.MkdirAll(workRoot, 0o700); err != nil {
		report.Errors = append(report.Errors, err.Error())
		return report, err
	}
	for _, key := range archiveKeys {
		relative := canonicalArchivePath[key]
		translationBase, hasTranslation := translationByArchive[key]
		profiles := profilesByArchive[key]
		var archive compositionBuildArchive
		if len(profiles) == 0 {
			archive, err = publishTranslationPassthrough(projectRoot, stagingRoot, translationBase)
		} else {
			archive, err = composeQuartetArchive(projectRoot, gameRoot, stagingRoot, workRoot, relative, translationBase, hasTranslation, profiles, tool, timeout)
		}
		if err != nil {
			report.Archives = append(report.Archives, archive)
			report.Errors = append(report.Errors, fmt.Sprintf("%s: %v", relative, err))
			return report, fmt.Errorf("compose %s: %w", relative, err)
		}
		report.Archives = append(report.Archives, archive)
		report.PublishedArchiveCount++
		if archive.Mode == "member_overlay" {
			report.ComposedArchiveCount++
			if archive.FullReextractVerified {
				report.FullReextractCount++
			}
		} else {
			report.PassthroughArchiveCount++
		}
	}
	if err := os.RemoveAll(workRoot); err != nil {
		report.Warnings = append(report.Warnings, fmt.Sprintf("remove composition work directory: %v", err))
	}

	report.Status = "ok"
	embedded := filepath.Join(stagingRoot, quartetCompositionEmbeddedReport)
	if err := writeJSONAtomic(embedded, report, 0o600); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("write embedded report: %v", err))
		return report, err
	}
	if err := publishCompositionDirectory(stagingRoot, outputRoot); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("publish composition payloads: %v", err))
		return report, err
	}
	published = true
	return report, nil
}

func publishTranslationPassthrough(projectRoot, stagingRoot string, base compositionTranslationBase) (compositionBuildArchive, error) {
	archive := compositionBuildArchive{
		ArchiveRelativePath: base.ArchiveRelativePath, Mode: "verified_translation_passthrough",
		BaseSourceKind: "verified_translation_archive", BaseSourcePath: base.SourcePath,
		BaseSHA256: base.SHA256, BaseBytes: base.Bytes,
		ProfileIDs: []string{}, TranslationChangedMembers: append([]string{}, base.ChangedMembers...),
		OverlayMembers: []compositionBuildMember{}, Status: "failed", Warnings: []string{},
	}
	source, err := resolveCompositionProjectPath(projectRoot, base.SourcePath)
	if err != nil {
		return archive, err
	}
	destination, err := secureJoin(stagingRoot, base.ArchiveRelativePath)
	if err != nil {
		return archive, err
	}
	method, err := cloneOrCopyCompositionFile(source, destination, base.SHA256, base.Bytes, 0o600)
	if err != nil {
		return archive, err
	}
	archive.Warnings = append(archive.Warnings, "storage_method="+method)
	hash, size, err := checkedFile(destination)
	if err != nil {
		return archive, err
	}
	archive.OutputPath = filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, filepath.FromSlash(base.ArchiveRelativePath)))
	archive.OutputSHA256, archive.OutputBytes = hash, size
	archive.Status = "published_verified_translation_passthrough"
	archive.ManifestDeclarationChecked = true
	return archive, nil
}

func composeQuartetArchive(projectRoot, gameRoot, stagingRoot, workRoot, archiveRelative string, translationBase compositionTranslationBase, hasTranslation bool, profiles []discoveredLocalProfile, tool compositionArchiveTool, timeout time.Duration) (compositionBuildArchive, error) {
	archive := compositionBuildArchive{
		ArchiveRelativePath: archiveRelative, Mode: "member_overlay",
		ProfileIDs: []string{}, TranslationChangedMembers: []string{}, OverlayMembers: []compositionBuildMember{},
		Status: "failed", Warnings: []string{},
	}
	for _, profile := range profiles {
		archive.ProfileIDs = append(archive.ProfileIDs, profile.Manifest.ProfileID)
	}
	sort.Strings(archive.ProfileIDs)
	baselineHash := profiles[0].Manifest.BaselineSHA256
	baselineSize := profiles[0].Manifest.BaselineSize
	for _, profile := range profiles[1:] {
		if profile.Manifest.BaselineSHA256 != baselineHash || profile.Manifest.BaselineSize != baselineSize {
			return archive, fmt.Errorf("eligible profiles do not share one installed baseline")
		}
	}
	installedPath, _, err := resolveCaseInsensitiveCompositionPath(gameRoot, archiveRelative)
	if err != nil {
		return archive, err
	}
	installedHash, installedSize, err := checkedFile(installedPath)
	if err != nil {
		return archive, err
	}
	archive.InstalledBaselinePath = installedPath
	archive.InstalledBaselineSHA256, archive.InstalledBaselineBytes = installedHash, installedSize
	if installedHash != baselineHash || installedSize != baselineSize {
		return archive, fmt.Errorf("installed baseline mismatch: got %s (%d bytes), expected %s (%d bytes)", installedHash, installedSize, baselineHash, baselineSize)
	}

	archiveWork := filepath.Join(workRoot, safeWorkName(archiveRelative))
	baselineExtract, err := tool.Extract(installedPath, filepath.Join(archiveWork, "baseline"), timeout)
	if err != nil {
		return archive, fmt.Errorf("extract installed baseline: %w", err)
	}
	baselineMembers, err := hashCompositionMembers(baselineExtract.Root, baselineExtract.Entries)
	if err != nil {
		return archive, err
	}

	baseExtract := baselineExtract
	if hasTranslation {
		translationPath, err := resolveCompositionProjectPath(projectRoot, translationBase.SourcePath)
		if err != nil {
			return archive, err
		}
		archive.BaseSourceKind = "verified_translation_archive"
		archive.BaseSourcePath = translationBase.SourcePath
		archive.BaseSHA256, archive.BaseBytes = translationBase.SHA256, translationBase.Bytes
		archive.TranslationChangedMembers = append([]string{}, translationBase.ChangedMembers...)
		baseExtract, err = tool.Extract(translationPath, filepath.Join(archiveWork, "base"), timeout)
		if err != nil {
			return archive, fmt.Errorf("extract verified translation base: %w", err)
		}
		if err := requireSameEntrySet(baselineExtract.Entries, baseExtract.Entries); err != nil {
			return archive, fmt.Errorf("translation archive member set differs from installed baseline: %w", err)
		}
		baseMembers, err := hashCompositionMembers(baseExtract.Root, baseExtract.Entries)
		if err != nil {
			return archive, err
		}
		actualTranslationChanges := memberDifferences(baselineMembers, baseMembers)
		declaredTranslationChanges, err := foldedMemberSet(translationBase.ChangedMembers)
		if err != nil {
			return archive, fmt.Errorf("invalid translation changed-member declaration: %w", err)
		}
		if extras := setDifference(actualTranslationChanges, declaredTranslationChanges); len(extras) > 0 {
			return archive, fmt.Errorf("translation PAK changes undeclared member(s): %s", strings.Join(extras, ", "))
		}
	} else {
		archive.BaseSourceKind = "installed_game_baseline"
		archive.BaseSourcePath = installedPath
		archive.BaseSHA256, archive.BaseBytes = installedHash, installedSize
	}

	stageRoot := filepath.Join(archiveWork, "stage")
	if err := cloneCompositionExtraction(baseExtract.Root, stageRoot); err != nil {
		return archive, fmt.Errorf("clone composition base: %w", err)
	}
	manifestRelative, err := filepath.Rel(baseExtract.Root, baseExtract.ManifestPath)
	if err != nil || manifestRelative == ".." || strings.HasPrefix(manifestRelative, ".."+string(filepath.Separator)) {
		return archive, fmt.Errorf("resolve cloned reconstruction manifest: %w", err)
	}
	stageManifest := filepath.Join(stageRoot, manifestRelative)
	if info, err := os.Lstat(stageManifest); err != nil || info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		if err != nil {
			return archive, fmt.Errorf("cloned reconstruction manifest is missing: %w", err)
		}
		return archive, fmt.Errorf("cloned reconstruction manifest is not a regular non-symlink file: %s", stageManifest)
	}
	baseMembers, err := hashCompositionMembers(baseExtract.Root, baseExtract.Entries)
	if err != nil {
		return archive, err
	}

	overlays := map[string]compositionOverlaySource{}
	for _, profile := range profiles {
		profileExtract, err := tool.Extract(profile.SourcePath, filepath.Join(archiveWork, "profile-"+safeWorkName(profile.Manifest.ProfileID)), timeout)
		if err != nil {
			return archive, fmt.Errorf("extract profile %s: %w", profile.Manifest.ProfileID, err)
		}
		if err := requireSameEntrySet(baselineExtract.Entries, profileExtract.Entries); err != nil {
			return archive, fmt.Errorf("profile %s member set differs from declared baseline: %w", profile.Manifest.ProfileID, err)
		}
		profileMembers, err := hashCompositionMembers(profileExtract.Root, profileExtract.Entries)
		if err != nil {
			return archive, err
		}
		actualProfileChanges := memberDifferences(baselineMembers, profileMembers)
		declaredProfileChanges, err := foldedMemberSet(profile.Manifest.ChangedMembers)
		if err != nil {
			return archive, fmt.Errorf("profile %s has invalid changed_members: %w", profile.Manifest.ProfileID, err)
		}
		if !sameStringSet(actualProfileChanges, declaredProfileChanges) {
			return archive, fmt.Errorf("profile %s manifest declaration mismatch: actual changed members=%s declared=%s", profile.Manifest.ProfileID, strings.Join(sortedSet(actualProfileChanges), ", "), strings.Join(sortedSet(declaredProfileChanges), ", "))
		}
		for _, rawMember := range profile.Manifest.ChangedMembers {
			member, err := normalizeCompositionMember(rawMember)
			if err != nil {
				return archive, err
			}
			key := foldCompositionPath(member)
			fingerprint, ok := profileMembers[key]
			if !ok {
				return archive, fmt.Errorf("profile %s declared member is absent after extraction: %s", profile.Manifest.ProfileID, member)
			}
			sourcePath, err := secureCompositionMemberPath(profileExtract.Root, fingerprint.Path)
			if err != nil {
				return archive, err
			}
			candidate := compositionOverlaySource{
				Member: compositionBuildMember{
					InternalPath: fingerprint.Path, SHA256: fingerprint.SHA256, Bytes: fingerprint.Bytes,
					SourceProfileIDs: []string{profile.Manifest.ProfileID},
				},
				SourcePath: sourcePath,
			}
			if err := mergeCompositionOverlay(overlays, key, candidate); err != nil {
				return archive, err
			}
		}
	}

	overlayKeys := make([]string, 0, len(overlays))
	for key := range overlays {
		overlayKeys = append(overlayKeys, key)
	}
	sort.Strings(overlayKeys)
	for _, key := range overlayKeys {
		overlay := overlays[key]
		destination, err := secureCompositionMemberPath(stageRoot, overlay.Member.InternalPath)
		if err != nil {
			return archive, err
		}
		if err := replaceCompositionMember(overlay.SourcePath, destination, overlay.Member.SHA256, overlay.Member.Bytes); err != nil {
			return archive, fmt.Errorf("overlay member %s: %w", overlay.Member.InternalPath, err)
		}
		archive.OverlayMembers = append(archive.OverlayMembers, overlay.Member)
	}
	stageMembers, err := hashCompositionMembers(stageRoot, baseExtract.Entries)
	if err != nil {
		return archive, err
	}
	actualStageChanges := memberDifferences(baseMembers, stageMembers)
	expectedStageChanges := map[string]bool{}
	for _, key := range overlayKeys {
		expectedStageChanges[key] = true
	}
	if !sameStringSet(actualStageChanges, expectedStageChanges) {
		return archive, fmt.Errorf("staged composition changed unexpected members: actual=%s expected=%s", strings.Join(sortedSet(actualStageChanges), ", "), strings.Join(sortedSet(expectedStageChanges), ", "))
	}
	archive.ManifestDeclarationChecked = true
	archive.UnchangedMemberCount = len(baseExtract.Entries) - len(overlayKeys)

	builtPak, _, err := tool.Repack(stageManifest, stageRoot, timeout)
	if err != nil {
		return archive, err
	}
	outputEntries, _, err := tool.List(builtPak, timeout)
	if err != nil {
		return archive, err
	}
	if err := requireSameEntrySet(baseExtract.Entries, outputEntries); err != nil {
		return archive, fmt.Errorf("rebuilt archive member set mismatch: %w", err)
	}
	verifyExtract, err := tool.Extract(builtPak, filepath.Join(archiveWork, "verify"), timeout)
	if err != nil {
		return archive, fmt.Errorf("full re-extract verification: %w", err)
	}
	verifiedMembers, err := hashCompositionMembers(verifyExtract.Root, verifyExtract.Entries)
	if err != nil {
		return archive, err
	}
	if differences := detailedMemberHashDifferences(stageMembers, verifiedMembers); len(differences) > 0 {
		return archive, fmt.Errorf("full re-extract verification failed: %s", strings.Join(differences, "; "))
	}
	archive.ListedEntryCount = len(outputEntries)
	archive.ReextractedEntryCount = len(verifiedMembers)
	archive.FullReextractVerified = true

	outputDestination, err := secureJoin(stagingRoot, archiveRelative)
	if err != nil {
		return archive, err
	}
	builtHash, builtSize, err := checkedFile(builtPak)
	if err != nil {
		return archive, err
	}
	if err := copyFileDurable(builtPak, outputDestination, builtHash, builtSize, 0o600); err != nil {
		return archive, err
	}
	archive.OutputPath = filepath.ToSlash(filepath.Join(quartetCompositionOutputRelative, filepath.FromSlash(archiveRelative)))
	archive.OutputSHA256, archive.OutputBytes = builtHash, builtSize
	archive.Status = "published_member_overlay_verified"
	return archive, nil
}

func replaceCompositionMember(source, destination, expectedHash string, expectedSize int64) error {
	info, err := os.Lstat(destination)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return fmt.Errorf("composition destination is not a regular non-symlink file: %s", destination)
	}
	// The destination lives only in the private composition staging tree. Removing it
	// first keeps copyFileDurable portable to Windows, where os.Rename does not replace
	// an existing file. A failure invalidates only this disposable staging directory.
	if err := os.Remove(destination); err != nil {
		return err
	}
	return copyFileDurable(source, destination, expectedHash, expectedSize, 0o600)
}

func mergeCompositionOverlay(overlays map[string]compositionOverlaySource, key string, candidate compositionOverlaySource) error {
	if existing, ok := overlays[key]; ok {
		if existing.Member.SHA256 != candidate.Member.SHA256 || existing.Member.Bytes != candidate.Member.Bytes {
			return fmt.Errorf("non-identical restoration overlay conflict for %s between %s and %s", candidate.Member.InternalPath, strings.Join(existing.Member.SourceProfileIDs, ","), strings.Join(candidate.Member.SourceProfileIDs, ","))
		}
		existing.Member.SourceProfileIDs = append(existing.Member.SourceProfileIDs, candidate.Member.SourceProfileIDs...)
		sort.Strings(existing.Member.SourceProfileIDs)
		existing.Member.SourceProfileIDs = uniqueStrings(existing.Member.SourceProfileIDs)
		overlays[key] = existing
		return nil
	}
	overlays[key] = candidate
	return nil
}

func uniqueStrings(values []string) []string {
	if len(values) < 2 {
		return values
	}
	result := values[:1]
	for _, value := range values[1:] {
		if value != result[len(result)-1] {
			result = append(result, value)
		}
	}
	return result
}

type compositionMemberFingerprint struct {
	Path   string
	SHA256 string
	Bytes  int64
}

func hashCompositionMembers(root string, entries []string) (map[string]compositionMemberFingerprint, error) {
	result := map[string]compositionMemberFingerprint{}
	for _, raw := range entries {
		member, err := normalizeCompositionMember(raw)
		if err != nil {
			return nil, err
		}
		key := foldCompositionPath(member)
		if _, exists := result[key]; exists {
			return nil, fmt.Errorf("case-insensitive duplicate archive member: %s", member)
		}
		memberPath, err := secureCompositionMemberPath(root, member)
		if err != nil {
			return nil, err
		}
		hash, size, err := checkedFile(memberPath)
		if err != nil {
			return nil, fmt.Errorf("hash extracted member %s: %w", member, err)
		}
		result[key] = compositionMemberFingerprint{Path: member, SHA256: hash, Bytes: size}
	}
	return result, nil
}

func memberDifferences(left, right map[string]compositionMemberFingerprint) map[string]bool {
	result := map[string]bool{}
	for key, leftValue := range left {
		rightValue, ok := right[key]
		if !ok || leftValue.SHA256 != rightValue.SHA256 || leftValue.Bytes != rightValue.Bytes {
			result[key] = true
		}
	}
	for key := range right {
		if _, ok := left[key]; !ok {
			result[key] = true
		}
	}
	return result
}

func detailedMemberHashDifferences(left, right map[string]compositionMemberFingerprint) []string {
	set := memberDifferences(left, right)
	keys := sortedSet(set)
	var result []string
	for _, key := range keys {
		leftValue, leftOK := left[key]
		rightValue, rightOK := right[key]
		switch {
		case !leftOK:
			result = append(result, key+" missing from expected tree")
		case !rightOK:
			result = append(result, key+" missing from re-extraction")
		default:
			result = append(result, fmt.Sprintf("%s expected %s/%d got %s/%d", key, leftValue.SHA256, leftValue.Bytes, rightValue.SHA256, rightValue.Bytes))
		}
	}
	return result
}

func foldedMemberSet(values []string) (map[string]bool, error) {
	result := map[string]bool{}
	for _, raw := range values {
		member, err := normalizeCompositionMember(raw)
		if err != nil {
			return nil, err
		}
		key := foldCompositionPath(member)
		if result[key] {
			return nil, fmt.Errorf("duplicate member declaration: %s", member)
		}
		result[key] = true
	}
	return result, nil
}

func setDifference(left, right map[string]bool) []string {
	var result []string
	for key := range left {
		if !right[key] {
			result = append(result, key)
		}
	}
	sort.Strings(result)
	return result
}

func sameStringSet(left, right map[string]bool) bool {
	if len(left) != len(right) {
		return false
	}
	for key := range left {
		if !right[key] {
			return false
		}
	}
	return true
}

func sortedSet(values map[string]bool) []string {
	result := make([]string, 0, len(values))
	for key := range values {
		result = append(result, key)
	}
	sort.Strings(result)
	return result
}

func requireSameEntrySet(left, right []string) error {
	leftSet, err := foldedMemberSet(left)
	if err != nil {
		return err
	}
	rightSet, err := foldedMemberSet(right)
	if err != nil {
		return err
	}
	if sameStringSet(leftSet, rightSet) {
		return nil
	}
	return fmt.Errorf("missing=%s extra=%s", strings.Join(setDifference(leftSet, rightSet), ","), strings.Join(setDifference(rightSet, leftSet), ","))
}

func normalizeCompositionMember(raw string) (string, error) {
	normalized := strings.ReplaceAll(strings.TrimSpace(raw), "\\", "/")
	normalized = strings.TrimLeft(normalized, "/")
	if normalized == "" || strings.ContainsRune(normalized, '\x00') {
		return "", fmt.Errorf("unsafe empty archive member path: %q", raw)
	}
	if len(normalized) >= 2 && ((normalized[0] >= 'A' && normalized[0] <= 'Z') || (normalized[0] >= 'a' && normalized[0] <= 'z')) && normalized[1] == ':' {
		return "", fmt.Errorf("unsafe drive-prefixed archive member path: %q", raw)
	}
	clean := path.Clean(normalized)
	if clean == "." || clean == ".." || strings.HasPrefix(clean, "../") || clean != normalized {
		return "", fmt.Errorf("unsafe or non-canonical archive member path: %q", raw)
	}
	for _, part := range strings.Split(clean, "/") {
		if part == "" || part == "." || part == ".." {
			return "", fmt.Errorf("unsafe archive member path: %q", raw)
		}
	}
	return clean, nil
}

func parseGustPakListing(output string) ([]string, error) {
	var entries []string
	seen := map[string]bool{}
	scanner := bufio.NewScanner(strings.NewReader(output))
	buffer := make([]byte, 64*1024)
	scanner.Buffer(buffer, 2*1024*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if len(line) < 20 || line[9] != ' ' || line[18] != ' ' || !allHex(line[:9]) || !allHex(line[10:18]) {
			continue
		}
		raw := strings.TrimSuffix(line[19:], "*")
		raw = strings.TrimSuffix(raw, " ")
		member, err := normalizeCompositionMember(raw)
		if err != nil {
			return nil, err
		}
		key := foldCompositionPath(member)
		if seen[key] {
			return nil, fmt.Errorf("duplicate case-insensitive member in gust_pak listing: %s", member)
		}
		seen[key] = true
		entries = append(entries, member)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(entries) == 0 {
		return nil, fmt.Errorf("gust_pak returned no parseable archive entries")
	}
	return entries, nil
}

func allHex(value string) bool {
	for _, char := range value {
		if !((char >= '0' && char <= '9') || (char >= 'a' && char <= 'f') || (char >= 'A' && char <= 'F')) {
			return false
		}
	}
	return true
}

func secureCompositionMemberPath(root, member string) (string, error) {
	normalized, err := normalizeCompositionMember(member)
	if err != nil {
		return "", err
	}
	joined := filepath.Join(root, filepath.FromSlash(normalized))
	relative, err := filepath.Rel(root, joined)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("archive member escapes extraction root: %s", member)
	}
	current := filepath.Clean(root)
	parts := strings.Split(filepath.FromSlash(normalized), string(filepath.Separator))
	for index, part := range parts {
		current = filepath.Join(current, part)
		info, statErr := os.Lstat(current)
		if statErr != nil {
			if errors.Is(statErr, os.ErrNotExist) && index < len(parts)-1 {
				continue
			}
			if errors.Is(statErr, os.ErrNotExist) && index == len(parts)-1 {
				return current, nil
			}
			return "", statErr
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return "", fmt.Errorf("symlink rejected in archive member path: %s", current)
		}
	}
	return joined, nil
}

func findExtractionManifest(root, inputName string) (string, error) {
	expectedStem := strings.TrimSuffix(inputName, filepath.Ext(inputName))
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}
	var matches []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			continue
		}
		stem := strings.TrimSuffix(entry.Name(), filepath.Ext(entry.Name()))
		if strings.EqualFold(stem, expectedStem) {
			matches = append(matches, filepath.Join(root, entry.Name()))
		}
	}
	if len(matches) != 1 {
		return "", fmt.Errorf("expected exactly one reconstruction manifest for %s, found %d", inputName, len(matches))
	}
	return matches[0], nil
}

func rootPakFiles(root string) (map[string]bool, error) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	result := map[string]bool{}
	for _, entry := range entries {
		if !entry.IsDir() && strings.EqualFold(filepath.Ext(entry.Name()), ".pak") {
			result[filepath.Join(root, entry.Name())] = true
		}
	}
	return result, nil
}

func cloneCompositionExtraction(source, destination string) error {
	return filepath.WalkDir(source, func(current string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(source, current)
		if err != nil {
			return err
		}
		target := filepath.Join(destination, relative)
		if entry.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("symlink rejected while cloning extraction: %s", current)
		}
		if entry.IsDir() {
			return os.MkdirAll(target, 0o700)
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("non-regular file rejected while cloning extraction: %s", current)
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			return err
		}
		if err := os.Link(current, target); err == nil {
			return nil
		}
		hash, size, err := checkedFile(current)
		if err != nil {
			return err
		}
		return copyFileDurable(current, target, hash, size, 0o600)
	})
}

func resolveCompositionProjectPath(projectRoot, value string) (string, error) {
	if filepath.IsAbs(value) {
		clean := filepath.Clean(value)
		if !pathWithin(projectRoot, clean) {
			return "", fmt.Errorf("composition source leaves project root: %s", value)
		}
		return clean, nil
	}
	return secureJoin(projectRoot, filepath.ToSlash(value))
}

func resolveGustPakPath(projectRoot, explicit string) (string, error) {
	if strings.TrimSpace(explicit) != "" {
		resolved, err := validateCompositionExecutable(explicit)
		if err != nil {
			return "", fmt.Errorf("invalid --gust-pak path: %w", err)
		}
		return resolved, nil
	}
	var candidates []string
	if env := strings.TrimSpace(os.Getenv("GUST_PAK")); env != "" {
		candidates = append(candidates, env)
	}
	if runtime.GOOS == "windows" {
		candidates = append(candidates, filepath.Join(projectRoot, ".local", "vendor", "gust_tools", "gust_pak.exe"))
	} else {
		candidates = append(candidates, filepath.Join(projectRoot, ".local", "vendor", "gust_tools", "gust_pak"))
	}
	for _, name := range []string{"gust_pak", "gust_pak.exe"} {
		if found, err := exec.LookPath(name); err == nil {
			candidates = append(candidates, found)
		}
	}
	seen := map[string]bool{}
	for _, candidate := range candidates {
		absolute, err := filepath.Abs(candidate)
		if err != nil || seen[absolute] {
			continue
		}
		seen[absolute] = true
		if resolved, err := validateCompositionExecutable(absolute); err == nil {
			return resolved, nil
		}
	}
	return "", fmt.Errorf("gust_pak was not found; pass --gust-pak PATH, set GUST_PAK, or build .local/vendor/gust_tools/gust_pak")
}

func validateCompositionExecutable(candidate string) (string, error) {
	absolute, err := filepath.Abs(candidate)
	if err != nil {
		return "", err
	}
	info, err := os.Lstat(absolute)
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", fmt.Errorf("not a regular non-symlink file: %s", absolute)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm()&0o111 == 0 {
		return "", fmt.Errorf("file is not executable: %s", absolute)
	}
	return absolute, nil
}

func publishCompositionDirectory(stagingRoot, outputRoot string) error {
	parent := filepath.Dir(outputRoot)
	backup := filepath.Join(parent, "."+filepath.Base(outputRoot)+".previous-"+transactionID())
	hadPrevious := false
	if info, err := os.Lstat(outputRoot); err == nil {
		if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
			return fmt.Errorf("composition output root is not a regular directory: %s", outputRoot)
		}
		if err := os.Rename(outputRoot, backup); err != nil {
			return err
		}
		hadPrevious = true
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err := os.Rename(stagingRoot, outputRoot); err != nil {
		if hadPrevious {
			_ = os.Rename(backup, outputRoot)
		}
		return err
	}
	if err := fsyncDirectory(parent); err != nil {
		return err
	}
	if hadPrevious {
		if err := os.RemoveAll(backup); err != nil {
			return fmt.Errorf("new payloads published but old local output could not be removed: %w", err)
		}
	}
	return nil
}

func safeWorkName(value string) string {
	var builder strings.Builder
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') || (char >= '0' && char <= '9') || char == '-' || char == '_' || char == '.' {
			builder.WriteRune(char)
		} else {
			builder.WriteByte('_')
		}
	}
	if builder.Len() == 0 {
		return "archive"
	}
	return builder.String()
}

func lastLines(value string, count int) []string {
	lines := strings.Split(strings.TrimSpace(value), "\n")
	if len(lines) > count {
		lines = lines[len(lines)-count:]
	}
	if len(lines) == 1 && lines[0] == "" {
		return []string{}
	}
	return lines
}

func printHumanQuartetCompositionBuild(out io.Writer, report quartetCompositionBuildReport) {
	fmt.Fprintf(out, "\n%s%sQuartet content-aware composition build%s\n", ansiBold, ansiCyan, ansiReset)
	fmt.Fprintf(out, "%sStatus:%s %s\n", ansiBold, ansiReset, report.Status)
	if report.RuntimeTestOnly {
		fmt.Fprintf(out, "Profiles: %d runtime-test candidate(s), production eligibility unchanged\n", len(report.RuntimeTestProfileIDs))
	} else {
		fmt.Fprintf(out, "Profiles: %d production eligible\n", len(report.ProductionProfileIDs))
	}
	for _, archive := range report.Archives {
		style := ansiGreen
		if archive.Status == "failed" {
			style = ansiYellow + ansiBold
		}
		fmt.Fprintf(out, "  %s%-38s%s %s\n", style, archive.ArchiveRelativePath, ansiReset, archive.Status)
		if archive.Mode == "member_overlay" {
			fmt.Fprintf(out, "      base=%s profiles=%d overlay_members=%d reextract=%t\n", archive.BaseSourceKind, len(archive.ProfileIDs), len(archive.OverlayMembers), archive.FullReextractVerified)
		}
	}
	if len(report.Errors) > 0 {
		for _, message := range report.Errors {
			fmt.Fprintf(out, "  %s%s%s\n", ansiYellow, message, ansiReset)
		}
	}
	fmt.Fprintf(out, "%sCommit disabled:%s only local composition payloads and reports may be written; no game file is modified.\n", ansiBold, ansiReset)
}
