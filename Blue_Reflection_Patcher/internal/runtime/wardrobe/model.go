package wardrobe

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

const (
	ProfileType          = "br_runtime_wardrobe_target_profile"
	RecordsType          = "br_runtime_wardrobe_records"
	ProfileFormatVersion = 2
	RecordsFormatVersion = 1
	CapabilityIDV1       = "wardrobe_registry_append_v1"
	CapabilityID         = "wardrobe_registry_append_v2"
)

type TargetProfile struct {
	Type               string                `json:"type"`
	FormatVersion      int                   `json:"format_version"`
	Capability         string                `json:"capability"`
	TargetID           string                `json:"target_id"`
	ModuleName         string                `json:"module_name"`
	PreferredImageBase uint64                `json:"preferred_image_base"`
	Registry           RegistryProfile       `json:"registry"`
	RuntimeStorage     RuntimeStorageProfile `json:"runtime_storage"`
	CacheSurface       CacheSurfaceProfile   `json:"cache_surface"`
	TableReferences    []TableReferencePatch `json:"table_references"`
	Bounds             []BoundPatch          `json:"bounds"`
}

type RegistryProfile struct {
	TableRVA            uint32 `json:"table_rva"`
	BaselineRecordCount int    `json:"baseline_record_count"`
	Stride              int    `json:"stride"`
	MaxAppendRecords    int    `json:"max_append_records"`
}

type RuntimeStorageProfile struct {
	CostumeFlagRVA           uint32 `json:"costume_flag_rva"`
	CostumeFlagSize          int    `json:"costume_flag_size"`
	CurrentCostumeRVA        uint32 `json:"current_costume_rva"`
	CurrentCostumeSize       int    `json:"current_costume_size"`
	CharacterCount           int    `json:"character_count"`
	FallbackMetadataRVA      uint32 `json:"fallback_metadata_rva"`
	FallbackMetadataStride   int    `json:"fallback_metadata_stride"`
	FallbackIndexFieldOffset int    `json:"fallback_index_field_offset"`
}

type CacheSurfaceProfile struct {
	ObjectCacheOffset     int              `json:"object_cache_offset"`
	RecordStride          int              `json:"record_stride"`
	BaselineRecordCount   int              `json:"baseline_record_count"`
	NextLiveFieldOffset   int              `json:"next_live_field_offset"`
	IndexFieldOffset      int              `json:"index_field_offset"`
	LabelFieldOffset      int              `json:"label_field_offset"`
	VisibilityFieldOffset int              `json:"visibility_field_offset"`
	PointerHook           CodeHookPatch    `json:"pointer_hook"`
	ValidationOnlySites   []ValidationSite `json:"validation_only_sites"`
}

type CodeHookPatch struct {
	Name         string `json:"name"`
	RVA          uint32 `json:"rva"`
	ExpectedHex  string `json:"expected_hex"`
	OverwriteLen int    `json:"overwrite_len"`
}

type ValidationSite struct {
	Name        string `json:"name"`
	RVA         uint32 `json:"rva"`
	ExpectedHex string `json:"expected_hex"`
	Role        string `json:"role"`
}

type TableReferencePatch struct {
	Name               string `json:"name"`
	RVA                uint32 `json:"rva"`
	ExpectedHex        string `json:"expected_hex"`
	DisplacementOffset int    `json:"displacement_offset"`
	InstructionLength  int    `json:"instruction_length"`
	TableOffset        int    `json:"table_offset"`
}

type BoundPatch struct {
	Name            string `json:"name"`
	RVA             uint32 `json:"rva"`
	ExpectedHex     string `json:"expected_hex"`
	ImmediateOffset int    `json:"immediate_offset"`
	Value           string `json:"value"`
}

type RecordSet struct {
	Type          string          `json:"type"`
	FormatVersion int             `json:"format_version"`
	Capability    string          `json:"capability"`
	Records       []LogicalRecord `json:"records"`
}

type LogicalRecord struct {
	LabelID   uint32 `json:"label_id"`
	Character uint32 `json:"character"`
	Field08   uint32 `json:"field08"`
	Field0C   uint32 `json:"field0c"`
	Field10   uint32 `json:"field10"`
	Field14   uint32 `json:"field14"`
	Field18   uint32 `json:"field18"`
	Field1C   uint32 `json:"field1c"`
	Field20   uint32 `json:"field20"`
	Field24   uint32 `json:"field24"`
	Field28   uint32 `json:"field28"`
	Field2C   uint32 `json:"field2c"`
	Visible   bool   `json:"visible"`
}

