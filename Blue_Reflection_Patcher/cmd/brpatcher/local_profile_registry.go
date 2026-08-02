package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	localProfileSchemaVersion = 1
	localProfileWorkstreamID  = "quartet_restoration"
	localProfileManifestRoot  = ".local/build/quartet_restoration/core_profiles"
	localProfilePayloadRoot   = ".local/build/quartet_restoration"
)

type localProfileManifest struct {
	SchemaVersion      int      `json:"schema_version"`
	ProfileID          string   `json:"profile_id"`
	TargetRelativePath string   `json:"target_relative_path"`
	BaselineSHA256     string   `json:"baseline_sha256"`
	BaselineSize       int64    `json:"baseline_size"`
	ProfileSHA256      string   `json:"profile_sha256"`
	ProfileSize        int64    `json:"profile_size"`
	LocalProfilePath   string   `json:"local_profile_path"`
	ChangedMemberCount int      `json:"changed_member_count"`
	ChangedMembers     []string `json:"changed_members"`
	RuntimeValidated   bool     `json:"runtime_validated"`
	WorkstreamID       string   `json:"workstream_id"`
	WorkstreamVersion  string   `json:"workstream_version"`
}

type discoveredLocalProfile struct {
	ManifestPath string
	SourcePath   string
	Manifest     localProfileManifest
	LocalStatus  string
	LocalError   string
}

type localProfileIssue struct {
	ManifestPath       string
	ProfileID          string
	TargetRelativePath string
	RuntimeValidated   bool
	Status             string
	Error              string
}

type localProfileRegistry struct {
	Profiles map[string]discoveredLocalProfile
	Issues   []localProfileIssue
}

type localProfileTargetSpec struct {
	RelativePath string
	Kind         string
	StatePath    string
	OtherState   string
	ReportLatest string
	ReportDir    string
	ReportType   string
}

var localProfileTargets = map[string]localProfileTargetSpec{
	"Data/PACK11.PAK": {
		RelativePath: "Data/PACK11.PAK",
		Kind:         "event",
		StatePath:    ".local/state/core_unified_patcher/quartet_event_profile.json",
		OtherState:   ".local/state/core_unified_patcher/quartet_shader_profile.json",
		ReportLatest: ".local/reports/core/BR_QUARTET_EVENT_PROFILE_TRANSACTION_REPORT.json",
		ReportDir:    ".local/reports/core/quartet_event_profiles",
		ReportType:   profileReportType,
	},
	"Data/PACK10_01.PAK": {
		RelativePath: "Data/PACK10_01.PAK",
		Kind:         "shader",
		StatePath:    ".local/state/core_unified_patcher/quartet_shader_profile.json",
		OtherState:   ".local/state/core_unified_patcher/quartet_event_profile.json",
		ReportLatest: ".local/reports/core/BR_QUARTET_SHADER_PROFILE_TRANSACTION_REPORT.json",
		ReportDir:    ".local/reports/core/quartet_shader_profiles",
		ReportType:   shaderProfileReportType,
	},
}

