package payloadpreview

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const (
	legacyDLCSourceKind            = "validated_quartet_legacy_dlc_handoff"
	legacyDLCManifestType          = "validated_quartet_legacy_dlc_payload"
	legacyDLCManifestFormatVersion = 1
	legacyDLCPolicyType            = "br_quartet_legacy_dlc_manifest_policy"
	legacyDLCPolicyFormatVersion   = 1
)

//go:embed legacy_dlc_policy.json
var rawLegacyDLCPolicy []byte

type legacyDLCPolicyArtifact struct {
	TargetPath           string   `json:"target_path"`
	Operation            string   `json:"operation"`
	AddedMemberTemplates []string `json:"added_member_templates"`
	ChangedMembers       []string `json:"changed_members"`
	RemovedMembers       []string `json:"removed_members"`
}

type legacyDLCFamilyPolicy struct {
	FamilyID          string                    `json:"family_id"`
	TransactionGroup  string                    `json:"transaction_group"`
	MemberIDPattern   string                    `json:"member_id_pattern"`
	MinimumMembers    int                       `json:"minimum_members"`
	MaximumMembers    int                       `json:"maximum_members"`
	Artifacts         []legacyDLCPolicyArtifact `json:"artifacts"`
	compiledMemberIDs *regexp.Regexp
}

type legacyDLCPolicy struct {
	Type                 string                  `json:"type"`
	FormatVersion        int                     `json:"format_version"`
	ManifestRelativePath string                  `json:"manifest_relative_path"`
	SourceKind           string                  `json:"source_kind"`
	TargetID             string                  `json:"target_id"`
	CandidateRoot        string                  `json:"candidate_root"`
	EvidenceRoot         string                  `json:"evidence_root"`
	Families             []legacyDLCFamilyPolicy `json:"families"`
}

type legacyDLCManifestMemberDelta struct {
	Added   []string `json:"added"`
	Changed []string `json:"changed"`
	Removed []string `json:"removed"`
}

type legacyDLCManifestArtifact struct {
	TargetPath            string                       `json:"target_path"`
	Operation             string                       `json:"operation"`
	CandidateRelativePath string                       `json:"candidate_relative_path"`
	CandidateSize         int64                        `json:"candidate_size"`
	CandidateSHA256       string                       `json:"candidate_sha256"`
	BaselineSize          int64                        `json:"baseline_size"`
	BaselineSHA256        string                       `json:"baseline_sha256"`
	MemberDelta           legacyDLCManifestMemberDelta `json:"member_delta"`
}

type legacyDLCManifestTransaction struct {
	Group         string `json:"group"`
	AllOrNone     bool   `json:"all_or_none"`
	CommitEnabled bool   `json:"commit_enabled"`
}

type legacyDLCManifestProvenance struct {
	WorkstreamID         string `json:"workstream_id"`
	WorkstreamVersion    string `json:"workstream_version"`
	EvidenceRelativePath string `json:"evidence_relative_path"`
	EvidenceSHA256       string `json:"evidence_sha256"`
}

type legacyDLCManifestAuthorization struct {
	CoreHandoffReady              bool `json:"core_handoff_ready"`
	RealTransactionPrepareEnabled bool `json:"real_transaction_prepare_enabled"`
	RealTransactionCommitEnabled  bool `json:"real_transaction_commit_enabled"`
	CandidateInstalled            bool `json:"candidate_installed"`
	ProfileRegistered             bool `json:"profile_registered"`
	RuntimeValidated              bool `json:"runtime_validated"`
	WetVariantIncluded            bool `json:"wet_variant_included"`
	GameModified                  bool `json:"game_modified"`
}

type legacyDLCManifest struct {
	Type          string                         `json:"type"`
	FormatVersion int                            `json:"format_version"`
	FamilyID      string                         `json:"family_id"`
	Generation    int                            `json:"generation"`
	Members       []string                       `json:"members"`
	SourceKind    string                         `json:"source_kind"`
	TargetID      string                         `json:"target_id"`
	Artifacts     []legacyDLCManifestArtifact    `json:"artifacts"`
	Transaction   legacyDLCManifestTransaction   `json:"transaction"`
	Provenance    legacyDLCManifestProvenance    `json:"provenance"`
	Authorization legacyDLCManifestAuthorization `json:"authorization"`
}

