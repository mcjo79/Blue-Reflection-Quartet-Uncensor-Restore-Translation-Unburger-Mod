package baseline

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
	"sort"
	"strings"
	"time"

	"local/blue-reflection-patcher/internal/plan/archivepolicy"
	"local/blue-reflection-patcher/internal/plan/gamepath"
)

const (
	ManifestType          = "br_installation_baseline"
	ManifestFormatVersion = 1
	IndexType             = "br_installation_baseline_index"
	IndexFormatVersion    = 1
)

const (
	ClassificationObservedPreinstall = "observed_preinstall_unverified"
	ClassificationManualAdoptCurrent = "manual_adopt_current"
	SourceCurrentInstallation        = "current_installation"
	ActionCreated                    = "created"
	ActionReused                     = "reused"
)

type FileRecord struct {
	RelativePath         string `json:"relative_path"`
	Existed              bool   `json:"existed"`
	SHA256               string `json:"sha256,omitempty"`
	Bytes                int64  `json:"bytes,omitempty"`
	Mode                 uint32 `json:"mode,omitempty"`
	StoredPath           string `json:"stored_path,omitempty"`
	SourcePath           string `json:"source_path,omitempty"`
	SourceClassification string `json:"source_classification,omitempty"`
}

type Manifest struct {
	Type                 string       `json:"type"`
	FormatVersion        int          `json:"format_version"`
	BaselineID           string       `json:"baseline_id"`
	Fingerprint          string       `json:"fingerprint"`
	TargetID             string       `json:"target_id"`
	GameRoot             string       `json:"game_root"`
	CapturedUTC          time.Time    `json:"captured_utc"`
	Classification       string       `json:"classification"`
	Verification         string       `json:"verification"`
	CaptureMethod        string       `json:"capture_method,omitempty"`
	SourceClassification string       `json:"source_classification,omitempty"`
	AdoptionID           string       `json:"adoption_id,omitempty"`
	PreviousStateArchive string       `json:"previous_state_archive,omitempty"`
	Files                []FileRecord `json:"files"`
}

type Summary struct {
	BaselineID           string    `json:"baseline_id"`
	Fingerprint          string    `json:"fingerprint"`
	ManifestPath         string    `json:"manifest_path"`
	CapturedUTC          time.Time `json:"captured_utc"`
	Classification       string    `json:"classification"`
	CaptureMethod        string    `json:"capture_method,omitempty"`
	SourceClassification string    `json:"source_classification,omitempty"`
	AdoptionID           string    `json:"adoption_id,omitempty"`
	PreviousStateArchive string    `json:"previous_state_archive,omitempty"`
	FileCount            int       `json:"file_count"`
}

type Index struct {
	Type          string    `json:"type"`
	FormatVersion int       `json:"format_version"`
	TargetID      string    `json:"target_id"`
	GameRoot      string    `json:"game_root"`
	UpdatedUTC    time.Time `json:"updated_utc"`
	Baselines     []Summary `json:"baselines"`
}

type EnsureResult struct {
	Action       string
	ManifestPath string
	Manifest     Manifest
	StoredFiles  map[string]string
}

type AdoptionProvenance struct {
	AdoptionID           string
	PreviousStateArchive string
}

type FileComparison struct {
	RelativePath string `json:"relative_path"`
	Expected     string `json:"expected_state"`
	Current      string `json:"current_state"`
	ExpectedHash string `json:"expected_sha256,omitempty"`
	CurrentHash  string `json:"current_sha256,omitempty"`
	Matches      bool   `json:"matches"`
}

type Inspection struct {
	Status             string           `json:"status"`
	StateRoot          string           `json:"state_root"`
	BaselineCount      int              `json:"baseline_count"`
	LatestBaselineID   string           `json:"latest_baseline_id,omitempty"`
	MatchingBaselineID string           `json:"matching_baseline_id,omitempty"`
	Baselines          []Summary        `json:"baselines"`
	Files              []FileComparison `json:"files"`
	Warnings           []string         `json:"warnings"`
}

