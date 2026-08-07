package wardrobe

import "fmt"

type ApplyReport struct {
	Type                               string   `json:"type"`
	FormatVersion                      int      `json:"format_version"`
	Status                             string   `json:"status"`
	Capability                         string   `json:"capability"`
	ProcessID                          uint32   `json:"process_id"`
	ModuleBase                         string   `json:"module_base"`
	AllocatedTable                     string   `json:"allocated_table"`
	AllocatedSyntheticCache            string   `json:"allocated_synthetic_cache"`
	AllocatedContextTable              string   `json:"allocated_context_table"`
	AllocatedOverflowContext           string   `json:"allocated_overflow_context"`
	AllocatedHookStub                  string   `json:"allocated_hook_stub"`
	AllocatedSeenStateStub             string   `json:"allocated_seen_state_stub"`
	BaselineRecordCount                int      `json:"baseline_record_count"`
	AppendedRecordCount                int      `json:"appended_record_count"`
	FinalRecordCount                   int      `json:"final_record_count"`
	ExistingTableBytesPreserved        bool     `json:"existing_table_bytes_preserved"`
	ExistingEmbeddedCachePreserved     bool     `json:"existing_embedded_cache_preserved"`
	EmbeddedCacheBoundRemainedBaseline bool     `json:"embedded_cache_bound_remained_baseline"`
	ObjectWritesPastOriginalCache      bool     `json:"object_writes_past_original_cache"`
	ExistingCostumeFlagsTouched        bool     `json:"existing_costume_flags_touched"`
	SyntheticVisibleIndices            []int    `json:"synthetic_visible_indices"`
	PatchedSites                       []string `json:"patched_sites"`
	ValidationOnlySites                []string `json:"validation_only_sites"`
	SeenValidationSites                []string `json:"seen_validation_sites"`
	PerObjectSyntheticCache            bool     `json:"per_object_synthetic_cache"`
	ContextSlotCount                   int      `json:"context_slot_count"`
	NativePointerFormulaExact          bool     `json:"native_pointer_formula_exact"`
	NativeBranchTargetVerified         bool     `json:"native_branch_target_verified"`
	HookRegisterTransparent            bool     `json:"hook_register_transparent"`
	RDXPreserved                       bool     `json:"rdx_preserved"`
	ProcessLocalSyntheticSeen          bool     `json:"process_local_synthetic_seen_state"`
	SyntheticSeenSurvivesRebuild       bool     `json:"synthetic_seen_survives_cache_rebuild"`
	NativeSeenBehaviorPreserved        bool     `json:"native_seen_behavior_preserved"`
	NativeSeenBackingTouched           bool     `json:"native_seen_backing_touched"`
	SaveMutationPerformed              bool     `json:"save_mutation_performed"`
	OnDiskModuleModified               bool     `json:"on_disk_module_modified"`
	RollbackSemantics                  string   `json:"rollback_semantics"`
	Errors                             []string `json:"errors"`
}

var ErrRuntimeUnsupported = fmt.Errorf("runtime wardrobe apply is supported only by the Windows companion build")
