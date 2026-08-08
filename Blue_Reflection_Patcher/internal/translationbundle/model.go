package translationbundle

// Bundle is the distributable, target-aware Translation payload. It contains
// only edited text plus stable structural keys. Game archive/container data is
// always read from the user's installation at apply time.
type Bundle struct {
	Type               string       `json:"type"`
	FormatVersion      int          `json:"format_version"`
	TranslationVersion string       `json:"translation_version"`
	Targets            []TargetPack `json:"targets"`
}

type TargetPack struct {
	TargetID string   `json:"target_id"`
	Members  []Member `json:"members"`
}

type Member struct {
	ArchiveRelativePath string   `json:"archive_relative_path"`
	InternalPath        string   `json:"internal_path"`
	Kind                string   `json:"kind"` // ebm or xml
	Records             []Record `json:"records"`
}

type EBMMetadata struct {
	Type     uint32 `json:"type"`
	VoiceID  uint32 `json:"voice_id"`
	Unknown1 uint32 `json:"unknown1"`
	NameID   uint32 `json:"name_id"`
	ExtraID  uint32 `json:"extra_id"`
	ExprID   uint32 `json:"expr_id"`
	MsgID    uint32 `json:"msg_id"`
	Unknown2 uint32 `json:"unknown2"`
}

type Record struct {
	LogicalID               string       `json:"logical_id"`
	TargetIndex             int          `json:"target_index"`
	MsgID                   *uint32      `json:"msg_id,omitempty"`
	StringNo                string       `json:"string_no,omitempty"`
	StringID                string       `json:"string_id,omitempty"`
	Metadata                *EBMMetadata `json:"metadata,omitempty"`
	ExpectedTextSHA256      string       `json:"expected_text_sha256,omitempty"`
	ExpectedTechnicalTokens []string     `json:"expected_technical_tokens,omitempty"`
	DesiredText             string       `json:"desired_text"`
}

type BuildStats struct {
	TranslationVersion string         `json:"translation_version"`
	TargetMembers      map[string]int `json:"target_members"`
	TargetRecords      map[string]int `json:"target_records"`
	TotalMembers       int            `json:"total_members"`
	TotalRecords       int            `json:"total_records"`
}

type ApplyAudit struct {
	TranslationVersion  string            `json:"translation_version"`
	TargetID            string            `json:"target_id"`
	Archives            map[string]int    `json:"archives"`
	Members             int               `json:"members"`
	Records             int               `json:"records"`
	AlreadyDesired      int               `json:"already_desired"`
	StructuralRebases   int               `json:"structural_rebases"`
	EncryptedAggregates int               `json:"encrypted_aggregates"`
	OutputSHA256        map[string]string `json:"output_sha256"`
}