func Ensure(gameRoot, stateRoot, targetID string, relativePaths []string) (EnsureResult, error) {
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return EnsureResult{}, err
	}
	stateRoot, err = filepath.Abs(stateRoot)
	if err != nil {
		return EnsureResult{}, fmt.Errorf("resolve state root: %w", err)
	}
	if strings.TrimSpace(targetID) == "" {
		return EnsureResult{}, fmt.Errorf("target id is required")
	}
	paths, err := normalizePaths(relativePaths)
	if err != nil {
		return EnsureResult{}, err
	}
	if len(paths) == 0 {
		return EnsureResult{}, fmt.Errorf("baseline requires at least one target path")
	}
	files, err := observe(gameRoot, paths)
	if err != nil {
		return EnsureResult{}, err
	}
	fingerprint, err := fingerprint(targetID, files)
	if err != nil {
		return EnsureResult{}, err
	}
	baselineID := fingerprint[:24]
	baselinesRoot := filepath.Join(stateRoot, "baselines")
	finalRoot := filepath.Join(baselinesRoot, fingerprint)
	manifestPath := filepath.Join(finalRoot, "manifest.json")
	if _, err := os.Stat(manifestPath); err == nil {
		manifest, stored, err := LoadAndVerify(manifestPath)
		if err != nil {
			return EnsureResult{}, err
		}
		if manifest.Fingerprint != fingerprint || manifest.TargetID != targetID || manifest.GameRoot != gameRoot {
			return EnsureResult{}, fmt.Errorf("existing baseline identity mismatch: %s", manifestPath)
		}
		if err := rebuildIndex(stateRoot, targetID, gameRoot); err != nil {
			return EnsureResult{}, err
		}
		return EnsureResult{Action: ActionReused, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return EnsureResult{}, fmt.Errorf("inspect baseline manifest: %w", err)
	}
	if err := os.MkdirAll(baselinesRoot, 0o755); err != nil {
		return EnsureResult{}, fmt.Errorf("create baselines root: %w", err)
	}
	tempRoot, err := temporaryDirectory(baselinesRoot, fingerprint)
	if err != nil {
		return EnsureResult{}, err
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(tempRoot)
		}
	}()
	stored := map[string]string{}
	for index := range files {
		record := &files[index]
		if !record.Existed {
			continue
		}
		source, err := secureGameJoin(gameRoot, record.RelativePath)
		if err != nil {
			return EnsureResult{}, err
		}
		storedRelative := filepath.ToSlash(filepath.Join("files", filepath.FromSlash(record.RelativePath)))
		destination := filepath.Join(tempRoot, filepath.FromSlash(storedRelative))
		if err := copyRegularFile(source, destination, 0o444); err != nil {
			return EnsureResult{}, fmt.Errorf("capture baseline %s: %w", record.RelativePath, err)
		}
		hash, size, err := hashAndSize(destination)
		if err != nil {
			return EnsureResult{}, err
		}
		if hash != record.SHA256 || size != record.Bytes {
			return EnsureResult{}, fmt.Errorf("baseline verification mismatch: %s", record.RelativePath)
		}
		record.StoredPath = storedRelative
		stored[record.RelativePath] = destination
	}
	manifest := Manifest{
		Type: ManifestType, FormatVersion: ManifestFormatVersion,
		BaselineID: baselineID, Fingerprint: fingerprint, TargetID: targetID,
		GameRoot: gameRoot, CapturedUTC: time.Now().UTC(),
		Classification:       ClassificationObservedPreinstall,
		Verification:         "exact path, existence, size and SHA-256; source cleanliness is not assumed",
		CaptureMethod:        "initial_installation_observation",
		SourceClassification: "current_installation",
		Files:                files,
	}
	if err := atomicJSON(filepath.Join(tempRoot, "manifest.json"), manifest, 0o444); err != nil {
		return EnsureResult{}, err
	}
	if err := syncTree(tempRoot); err != nil {
		return EnsureResult{}, err
	}
	if err := os.Rename(tempRoot, finalRoot); err != nil {
		if _, statErr := os.Stat(manifestPath); statErr == nil {
			manifest, stored, loadErr := LoadAndVerify(manifestPath)
			if loadErr != nil {
				return EnsureResult{}, loadErr
			}
			cleanup = true
			if indexErr := rebuildIndex(stateRoot, targetID, gameRoot); indexErr != nil {
				return EnsureResult{}, indexErr
			}
			return EnsureResult{Action: ActionReused, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
		}
		return EnsureResult{}, fmt.Errorf("publish baseline: %w", err)
	}
	cleanup = false
	if err := syncParent(finalRoot); err != nil {
		return EnsureResult{}, err
	}
	manifest, stored, err = LoadAndVerify(manifestPath)
	if err != nil {
		return EnsureResult{}, err
	}
	if err := rebuildIndex(stateRoot, targetID, gameRoot); err != nil {
		return EnsureResult{}, err
	}
	return EnsureResult{Action: ActionCreated, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
}

// EnsureWithInherited preserves records from an already verified baseline and only
// observes requested paths that were not part of that baseline. This is used when
// an installed mod is active: managed paths must keep their original pre-install
// baseline instead of capturing the currently modded game files as a new baseline.
func EnsureWithInherited(gameRoot, stateRoot, targetID string, relativePaths []string, inheritedManifestPath string) (EnsureResult, error) {
	if strings.TrimSpace(inheritedManifestPath) == "" {
		return Ensure(gameRoot, stateRoot, targetID, relativePaths)
	}
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return EnsureResult{}, err
	}
	stateRoot, err = filepath.Abs(stateRoot)
	if err != nil {
		return EnsureResult{}, fmt.Errorf("resolve state root: %w", err)
	}
	paths, err := normalizePaths(relativePaths)
	if err != nil {
		return EnsureResult{}, err
	}
	if len(paths) == 0 {
		return EnsureResult{}, fmt.Errorf("baseline requires at least one target path")
	}
	inherited, inheritedStored, err := LoadAndVerify(inheritedManifestPath)
	if err != nil {
		return EnsureResult{}, err
	}
	if inherited.TargetID != targetID || filepath.Clean(inherited.GameRoot) != gameRoot {
		return EnsureResult{}, fmt.Errorf("inherited baseline identity mismatch")
	}
	inheritedByPath := map[string]FileRecord{}
	for _, record := range inherited.Files {
		inheritedByPath[strings.ToLower(filepath.ToSlash(record.RelativePath))] = record
	}
	files := make([]FileRecord, 0, len(paths))
	sources := map[string]string{}
	extended := false
	for _, relative := range paths {
		key := strings.ToLower(filepath.ToSlash(relative))
		if record, ok := inheritedByPath[key]; ok {
			record.StoredPath = ""
			files = append(files, record)
			if record.Existed {
				source, ok := inheritedStored[record.RelativePath]
				if !ok {
					return EnsureResult{}, fmt.Errorf("inherited baseline stored file is missing: %s", record.RelativePath)
				}
				sources[record.RelativePath] = source
			}
			continue
		}
		observed, err := observe(gameRoot, []string{relative})
		if err != nil {
			return EnsureResult{}, err
		}
		record := observed[0]
		files = append(files, record)
		if record.Existed {
			source, err := secureGameJoin(gameRoot, record.RelativePath)
			if err != nil {
				return EnsureResult{}, err
			}
			sources[record.RelativePath] = source
		}
		extended = true
	}
	classification := inherited.Classification
	verification := "preserved from verified inherited baseline"
	captureMethod := inherited.CaptureMethod
	if captureMethod == "" {
		captureMethod = "inherited_verified_baseline"
	}
	sourceClassification := inherited.SourceClassification
	if sourceClassification == "" {
		sourceClassification = inherited.Classification
	}
	if extended {
		classification = "observed_preinstall_extended_from_active"
		verification = "managed paths preserved from verified inherited baseline; newly requested paths observed exactly by existence, size and SHA-256 without cleanliness claim"
		captureMethod = "inherited_baseline_extended_current_installation"
	}
	return ensureRecords(gameRoot, stateRoot, targetID, files, sources, classification, verification, captureMethod, sourceClassification, inherited.AdoptionID, inherited.PreviousStateArchive)
}