type SiteValidation struct {
	Name        string `json:"name"`
	RVA         string `json:"rva"`
	Kind        string `json:"kind"`
	Role        string `json:"role,omitempty"`
	ExpectedHex string `json:"expected_hex"`
	ActualHex   string `json:"actual_hex"`
	Match       bool   `json:"match"`
}

type ModuleValidationReport struct {
	Type                       string           `json:"type"`
	FormatVersion              int              `json:"format_version"`
	Status                     string           `json:"status"`
	ReadOnly                   bool             `json:"read_only"`
	ModulePath                 string           `json:"module_path"`
	ModuleSize                 int64            `json:"module_size"`
	Machine                    string           `json:"machine"`
	ImageBase                  string           `json:"image_base"`
	ProfileTargetID            string           `json:"profile_target_id"`
	BaselineRecordCount        int              `json:"baseline_record_count"`
	Stride                     int              `json:"stride"`
	MaxAppendRecords           int              `json:"max_append_records"`
	TableFileBacked            bool             `json:"table_file_backed"`
	CacheEndExclusive          string           `json:"cache_end_exclusive"`
	NextLiveFieldOffset        string           `json:"next_live_field_offset"`
	EmbeddedCacheExtensionSafe bool             `json:"embedded_cache_extension_safe"`
	Sites                      []SiteValidation `json:"sites"`
	Errors                     []string         `json:"errors"`
}

type PlannedPatch struct {
	Name        string `json:"name"`
	RVA         string `json:"rva"`
	Kind        string `json:"kind"`
	OriginalHex string `json:"original_hex"`
	PatchedHex  string `json:"patched_hex"`
}

type PlanReport struct {
	Type                         string         `json:"type"`
	FormatVersion                int            `json:"format_version"`
	Status                       string         `json:"status"`
	Capability                   string         `json:"capability"`
	BaselineRecordCount          int            `json:"baseline_record_count"`
	AppendedRecordCount          int            `json:"appended_record_count"`
	LogicalIndices               []int          `json:"logical_indices"`
	FinalRecordCount             int            `json:"final_record_count"`
	ExistingRecordsPreserved     bool           `json:"existing_records_preserved"`
	EmbeddedCachePrefixPreserved bool           `json:"embedded_cache_prefix_preserved"`
	EmbeddedCacheCountRemains56  bool           `json:"embedded_cache_count_remains_baseline"`
	SyntheticCacheExternal       bool           `json:"synthetic_cache_external"`
	ObjectWritesPastCache        bool           `json:"object_writes_past_original_cache"`
	GlobalShowAll                bool           `json:"global_show_all"`
	SaveMutationRequired         bool           `json:"save_mutation_required"`
	DisableSemantics             string         `json:"disable_semantics"`
	Patches                      []PlannedPatch `json:"patches"`
	ValidationOnlyInvariantCount int            `json:"validation_only_invariant_count"`
	Errors                       []string       `json:"errors"`
}

func LoadProfile(path string) (TargetProfile, error) {
	var p TargetProfile
	b, err := os.ReadFile(path)
	if err != nil {
		return p, err
	}
	if err := json.Unmarshal(b, &p); err != nil {
		return p, err
	}
	if err := p.Validate(); err != nil {
		return p, err
	}
	return p, nil
}

func LoadRecords(path string) (RecordSet, error) {
	var r RecordSet
	b, err := os.ReadFile(path)
	if err != nil {
		return r, err
	}
	if err := json.Unmarshal(b, &r); err != nil {
		return r, err
	}
	return r, nil
}

func decodeExpected(s string) ([]byte, error) {
	b, err := hex.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("decode expected hex %q: %w", s, err)
	}
	return b, nil
}