// LegacyDLCCompositionArtifact is a manifest-declared, preview-only input
// consumed by the shared Quartet composer. Member deltas are validated against
// the embedded family policy and later verified against the actual PAK contents.
type LegacyDLCCompositionArtifact struct {
	RelativePath          string   `json:"relative_path"`
	Operation             string   `json:"operation"`
	CandidateRelativePath string   `json:"candidate_relative_path"`
	CandidatePath         string   `json:"candidate_path"`
	CandidateSize         int64    `json:"candidate_size"`
	CandidateSHA256       string   `json:"candidate_sha256"`
	BaselinePath          string   `json:"baseline_path"`
	BaselineSize          int64    `json:"baseline_size"`
	BaselineSHA256        string   `json:"baseline_sha256"`
	AddedMembers          []string `json:"added_members"`
	ChangedMembers        []string `json:"changed_members"`
	RemovedMembers        []string `json:"removed_members"`
}

type LegacyDLCCompositionContract struct {
	SourceKind             string                         `json:"source_kind"`
	ManifestPath           string                         `json:"manifest_path"`
	ManifestSHA256         string                         `json:"manifest_sha256"`
	ManifestBytes          int64                          `json:"manifest_bytes"`
	FamilyID               string                         `json:"family_id"`
	Generation             int                            `json:"generation"`
	Members                []string                       `json:"members"`
	TransactionGroup       string                         `json:"transaction_group"`
	WorkstreamVersion      string                         `json:"workstream_version"`
	ProvenanceEvidencePath string                         `json:"provenance_evidence_path"`
	ProvenanceEvidenceHash string                         `json:"provenance_evidence_sha256"`
	TargetID               string                         `json:"target_id"`
	Artifacts              []LegacyDLCCompositionArtifact `json:"artifacts"`
}

func canonicalRelativePath(raw, label string) (string, error) {
	if strings.TrimSpace(raw) == "" || filepath.IsAbs(raw) {
		return "", fmt.Errorf("%s must be a non-empty relative path: %q", label, raw)
	}
	clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(raw)))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, "../") {
		return "", fmt.Errorf("%s escapes its allowed root: %q", label, raw)
	}
	if clean != filepath.ToSlash(raw) {
		return "", fmt.Errorf("%s is not canonical: %q", label, raw)
	}
	return clean, nil
}

func relativeUnderRoot(raw, root, label string) (string, error) {
	clean, err := canonicalRelativePath(raw, label)
	if err != nil {
		return "", err
	}
	cleanRoot, err := canonicalRelativePath(root, label+" policy root")
	if err != nil {
		return "", err
	}
	if clean != cleanRoot && !strings.HasPrefix(clean, cleanRoot+"/") {
		return "", fmt.Errorf("%s is outside the allowed root %s: %s", label, cleanRoot, clean)
	}
	return clean, nil
}

func secureProjectRegularFile(projectRoot, raw, allowedRoot, label string) (string, os.FileInfo, error) {
	clean, err := relativeUnderRoot(raw, allowedRoot, label)
	if err != nil {
		return "", nil, err
	}
	rootAbs, err := filepath.Abs(projectRoot)
	if err != nil {
		return "", nil, err
	}
	rootReal, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return "", nil, fmt.Errorf("resolve project root for %s: %w", label, err)
	}
	joined := filepath.Join(rootAbs, filepath.FromSlash(clean))
	parentReal, err := filepath.EvalSymlinks(filepath.Dir(joined))
	if err != nil {
		return "", nil, fmt.Errorf("resolve parent for %s: %w", label, err)
	}
	relative, err := filepath.Rel(rootReal, parentReal)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", nil, fmt.Errorf("%s resolves outside the project root", label)
	}
	info, err := os.Lstat(joined)
	if err != nil {
		return "", nil, fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", nil, fmt.Errorf("%s is not a regular non-symlink file", label)
	}
	return joined, info, nil
}

func secureGameRegularFile(gameRoot, raw, label string) (string, os.FileInfo, error) {
	clean, err := canonicalRelativePath(raw, label)
	if err != nil {
		return "", nil, err
	}
	rootAbs, err := filepath.Abs(gameRoot)
	if err != nil {
		return "", nil, err
	}
	rootReal, err := filepath.EvalSymlinks(rootAbs)
	if err != nil {
		return "", nil, fmt.Errorf("resolve game root for %s: %w", label, err)
	}
	resolved, exists, err := resolveTargetPath(rootAbs, clean)
	if err != nil || !exists {
		return "", nil, fmt.Errorf("%s is missing: %s", label, clean)
	}
	parentReal, err := filepath.EvalSymlinks(filepath.Dir(resolved))
	if err != nil {
		return "", nil, fmt.Errorf("resolve game target parent for %s: %w", label, err)
	}
	relative, err := filepath.Rel(rootReal, parentReal)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) {
		return "", nil, fmt.Errorf("%s resolves outside the game root", label)
	}
	info, err := os.Lstat(resolved)
	if err != nil {
		return "", nil, fmt.Errorf("inspect %s: %w", label, err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", nil, fmt.Errorf("%s is not a regular non-symlink file", label)
	}
	return resolved, info, nil
}