func discoverLocalProfiles(projectRoot string) (localProfileRegistry, error) {
	registry := localProfileRegistry{Profiles: map[string]discoveredLocalProfile{}}
	projectRoot, err := filepath.Abs(projectRoot)
	if err != nil {
		return registry, err
	}
	manifestRoot, err := secureJoin(projectRoot, localProfileManifestRoot)
	if err != nil {
		return registry, err
	}
	info, err := os.Stat(manifestRoot)
	if errors.Is(err, os.ErrNotExist) {
		return registry, nil
	}
	if err != nil {
		return registry, fmt.Errorf("inspect local profile manifest root: %w", err)
	}
	if !info.IsDir() {
		return registry, fmt.Errorf("local profile manifest root is not a directory: %s", manifestRoot)
	}

	var candidates []string
	err = filepath.WalkDir(manifestRoot, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			registry.Issues = append(registry.Issues, localProfileIssue{ManifestPath: path, Status: "unreadable", Error: walkErr.Error()})
			if entry != nil && entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if path == manifestRoot {
			return nil
		}
		if entry.Type()&os.ModeSymlink != 0 {
			if entry.IsDir() {
				registry.Issues = append(registry.Issues, localProfileIssue{ManifestPath: relativeDisplayPath(projectRoot, path), Status: "symlink_rejected", Error: "symlinked directories are not followed"})
				return filepath.SkipDir
			}
			registry.Issues = append(registry.Issues, localProfileIssue{ManifestPath: relativeDisplayPath(projectRoot, path), Status: "symlink_rejected", Error: "manifest symlink rejected"})
			return nil
		}
		if entry.IsDir() {
			return nil
		}
		if strings.EqualFold(filepath.Ext(entry.Name()), ".json") {
			candidates = append(candidates, path)
		}
		return nil
	})
	if err != nil {
		return registry, err
	}
	sort.Strings(candidates)

	byID := map[string][]discoveredLocalProfile{}
	for _, path := range candidates {
		profile, issue := loadLocalProfileManifest(projectRoot, path)
		if issue != nil {
			registry.Issues = append(registry.Issues, *issue)
			continue
		}
		byID[profile.Manifest.ProfileID] = append(byID[profile.Manifest.ProfileID], profile)
	}
	for profileID, items := range byID {
		if len(items) != 1 {
			sort.Slice(items, func(i, j int) bool { return items[i].ManifestPath < items[j].ManifestPath })
			paths := make([]string, 0, len(items))
			for _, item := range items {
				paths = append(paths, item.ManifestPath)
				registry.Issues = append(registry.Issues, localProfileIssue{
					ManifestPath: item.ManifestPath,
					ProfileID:    profileID,
					Status:       "duplicate_profile_id",
					Error:        "profile_id appears in multiple manifests",
				})
			}
			_ = paths
			continue
		}
		registry.Profiles[profileID] = items[0]
	}
	sort.Slice(registry.Issues, func(i, j int) bool {
		if registry.Issues[i].ProfileID != registry.Issues[j].ProfileID {
			return registry.Issues[i].ProfileID < registry.Issues[j].ProfileID
		}
		return registry.Issues[i].ManifestPath < registry.Issues[j].ManifestPath
	})
	return registry, nil
}