func ensureRecords(gameRoot, stateRoot, targetID string, files []FileRecord, sources map[string]string, classification, verification, captureMethod, sourceClassification, adoptionID, previousStateArchive string) (EnsureResult, error) {
	fingerprint, err := fingerprint(targetID, files)
	if err != nil {
		return EnsureResult{}, err
	}
	baselineID := fingerprint[:24]
	baselinesRoot := filepath.Join(stateRoot, "baselines")
	finalRoot := filepath.Join(baselinesRoot, fingerprint)
	manifestPath := filepath.Join(finalRoot, "manifest.json")
	if _, err := os.Stat(manifestPath); err == nil {
		manifest, stored, err := LoadAndVerify(manifestPath)
		if err != nil {
			return EnsureResult{}, err
		}
		if manifest.Fingerprint != fingerprint || manifest.TargetID != targetID || manifest.GameRoot != gameRoot {
			return EnsureResult{}, fmt.Errorf("existing baseline identity mismatch: %s", manifestPath)
		}
		if err := rebuildIndex(stateRoot, targetID, gameRoot); err != nil {
			return EnsureResult{}, err
		}
		return EnsureResult{Action: ActionReused, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return EnsureResult{}, fmt.Errorf("inspect baseline manifest: %w", err)
	}
	if err := os.MkdirAll(baselinesRoot, 0o755); err != nil {
		return EnsureResult{}, fmt.Errorf("create baselines root: %w", err)
	}
	tempRoot, err := temporaryDirectory(baselinesRoot, fingerprint)
	if err != nil {
		return EnsureResult{}, err
	}
	cleanup := true
	defer func() {
		if cleanup {
			_ = os.RemoveAll(tempRoot)
		}
	}()
	stored := map[string]string{}
	for index := range files {
		record := &files[index]
		if !record.Existed {
			continue
		}
		source, ok := sources[record.RelativePath]
		if !ok {
			return EnsureResult{}, fmt.Errorf("baseline source is missing: %s", record.RelativePath)
		}
		storedRelative := filepath.ToSlash(filepath.Join("files", filepath.FromSlash(record.RelativePath)))
		destination := filepath.Join(tempRoot, filepath.FromSlash(storedRelative))
		if err := copyRegularFile(source, destination, 0o444); err != nil {
			return EnsureResult{}, fmt.Errorf("capture baseline %s: %w", record.RelativePath, err)
		}
		hash, size, err := hashAndSize(destination)
		if err != nil {
			return EnsureResult{}, err
		}
		if hash != record.SHA256 || size != record.Bytes {
			return EnsureResult{}, fmt.Errorf("baseline verification mismatch: %s", record.RelativePath)
		}
		record.StoredPath = storedRelative
		stored[record.RelativePath] = destination
	}
	manifest := Manifest{
		Type: ManifestType, FormatVersion: ManifestFormatVersion,
		BaselineID: baselineID, Fingerprint: fingerprint, TargetID: targetID,
		GameRoot: gameRoot, CapturedUTC: time.Now().UTC(), Classification: classification,
		Verification: verification, CaptureMethod: captureMethod,
		SourceClassification: sourceClassification, AdoptionID: adoptionID,
		PreviousStateArchive: previousStateArchive, Files: files,
	}
	if err := atomicJSON(filepath.Join(tempRoot, "manifest.json"), manifest, 0o444); err != nil {
		return EnsureResult{}, err
	}
	if err := syncTree(tempRoot); err != nil {
		return EnsureResult{}, err
	}
	if err := os.Rename(tempRoot, finalRoot); err != nil {
		if _, statErr := os.Stat(manifestPath); statErr == nil {
			manifest, stored, loadErr := LoadAndVerify(manifestPath)
			if loadErr != nil {
				return EnsureResult{}, loadErr
			}
			if indexErr := rebuildIndex(stateRoot, targetID, gameRoot); indexErr != nil {
				return EnsureResult{}, indexErr
			}
			return EnsureResult{Action: ActionReused, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
		}
		return EnsureResult{}, fmt.Errorf("publish baseline: %w", err)
	}
	cleanup = false
	if err := syncParent(finalRoot); err != nil {
		return EnsureResult{}, err
	}
	manifest, stored, err = LoadAndVerify(manifestPath)
	if err != nil {
		return EnsureResult{}, err
	}
	if err := rebuildIndex(stateRoot, targetID, gameRoot); err != nil {
		return EnsureResult{}, err
	}
	return EnsureResult{Action: ActionCreated, ManifestPath: manifestPath, Manifest: manifest, StoredFiles: stored}, nil
}

// AdoptCurrent captures the explicitly selected current installation files as a
// new baseline after previous patcher state has been archived by the caller. It
// records provenance without claiming that the observed files are official or clean.
func AdoptCurrent(gameRoot, stateRoot, targetID string, relativePaths []string, provenance AdoptionProvenance) (EnsureResult, error) {
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return EnsureResult{}, err
	}
	stateRoot, err = filepath.Abs(stateRoot)
	if err != nil {
		return EnsureResult{}, fmt.Errorf("resolve state root: %w", err)
	}
	paths, err := normalizePaths(relativePaths)
	if err != nil {
		return EnsureResult{}, err
	}
	if len(paths) == 0 {
		return EnsureResult{}, fmt.Errorf("adopted baseline requires at least one target path")
	}
	files, err := observe(gameRoot, paths)
	if err != nil {
		return EnsureResult{}, err
	}
	sources := map[string]string{}
	for index := range files {
		record := &files[index]
		record.SourceClassification = SourceCurrentInstallation
		if !record.Existed {
			continue
		}
		source, err := secureGameJoin(gameRoot, record.RelativePath)
		if err != nil {
			return EnsureResult{}, err
		}
		record.SourcePath = source
		sources[record.RelativePath] = source
	}
	return ensureRecords(
		gameRoot, stateRoot, targetID, files, sources,
		ClassificationManualAdoptCurrent,
		"current installation adopted exactly by path, existence, size and SHA-256 after explicit confirmation; source cleanliness or official provenance is not assumed",
		"manual_adopt_current", SourceCurrentInstallation,
		strings.TrimSpace(provenance.AdoptionID), strings.TrimSpace(provenance.PreviousStateArchive),
	)
}

func LoadAndVerify(manifestPath string) (Manifest, map[string]string, error) {
	absolute, err := regularFile(manifestPath, "baseline manifest")
	if err != nil {
		return Manifest{}, nil, err
	}
	data, err := os.ReadFile(absolute)
	if err != nil {
		return Manifest{}, nil, err
	}
	var manifest Manifest
	if err := json.Unmarshal(data, &manifest); err != nil {
		return Manifest{}, nil, fmt.Errorf("decode baseline manifest: %w", err)
	}
	if manifest.Type != ManifestType || manifest.FormatVersion != ManifestFormatVersion {
		return Manifest{}, nil, fmt.Errorf("unsupported baseline manifest type/version")
	}
	root := filepath.Dir(absolute)
	if filepath.Base(root) != manifest.Fingerprint {
		return Manifest{}, nil, fmt.Errorf("baseline directory fingerprint mismatch")
	}
	expected, err := fingerprint(manifest.TargetID, manifest.Files)
	if err != nil {
		return Manifest{}, nil, err
	}
	if expected != manifest.Fingerprint || manifest.BaselineID != manifest.Fingerprint[:24] {
		return Manifest{}, nil, fmt.Errorf("baseline manifest fingerprint mismatch")
	}
	stored := map[string]string{}
	for _, record := range manifest.Files {
		if _, err := cleanRelativePath(record.RelativePath); err != nil {
			return Manifest{}, nil, err
		}
		if !record.Existed {
			if record.StoredPath != "" || record.SHA256 != "" || record.Bytes != 0 {
				return Manifest{}, nil, fmt.Errorf("absent baseline record carries file data: %s", record.RelativePath)
			}
			continue
		}
		path, err := secureJoin(root, record.StoredPath)
		if err != nil {
			return Manifest{}, nil, err
		}
		hash, size, err := hashAndSize(path)
		if err != nil {
			return Manifest{}, nil, fmt.Errorf("verify baseline %s: %w", record.RelativePath, err)
		}
		if hash != record.SHA256 || size != record.Bytes {
			return Manifest{}, nil, fmt.Errorf("stored baseline changed: %s", record.RelativePath)
		}
		stored[record.RelativePath] = path
	}
	return manifest, stored, nil
}

func Inspect(gameRoot, stateRoot, targetID string) (Inspection, error) {
	gameRoot, err := cleanExistingDirectory(gameRoot, "game root")
	if err != nil {
		return Inspection{}, err
	}
	stateRoot, err = filepath.Abs(stateRoot)
	if err != nil {
		return Inspection{}, err
	}
	manifests, summaries, err := loadAll(stateRoot, targetID, gameRoot)
	if err != nil {
		return Inspection{}, err
	}
	result := Inspection{Status: "not_captured", StateRoot: stateRoot, BaselineCount: len(manifests), Baselines: summaries, Warnings: []string{}}
	if len(manifests) == 0 {
		return result, nil
	}
	latest := manifests[len(manifests)-1]
	result.LatestBaselineID = latest.BaselineID
	matching := ""
	for _, manifest := range manifests {
		matches, _, err := compareManifest(gameRoot, manifest)
		if err != nil {
			return Inspection{}, err
		}
		if matches {
			matching = manifest.BaselineID
		}
	}
	_, comparisons, err := compareManifest(gameRoot, latest)
	if err != nil {
		return Inspection{}, err
	}
	result.Files = comparisons
	if matching != "" {
		result.Status = "matches_known_baseline"
		result.MatchingBaselineID = matching
		return result, nil
	}
	matched, changed, missing := 0, 0, 0
	for _, file := range comparisons {
		if file.Matches {
			matched++
		} else if file.Current == "missing" {
			missing++
		} else {
			changed++
		}
	}
	switch {
	case missing > 0:
		result.Status = "missing_or_changed"
	case matched > 0 && changed > 0:
		result.Status = "mixed_changes"
	case changed > 0:
		result.Status = "changed_unclassified"
	default:
		result.Status = "changed_unclassified"
	}
	result.Warnings = append(result.Warnings, "Current files do not match a stored baseline. This may be a game update or an external modification; no automatic cleanliness claim is made.")
	return result, nil
}

func loadAll(stateRoot, targetID, gameRoot string) ([]Manifest, []Summary, error) {
	root := filepath.Join(stateRoot, "baselines")
	entries, err := os.ReadDir(root)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, err
	}
	var manifests []Manifest
	var summaries []Summary
	for _, entry := range entries {
		if !entry.IsDir() || strings.HasPrefix(entry.Name(), ".tmp-") {
			continue
		}
		path := filepath.Join(root, entry.Name(), "manifest.json")
		manifest, _, err := LoadAndVerify(path)
		if err != nil {
			return nil, nil, err
		}
		if manifest.TargetID != targetID || manifest.GameRoot != gameRoot {
			return nil, nil, fmt.Errorf("baseline registry identity mismatch: %s", path)
		}
		manifests = append(manifests, manifest)
		summaries = append(summaries, Summary{BaselineID: manifest.BaselineID, Fingerprint: manifest.Fingerprint, ManifestPath: path, CapturedUTC: manifest.CapturedUTC, Classification: manifest.Classification, CaptureMethod: manifest.CaptureMethod, SourceClassification: manifest.SourceClassification, AdoptionID: manifest.AdoptionID, PreviousStateArchive: manifest.PreviousStateArchive, FileCount: len(manifest.Files)})
	}
	sort.SliceStable(manifests, func(i, j int) bool { return manifests[i].CapturedUTC.Before(manifests[j].CapturedUTC) })
	sort.SliceStable(summaries, func(i, j int) bool { return summaries[i].CapturedUTC.Before(summaries[j].CapturedUTC) })
	return manifests, summaries, nil
}