func validSHA256(raw string) bool {
	if len(raw) != 64 {
		return false
	}
	for _, value := range raw {
		if !((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f') || (value >= 'A' && value <= 'F')) {
			return false
		}
	}
	return true
}

func normalizedUniquePaths(values []string, label string) ([]string, error) {
	result := make([]string, 0, len(values))
	seen := map[string]bool{}
	for _, raw := range values {
		clean, err := canonicalRelativePath(raw, label)
		if err != nil {
			return nil, err
		}
		folded := strings.ToLower(clean)
		if seen[folded] {
			return nil, fmt.Errorf("duplicate %s: %s", label, clean)
		}
		seen[folded] = true
		result = append(result, clean)
	}
	sort.Strings(result)
	return result, nil
}

func sameStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func loadLegacyDLCPolicy() (legacyDLCPolicy, error) {
	var policy legacyDLCPolicy
	if err := json.Unmarshal(rawLegacyDLCPolicy, &policy); err != nil {
		return legacyDLCPolicy{}, fmt.Errorf("decode embedded legacy DLC manifest policy: %w", err)
	}
	if policy.Type != legacyDLCPolicyType || policy.FormatVersion != legacyDLCPolicyFormatVersion {
		return legacyDLCPolicy{}, fmt.Errorf("unsupported legacy DLC manifest policy type/version")
	}
	if policy.SourceKind != legacyDLCSourceKind || strings.TrimSpace(policy.TargetID) == "" {
		return legacyDLCPolicy{}, fmt.Errorf("invalid legacy DLC policy provenance or target")
	}
	if _, err := canonicalRelativePath(policy.ManifestRelativePath, "legacy DLC active manifest path"); err != nil {
		return legacyDLCPolicy{}, err
	}
	if _, err := canonicalRelativePath(policy.CandidateRoot, "legacy DLC candidate root"); err != nil {
		return legacyDLCPolicy{}, err
	}
	if _, err := canonicalRelativePath(policy.EvidenceRoot, "legacy DLC evidence root"); err != nil {
		return legacyDLCPolicy{}, err
	}
	families := map[string]bool{}
	for index := range policy.Families {
		family := &policy.Families[index]
		if strings.TrimSpace(family.FamilyID) == "" || families[family.FamilyID] {
			return legacyDLCPolicy{}, fmt.Errorf("invalid or duplicate legacy DLC family policy: %q", family.FamilyID)
		}
		families[family.FamilyID] = true
		if strings.TrimSpace(family.TransactionGroup) == "" || family.MinimumMembers < 1 || family.MaximumMembers < family.MinimumMembers {
			return legacyDLCPolicy{}, fmt.Errorf("invalid legacy DLC family bounds: %s", family.FamilyID)
		}
		compiled, err := regexp.Compile(family.MemberIDPattern)
		if err != nil || compiled.NumSubexp() != 1 {
			return legacyDLCPolicy{}, fmt.Errorf("legacy DLC family member pattern must contain exactly one capture: %s", family.FamilyID)
		}
		family.compiledMemberIDs = compiled
		if len(family.Artifacts) == 0 {
			return legacyDLCPolicy{}, fmt.Errorf("legacy DLC family policy has no artifacts: %s", family.FamilyID)
		}
		seenTargets := map[string]bool{}
		for _, artifact := range family.Artifacts {
			target, err := canonicalRelativePath(artifact.TargetPath, "legacy DLC policy target")
			if err != nil {
				return legacyDLCPolicy{}, err
			}
			folded := strings.ToLower(target)
			if seenTargets[folded] || artifact.Operation != "replace" {
				return legacyDLCPolicy{}, fmt.Errorf("invalid or duplicate legacy DLC policy artifact: %s", target)
			}
			seenTargets[folded] = true
			for _, template := range artifact.AddedMemberTemplates {
				if strings.Count(template, "{member_key}") == 0 {
					return legacyDLCPolicy{}, fmt.Errorf("legacy DLC added-member template has no member key: %s", template)
				}
				if _, err := canonicalRelativePath(strings.ReplaceAll(template, "{member_key}", "member"), "legacy DLC policy member template"); err != nil {
					return legacyDLCPolicy{}, err
				}
			}
			if _, err := normalizedUniquePaths(artifact.ChangedMembers, "legacy DLC policy changed member"); err != nil {
				return legacyDLCPolicy{}, err
			}
			if _, err := normalizedUniquePaths(artifact.RemovedMembers, "legacy DLC policy removed member"); err != nil {
				return legacyDLCPolicy{}, err
			}
		}
	}
	return policy, nil
}

func legacyDLCFamily(policy legacyDLCPolicy, familyID string) (legacyDLCFamilyPolicy, bool) {
	for _, family := range policy.Families {
		if family.FamilyID == familyID {
			return family, true
		}
	}
	return legacyDLCFamilyPolicy{}, false
}

func expectedLegacyDLCMemberDelta(family legacyDLCFamilyPolicy, policyArtifact legacyDLCPolicyArtifact, members []string) (added, changed, removed []string, err error) {
	for _, memberID := range members {
		match := family.compiledMemberIDs.FindStringSubmatch(memberID)
		if len(match) != 2 {
			return nil, nil, nil, fmt.Errorf("legacy DLC member does not match family policy: %s", memberID)
		}
		for _, template := range policyArtifact.AddedMemberTemplates {
			added = append(added, strings.ReplaceAll(template, "{member_key}", match[1]))
		}
	}
	added, err = normalizedUniquePaths(added, "legacy DLC expected added member")
	if err != nil {
		return nil, nil, nil, err
	}
	changed, err = normalizedUniquePaths(policyArtifact.ChangedMembers, "legacy DLC expected changed member")
	if err != nil {
		return nil, nil, nil, err
	}
	removed, err = normalizedUniquePaths(policyArtifact.RemovedMembers, "legacy DLC expected removed member")
	if err != nil {
		return nil, nil, nil, err
	}
	return added, changed, removed, nil
}

func validateLegacyDLCManifest(projectRoot string, policy legacyDLCPolicy) (legacyDLCManifest, string, os.FileInfo, string, error) {
	manifestPath, manifestInfo, err := secureProjectRegularFile(projectRoot, policy.ManifestRelativePath, filepath.ToSlash(filepath.Dir(policy.ManifestRelativePath)), "legacy DLC active manifest")
	if err != nil {
		return legacyDLCManifest{}, "", nil, "", err
	}
	manifestData, err := os.ReadFile(manifestPath)
	if err != nil {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("read legacy DLC active manifest: %w", err)
	}
	var manifest legacyDLCManifest
	if err := json.Unmarshal(manifestData, &manifest); err != nil {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("decode legacy DLC active manifest: %w", err)
	}
	if manifest.Type != legacyDLCManifestType || manifest.FormatVersion != legacyDLCManifestFormatVersion {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("unsupported legacy DLC active manifest type/version")
	}
	if manifest.SourceKind != policy.SourceKind || manifest.SourceKind != legacyDLCSourceKind || manifest.TargetID != policy.TargetID {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC manifest provenance or target does not match core policy")
	}
	family, ok := legacyDLCFamily(policy, manifest.FamilyID)
	if !ok {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC family is not allowed by core policy: %s", manifest.FamilyID)
	}
	if manifest.Generation < 1 || len(manifest.Members) < family.MinimumMembers || len(manifest.Members) > family.MaximumMembers {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC generation/member bounds are invalid")
	}
	members := append([]string{}, manifest.Members...)
	sortedMembers := append([]string{}, members...)
	sort.Strings(sortedMembers)
	if !sameStrings(members, sortedMembers) {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC members must be sorted canonically")
	}
	seenMembers := map[string]bool{}
	for _, member := range members {
		if !family.compiledMemberIDs.MatchString(member) || seenMembers[member] {
			return legacyDLCManifest{}, "", nil, "", fmt.Errorf("invalid or duplicate legacy DLC member: %s", member)
		}
		seenMembers[member] = true
	}
	if manifest.Transaction.Group != family.TransactionGroup || !manifest.Transaction.AllOrNone || manifest.Transaction.CommitEnabled {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC transaction policy is not preview-only all-or-none")
	}
	authorization := manifest.Authorization
	if !authorization.CoreHandoffReady || authorization.RealTransactionPrepareEnabled || authorization.RealTransactionCommitEnabled || authorization.CandidateInstalled || authorization.ProfileRegistered || authorization.RuntimeValidated || authorization.WetVariantIncluded || authorization.GameModified {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC manifest authorization is not preview-only")
	}
	if manifest.Provenance.WorkstreamID != "quartet_legacy_dlc" || strings.TrimSpace(manifest.Provenance.WorkstreamVersion) == "" || !validSHA256(manifest.Provenance.EvidenceSHA256) {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC manifest provenance is incomplete")
	}
	evidencePath, evidenceInfo, err := secureProjectRegularFile(projectRoot, manifest.Provenance.EvidenceRelativePath, policy.EvidenceRoot, "legacy DLC provenance evidence")
	if err != nil {
		return legacyDLCManifest{}, "", nil, "", err
	}
	evidenceHash, err := hashFile(evidencePath)
	if err != nil {
		return legacyDLCManifest{}, "", nil, "", err
	}
	if !strings.EqualFold(evidenceHash, manifest.Provenance.EvidenceSHA256) || evidenceInfo.Size() <= 0 {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC provenance evidence hash mismatch")
	}
	if len(manifest.Artifacts) == 0 || len(manifest.Artifacts) != len(family.Artifacts) {
		return legacyDLCManifest{}, "", nil, "", fmt.Errorf("legacy DLC manifest must declare exactly %d artifacts", len(family.Artifacts))
	}
	manifestHash, err := hashFile(manifestPath)
	if err != nil {
		return legacyDLCManifest{}, "", nil, "", err
	}
	return manifest, manifestPath, manifestInfo, strings.ToLower(manifestHash), nil
}

// LoadLegacyDLCCompositionContract validates the active DLC-owned manifest,
// provenance evidence, production candidates and installed Quartet baselines.
// It does not prepare a transaction or modify any file.
func LoadLegacyDLCCompositionContract(projectRoot, gameRoot string) (LegacyDLCCompositionContract, error) {
	policy, err := loadLegacyDLCPolicy()
	if err != nil {
		return LegacyDLCCompositionContract{}, err
	}
	manifest, manifestPath, manifestInfo, manifestHash, err := validateLegacyDLCManifest(projectRoot, policy)
	if err != nil {
		return LegacyDLCCompositionContract{}, err
	}
	family, _ := legacyDLCFamily(policy, manifest.FamilyID)
	manifestByTarget := map[string]legacyDLCManifestArtifact{}
	for _, artifact := range manifest.Artifacts {
		target, err := canonicalRelativePath(artifact.TargetPath, "legacy DLC manifest target")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		folded := strings.ToLower(target)
		if _, exists := manifestByTarget[folded]; exists {
			return LegacyDLCCompositionContract{}, fmt.Errorf("duplicate legacy DLC target path: %s", target)
		}
		manifestByTarget[folded] = artifact
	}
	result := LegacyDLCCompositionContract{
		SourceKind:             legacyDLCSourceKind,
		ManifestPath:           manifestPath,
		ManifestSHA256:         manifestHash,
		ManifestBytes:          manifestInfo.Size(),
		FamilyID:               manifest.FamilyID,
		Generation:             manifest.Generation,
		Members:                append([]string{}, manifest.Members...),
		TransactionGroup:       manifest.Transaction.Group,
		WorkstreamVersion:      manifest.Provenance.WorkstreamVersion,
		ProvenanceEvidenceHash: strings.ToLower(manifest.Provenance.EvidenceSHA256),
		TargetID:               manifest.TargetID,
		Artifacts:              []LegacyDLCCompositionArtifact{},
	}
	evidencePath, _, err := secureProjectRegularFile(projectRoot, manifest.Provenance.EvidenceRelativePath, policy.EvidenceRoot, "legacy DLC provenance evidence")
	if err != nil {
		return LegacyDLCCompositionContract{}, err
	}
	result.ProvenanceEvidencePath = evidencePath
	for _, policyArtifact := range family.Artifacts {
		key := strings.ToLower(policyArtifact.TargetPath)
		artifact, exists := manifestByTarget[key]
		if !exists {
			return LegacyDLCCompositionContract{}, fmt.Errorf("legacy DLC manifest is missing required target: %s", policyArtifact.TargetPath)
		}
		if artifact.TargetPath != policyArtifact.TargetPath || artifact.Operation != policyArtifact.Operation {
			return LegacyDLCCompositionContract{}, fmt.Errorf("legacy DLC artifact target/operation is not allowed: %s", artifact.TargetPath)
		}
		if artifact.BaselineSize <= 0 || artifact.CandidateSize <= 0 || !validSHA256(artifact.BaselineSHA256) || !validSHA256(artifact.CandidateSHA256) {
			return LegacyDLCCompositionContract{}, fmt.Errorf("invalid legacy DLC artifact hash/size contract: %s", artifact.TargetPath)
		}
		expectedAdded, expectedChanged, expectedRemoved, err := expectedLegacyDLCMemberDelta(family, policyArtifact, manifest.Members)
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		declaredAdded, err := normalizedUniquePaths(artifact.MemberDelta.Added, "legacy DLC manifest added member")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		declaredChanged, err := normalizedUniquePaths(artifact.MemberDelta.Changed, "legacy DLC manifest changed member")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		declaredRemoved, err := normalizedUniquePaths(artifact.MemberDelta.Removed, "legacy DLC manifest removed member")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		if !sameStrings(declaredAdded, expectedAdded) || !sameStrings(declaredChanged, expectedChanged) || !sameStrings(declaredRemoved, expectedRemoved) {
			return LegacyDLCCompositionContract{}, fmt.Errorf("legacy DLC member delta does not match family policy: %s", artifact.TargetPath)
		}
		candidate, candidateInfo, err := secureProjectRegularFile(projectRoot, artifact.CandidateRelativePath, policy.CandidateRoot, "legacy DLC candidate")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		candidateHash, err := hashFile(candidate)
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		if candidateInfo.Size() != artifact.CandidateSize || !strings.EqualFold(candidateHash, artifact.CandidateSHA256) {
			return LegacyDLCCompositionContract{}, fmt.Errorf("legacy DLC candidate hash/size mismatch: %s", artifact.TargetPath)
		}
		baseline, baselineInfo, err := secureGameRegularFile(gameRoot, artifact.TargetPath, "legacy DLC baseline target")
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		baselineHash, err := hashFile(baseline)
		if err != nil {
			return LegacyDLCCompositionContract{}, err
		}
		if baselineInfo.Size() != artifact.BaselineSize || !strings.EqualFold(baselineHash, artifact.BaselineSHA256) {
			return LegacyDLCCompositionContract{}, fmt.Errorf("legacy DLC baseline hash/size mismatch: %s", artifact.TargetPath)
		}
		result.Artifacts = append(result.Artifacts, LegacyDLCCompositionArtifact{
			RelativePath:          artifact.TargetPath,
			Operation:             artifact.Operation,
			CandidateRelativePath: filepath.ToSlash(artifact.CandidateRelativePath),
			CandidatePath:         candidate,
			CandidateSize:         artifact.CandidateSize,
			CandidateSHA256:       strings.ToLower(artifact.CandidateSHA256),
			BaselinePath:          baseline,
			BaselineSize:          artifact.BaselineSize,
			BaselineSHA256:        strings.ToLower(artifact.BaselineSHA256),
			AddedMembers:          expectedAdded,
			ChangedMembers:        expectedChanged,
			RemovedMembers:        expectedRemoved,
		})
	}
	return result, nil
}

func inspectLegacyDLCModule(projectRoot, gameRoot, moduleID string) ([]ArtifactPreview, bool, string) {
	contract, err := LoadLegacyDLCCompositionContract(projectRoot, gameRoot)
	if err != nil {
		return nil, false, err.Error()
	}
	artifacts := make([]ArtifactPreview, 0, len(contract.Artifacts))
	for _, item := range contract.Artifacts {
		artifact := ArtifactPreview{
			ModuleID:         moduleID,
			RelativePath:     item.RelativePath,
			SourcePath:       item.CandidatePath,
			SourceSHA256:     item.CandidateSHA256,
			SourceBytes:      item.CandidateSize,
			ReportSHA256:     item.CandidateSHA256,
			ReportBytes:      item.CandidateSize,
			ReportVerified:   true,
			TargetPath:       item.BaselinePath,
			TargetExists:     true,
			TargetSHA256:     item.BaselineSHA256,
			TargetBytes:      item.BaselineSize,
			TransactionReady: true,
			Status:           "ready",
			DesiredAction:    item.Operation,
		}
		if strings.EqualFold(item.BaselineSHA256, item.CandidateSHA256) {
			artifact.DesiredAction = "noop"
		}
		artifacts = append(artifacts, artifact)
	}
	reason := fmt.Sprintf("validated legacy DLC manifest %s generation %d (%d members); preview-only all-or-none %d-artifact contract", contract.FamilyID, contract.Generation, len(contract.Members), len(contract.Artifacts))
	return artifacts, true, reason
}