func loadLocalProfileManifest(projectRoot, path string) (discoveredLocalProfile, *localProfileIssue) {
	display := relativeDisplayPath(projectRoot, path)
	resolvedManifest, err := filepath.EvalSymlinks(path)
	if err != nil {
		return discoveredLocalProfile{}, &localProfileIssue{ManifestPath: display, Status: "unreadable", Error: err.Error()}
	}
	manifestRoot, _ := secureJoin(projectRoot, localProfileManifestRoot)
	if !pathWithin(manifestRoot, resolvedManifest) {
		return discoveredLocalProfile{}, &localProfileIssue{ManifestPath: display, Status: "symlink_escape", Error: "resolved manifest leaves the approved manifest root"}
	}
	data, err := os.ReadFile(resolvedManifest)
	if err != nil {
		return discoveredLocalProfile{}, &localProfileIssue{ManifestPath: display, Status: "unreadable", Error: err.Error()}
	}
	var manifest localProfileManifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return discoveredLocalProfile{}, &localProfileIssue{ManifestPath: display, Status: "invalid_json", Error: err.Error()}
	}
	issue := func(status, message string) (discoveredLocalProfile, *localProfileIssue) {
		return discoveredLocalProfile{}, &localProfileIssue{ManifestPath: display, ProfileID: manifest.ProfileID, Status: status, Error: message}
	}
	if manifest.SchemaVersion != localProfileSchemaVersion {
		return issue("unsupported_schema", fmt.Sprintf("schema_version must equal %d", localProfileSchemaVersion))
	}
	if manifest.WorkstreamID != localProfileWorkstreamID {
		return issue("wrong_workstream", "workstream_id must equal quartet_restoration")
	}
	if strings.TrimSpace(manifest.WorkstreamVersion) == "" {
		return issue("invalid_manifest", "workstream_version is required")
	}
	if err := validateProfileID(manifest.ProfileID); err != nil {
		return issue("invalid_profile_id", err.Error())
	}
	spec, ok := localProfileTargets[filepath.ToSlash(manifest.TargetRelativePath)]
	if !ok || spec.RelativePath != manifest.TargetRelativePath {
		return issue("unsupported_target", "target_relative_path is not in the core-owned allowlist")
	}
	if err := validateSHA256(manifest.BaselineSHA256); err != nil || manifest.BaselineSize <= 0 {
		return issue("invalid_manifest", "invalid baseline_sha256 or baseline_size")
	}
	if err := validateSHA256(manifest.ProfileSHA256); err != nil || manifest.ProfileSize <= 0 {
		return issue("invalid_manifest", "invalid profile_sha256 or profile_size")
	}
	if manifest.ChangedMemberCount < 0 || manifest.ChangedMemberCount != len(manifest.ChangedMembers) {
		return issue("invalid_manifest", "changed_member_count must equal the changed_members length")
	}
	for _, member := range manifest.ChangedMembers {
		if strings.TrimSpace(member) == "" {
			return issue("invalid_manifest", "changed_members cannot contain an empty path")
		}
	}
	if err := validateLocalProfilePath(manifest.LocalProfilePath); err != nil {
		return issue("invalid_local_path", err.Error())
	}
	sourcePath, err := secureJoin(projectRoot, manifest.LocalProfilePath)
	if err != nil {
		return issue("invalid_local_path", err.Error())
	}
	payloadRoot, _ := secureJoin(projectRoot, localProfilePayloadRoot)
	resolvedPayloadRoot, err := filepath.EvalSymlinks(payloadRoot)
	if err != nil {
		return issue("local_root_missing", fmt.Sprintf("resolve approved payload root: %v", err))
	}
	sourceInfo, err := os.Lstat(sourcePath)
	if errors.Is(err, os.ErrNotExist) {
		return issue("missing", "local profile file does not exist")
	}
	if err != nil {
		return issue("unreadable", err.Error())
	}
	if sourceInfo.Mode()&os.ModeSymlink != 0 {
		resolved, resolveErr := filepath.EvalSymlinks(sourcePath)
		if resolveErr != nil {
			return issue("unreadable", resolveErr.Error())
		}
		if !pathWithin(resolvedPayloadRoot, resolved) {
			return issue("symlink_escape", "local profile symlink leaves the approved payload root")
		}
		sourcePath = resolved
		sourceInfo, err = os.Stat(sourcePath)
		if err != nil {
			return issue("unreadable", err.Error())
		}
	} else {
		resolved, resolveErr := filepath.EvalSymlinks(sourcePath)
		if resolveErr != nil {
			return issue("unreadable", resolveErr.Error())
		}
		if !pathWithin(resolvedPayloadRoot, resolved) {
			return issue("symlink_escape", "resolved local profile leaves the approved payload root")
		}
		sourcePath = resolved
	}
	if !sourceInfo.Mode().IsRegular() {
		return issue("not_regular", "local profile is not a regular file")
	}
	hash, size, err := checkedFile(sourcePath)
	if err != nil {
		return issue("unreadable", err.Error())
	}
	if size != manifest.ProfileSize {
		return issue("size_mismatch", fmt.Sprintf("got %d bytes, expected %d", size, manifest.ProfileSize))
	}
	if hash != manifest.ProfileSHA256 {
		return issue("sha256_mismatch", fmt.Sprintf("got %s", hash))
	}
	return discoveredLocalProfile{
		ManifestPath: display,
		SourcePath:   sourcePath,
		Manifest:     manifest,
		LocalStatus:  "ok",
	}, nil
}

func validateProfileID(value string) error {
	if value == "" {
		return fmt.Errorf("profile_id is required")
	}
	for _, r := range value {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '_' || r == '-' || r == '.' {
			continue
		}
		return fmt.Errorf("profile_id contains an unsupported character: %q", r)
	}
	return nil
}

func validateLocalProfilePath(value string) error {
	if value == "" || filepath.IsAbs(value) {
		return fmt.Errorf("local_profile_path must be a non-empty relative path")
	}
	slash := filepath.ToSlash(value)
	cleaned := filepath.ToSlash(filepath.Clean(value))
	if slash != cleaned || cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, "../") {
		return fmt.Errorf("local_profile_path is not canonical or contains traversal")
	}
	prefix := localProfilePayloadRoot + "/"
	if !strings.HasPrefix(cleaned, prefix) {
		return fmt.Errorf("local_profile_path must stay under %s/", localProfilePayloadRoot)
	}
	return nil
}

func pathWithin(root, candidate string) bool {
	root, errRoot := filepath.Abs(root)
	candidate, errCandidate := filepath.Abs(candidate)
	if errRoot != nil || errCandidate != nil {
		return false
	}
	relative, err := filepath.Rel(root, candidate)
	if err != nil {
		return false
	}
	return relative == "." || (relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator)))
}

func relativeDisplayPath(projectRoot, path string) string {
	relative, err := filepath.Rel(projectRoot, path)
	if err != nil {
		return filepath.ToSlash(path)
	}
	return filepath.ToSlash(relative)
}