func compareManifest(gameRoot string, manifest Manifest) (bool, []FileComparison, error) {
	all := true
	comparisons := make([]FileComparison, 0, len(manifest.Files))
	for _, record := range manifest.Files {
		target, err := secureGameJoin(gameRoot, record.RelativePath)
		if err != nil {
			return false, nil, err
		}
		hash, exists, err := currentRegularHash(target)
		if err != nil {
			return false, nil, err
		}
		item := FileComparison{RelativePath: record.RelativePath, ExpectedHash: record.SHA256}
		if record.Existed {
			item.Expected = "file"
			if exists {
				item.Current = "file"
				item.CurrentHash = hash
				item.Matches = hash == record.SHA256
			} else {
				item.Current = "missing"
			}
		} else {
			item.Expected = "missing"
			if exists {
				item.Current = "file"
				item.CurrentHash = hash
			} else {
				item.Current = "missing"
				item.Matches = true
			}
		}
		if !item.Matches {
			all = false
		}
		comparisons = append(comparisons, item)
	}
	return all, comparisons, nil
}

func observe(gameRoot string, paths []string) ([]FileRecord, error) {
	records := make([]FileRecord, 0, len(paths))
	for _, relative := range paths {
		target, err := secureGameJoin(gameRoot, relative)
		if err != nil {
			return nil, err
		}
		record := FileRecord{RelativePath: filepath.ToSlash(relative)}
		info, err := os.Lstat(target)
		switch {
		case err == nil:
			if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
				return nil, fmt.Errorf("baseline target is not a regular file: %s", target)
			}
			record.Existed = true
			record.Mode = uint32(info.Mode().Perm())
			record.SHA256, record.Bytes, err = hashAndSize(target)
			if err != nil {
				return nil, err
			}
		case errors.Is(err, os.ErrNotExist):
			record.Existed = false
		case err != nil:
			return nil, fmt.Errorf("inspect baseline target: %w", err)
		}
		records = append(records, record)
	}
	return records, nil
}

