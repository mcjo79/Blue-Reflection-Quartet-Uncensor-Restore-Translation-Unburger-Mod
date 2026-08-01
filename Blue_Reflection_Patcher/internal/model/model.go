package model

import "time"

const (
	BundleType          = "br_patch_bundle"
	BundleFormatVersion = 1
)

type TargetSpec struct {
	TargetID       string   `json:"target_id"`
	DisplayName    string   `json:"display_name"`
	Project        string   `json:"project"`
	Platform       string   `json:"platform"`
	SteamAppID     uint32   `json:"steam_app_id"`
	InstallDirHint []string `json:"install_dir_hints"`
	Markers        []string `json:"markers"`
	ArchiveFormat  string   `json:"archive_format"`
}

type Detection struct {
	TargetID    string `json:"target_id"`
	DisplayName string `json:"display_name"`
	Root        string `json:"root"`
	Source      string `json:"source"`
	Confidence  string `json:"confidence"`
	SteamAppID  uint32 `json:"steam_app_id,omitempty"`
	BuildID     string `json:"build_id,omitempty"`
}

type BundleManifest struct {
	Type          string           `json:"type"`
	FormatVersion int              `json:"format_version"`
	BundleID      string           `json:"bundle_id"`
	BundleVersion string           `json:"bundle_version"`
	DisplayName   string           `json:"display_name"`
	Compatibility Compatibility    `json:"compatibility"`
	Targets       []BundleTarget   `json:"targets"`
	Modules       []BundleModule   `json:"modules"`
	Operations    []PatchOperation `json:"operations"`
}

type Compatibility struct {
	Mode                     string `json:"mode"`
	RequireWholeArchiveHash  bool   `json:"require_whole_archive_hash"`
	PreserveUnknownEntries   bool   `json:"preserve_unknown_entries"`
	AllowKnownPriorOutputs   bool   `json:"allow_known_prior_outputs"`
	StructuredMergePreferred bool   `json:"structured_merge_preferred"`
}

type BundleTarget struct {
	TargetID      string   `json:"target_id"`
	ArchiveFormat string   `json:"archive_format"`
	RequiredPaths []string `json:"required_paths"`
}

type BundleModule struct {
	ModuleID          string   `json:"module_id"`
	DisplayName       string   `json:"display_name"`
	Description       string   `json:"description"`
	ModuleType        string   `json:"module_type"`
	SupportedTargets  []string `json:"supported_targets"`
	DefaultTargets    []string `json:"default_targets"`
	Dependencies      []string `json:"dependencies"`
	Conflicts         []string `json:"conflicts"`
	Selectable        bool     `json:"selectable"`
	RequiresOwnedGame []string `json:"requires_owned_games"`
}

type BaseVariant struct {
	Label          string `json:"label"`
	EntrySHA256    string `json:"entry_sha256,omitempty"`
	StructureID    string `json:"structure_id,omitempty"`
	RecognizedFrom string `json:"recognized_from,omitempty"`
}

type PatchOperation struct {
	OperationID      string        `json:"operation_id"`
	ModuleID         string        `json:"module_id"`
	TargetID         string        `json:"target_id"`
	ArchivePath      string        `json:"archive_path"`
	EntryPath        string        `json:"entry_path"`
	Kind             string        `json:"kind"`
	ConflictPolicy   string        `json:"conflict_policy"`
	PayloadRef       string        `json:"payload_ref,omitempty"`
	SourceTargetID   string        `json:"source_target_id,omitempty"`
	SourceArchive    string        `json:"source_archive_path,omitempty"`
	SourceEntry      string        `json:"source_entry_path,omitempty"`
	BaseVariants     []BaseVariant `json:"base_variants"`
	RecognizedOutput []string      `json:"recognized_output_sha256"`
}

type TargetPlan struct {
	TargetID    string           `json:"target_id"`
	DisplayName string           `json:"display_name"`
	Root        string           `json:"root"`
	Modules     []string         `json:"modules"`
	Archives    []string         `json:"archives"`
	Operations  []PatchOperation `json:"operations"`
	Warnings    []string         `json:"warnings"`
}

type PatchPlan struct {
	Type             string       `json:"type"`
	FormatVersion    int          `json:"format_version"`
	GeneratedUTC     time.Time    `json:"generated_utc"`
	BundleID         string       `json:"bundle_id"`
	BundleVersion    string       `json:"bundle_version"`
	StateStrategy    string       `json:"state_strategy"`
	TransactionModel string       `json:"transaction_model"`
	Targets          []TargetPlan `json:"targets"`
	Warnings         []string     `json:"warnings"`
}