func (p TargetProfile) Validate() error {
	if p.Type != ProfileType || p.FormatVersion != ProfileFormatVersion || p.Capability != CapabilityID {
		return fmt.Errorf("unsupported wardrobe target profile type/version/capability")
	}
	if p.ModuleName == "" || p.TargetID == "" {
		return fmt.Errorf("target profile identity is incomplete")
	}
	if p.Registry.BaselineRecordCount <= 0 || p.Registry.Stride != 0x30 {
		return fmt.Errorf("unsupported registry shape")
	}
	if p.Registry.MaxAppendRecords <= 0 || p.Registry.MaxAppendRecords > 8 {
		return fmt.Errorf("max_append_records must be 1..8")
	}
	finalMax := p.Registry.BaselineRecordCount + p.Registry.MaxAppendRecords
	if finalMax > p.RuntimeStorage.CostumeFlagSize {
		return fmt.Errorf("synthetic domain exceeds costumeFlag storage")
	}
	if p.RuntimeStorage.CharacterCount <= 0 || p.RuntimeStorage.CurrentCostumeSize < p.RuntimeStorage.CharacterCount*4 {
		return fmt.Errorf("currentCostume storage is too small")
	}
	c := p.CacheSurface
	if c.ObjectCacheOffset < 0 || c.RecordStride != 0x0c || c.BaselineRecordCount != p.Registry.BaselineRecordCount {
		return fmt.Errorf("unsupported cache shape")
	}
	if c.NextLiveFieldOffset != c.ObjectCacheOffset+c.RecordStride*c.BaselineRecordCount {
		return fmt.Errorf("cache boundary does not end exactly at next live field")
	}
	if c.IndexFieldOffset != 0 || c.LabelFieldOffset != 4 || c.VisibilityFieldOffset != 8 {
		return fmt.Errorf("unsupported cache record field layout")
	}
	hookExpected, err := decodeExpected(c.PointerHook.ExpectedHex)
	if err != nil {
		return err
	}
	if c.PointerHook.RVA == 0 || c.PointerHook.OverwriteLen != len(hookExpected) || c.PointerHook.OverwriteLen < 5 {
		return fmt.Errorf("invalid cache pointer hook")
	}
	if len(p.TableReferences) == 0 || len(p.Bounds) == 0 || len(c.ValidationOnlySites) == 0 {
		return fmt.Errorf("target profile patch/validation surface is incomplete")
	}
	seen := map[uint32]string{}
	add := func(rva uint32, name string) error {
		if old, ok := seen[rva]; ok {
			return fmt.Errorf("duplicate profile RVA %#x (%s/%s)", rva, old, name)
		}
		seen[rva] = name
		return nil
	}
	for _, s := range p.TableReferences {
		if err := add(s.RVA, s.Name); err != nil {
			return err
		}
		e, err := decodeExpected(s.ExpectedHex)
		if err != nil {
			return err
		}
		if s.DisplacementOffset < 0 || s.DisplacementOffset+4 > len(e) || s.InstructionLength != len(e) {
			return fmt.Errorf("invalid table reference %s", s.Name)
		}
	}
	for _, s := range p.Bounds {
		if err := add(s.RVA, s.Name); err != nil {
			return err
		}
		e, err := decodeExpected(s.ExpectedHex)
		if err != nil {
			return err
		}
		if s.ImmediateOffset < 0 || s.ImmediateOffset >= len(e) {
			return fmt.Errorf("invalid bound %s", s.Name)
		}
		if s.Value != "max_index" && s.Value != "record_count" {
			return fmt.Errorf("invalid bound value %q", s.Value)
		}
	}
	if err := add(c.PointerHook.RVA, c.PointerHook.Name); err != nil {
		return err
	}
	for _, s := range c.ValidationOnlySites {
		if err := add(s.RVA, s.Name); err != nil {
			return err
		}
		if _, err := decodeExpected(s.ExpectedHex); err != nil {
			return err
		}
	}
	return nil
}

func (r RecordSet) Validate(p TargetProfile) error {
	if r.Type != RecordsType || r.FormatVersion != RecordsFormatVersion || (r.Capability != CapabilityID && r.Capability != CapabilityIDV1) {
		return fmt.Errorf("unsupported wardrobe record set type/version/capability")
	}
	if len(r.Records) == 0 || len(r.Records) > p.Registry.MaxAppendRecords {
		return fmt.Errorf("record count must be 1..%d", p.Registry.MaxAppendRecords)
	}
	for i, rec := range r.Records {
		if rec.Character >= uint32(p.RuntimeStorage.CharacterCount) {
			return fmt.Errorf("record %d character out of range", i)
		}
		if rec.Visible && rec.Field18 != 0 {
			return fmt.Errorf("record %d requests visible=true but field18 is nonzero", i)
		}
	}
	return nil
}