func fingerprint(targetID string, files []FileRecord) (string, error) {
	type identityFile struct {
		RelativePath string `json:"relative_path"`
		Existed      bool   `json:"existed"`
		SHA256       string `json:"sha256,omitempty"`
		Bytes        int64  `json:"bytes,omitempty"`
	}
	identity := struct {
		TargetID string         `json:"target_id"`
		Files    []identityFile `json:"files"`
	}{TargetID: targetID}
	for _, record := range files {
		identity.Files = append(identity.Files, identityFile{RelativePath: filepath.ToSlash(record.RelativePath), Existed: record.Existed, SHA256: record.SHA256, Bytes: record.Bytes})
	}
	data, err := json.Marshal(identity)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

func rebuildIndex(stateRoot, targetID, gameRoot string) error {
	_, summaries, err := loadAll(stateRoot, targetID, gameRoot)
	if err != nil {
		return err
	}
	index := Index{Type: IndexType, FormatVersion: IndexFormatVersion, TargetID: targetID, GameRoot: gameRoot, UpdatedUTC: time.Now().UTC(), Baselines: summaries}
	return atomicJSON(filepath.Join(stateRoot, "baselines", "index.json"), index, 0o600)
}

func normalizePaths(paths []string) ([]string, error) {
	seen := map[string]bool{}
	var result []string
	for _, path := range paths {
		clean, err := cleanRelativePath(path)
		if err != nil {
			return nil, err
		}
		key := strings.ToLower(filepath.ToSlash(clean))
		if seen[key] {
			continue
		}
		seen[key] = true
		result = append(result, filepath.ToSlash(clean))
	}
	sort.Strings(result)
	return result, nil
}

func temporaryDirectory(parent, fingerprint string) (string, error) {
	var random [6]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", err
	}
	path := filepath.Join(parent, ".tmp-"+fingerprint[:12]+"-"+hex.EncodeToString(random[:]))
	if err := os.Mkdir(path, 0o700); err != nil {
		return "", err
	}
	return path, nil
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
		return "", fmt.Errorf("invalid baseline relative path: %q", path)
	}
	clean := filepath.Clean(filepath.FromSlash(path))
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("baseline path escapes root: %q", path)
	}
	if err := archivepolicy.RejectAnalyticalArchivePath(clean, "baseline"); err != nil {
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
		return "", false, fmt.Errorf("baseline target is not a regular file: %s", path)
	}
	hash, _, err := hashAndSize(path)
	return hash, true, err
}

func hashAndSize(path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	hash := sha256.New()
	n, err := io.Copy(hash, file)
	if err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(hash.Sum(nil)), n, nil
}

func copyRegularFile(source, destination string, mode fs.FileMode) error {
	input, err := regularFile(source, "baseline source")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return err
	}
	in, err := os.Open(input)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(destination)
		}
	}()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	if err := os.Chmod(destination, mode); err != nil {
		return err
	}
	ok = true
	return syncParent(destination)
}

func atomicJSON(path string, value any, mode fs.FileMode) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return atomicWrite(path, data, mode)
}

func atomicWrite(path string, data []byte, mode fs.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(path), ".tmp-baseline-")
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
	if err := syncParent(path); err != nil {
		return err
	}
	ok = true
	return nil
}

func syncTree(root string) error {
	return filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		file, err := os.Open(path)
		if err != nil {
			return err
		}
		syncErr := file.Sync()
		closeErr := file.Close()
		if syncErr != nil {
			return syncErr
		}
		return closeErr
	})
}

func syncParent(path string) error {
	directory, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}
