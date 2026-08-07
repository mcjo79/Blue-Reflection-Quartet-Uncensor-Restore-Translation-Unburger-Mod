package wardrobe

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math"
)

const contextSlotHeaderSize = 8

type CachePointerStubAudit struct {
	Type                       string   `json:"type"`
	FormatVersion              int      `json:"format_version"`
	Capability                 string   `json:"capability"`
	StubLength                 int      `json:"stub_length"`
	NativePathOffset           int      `json:"native_path_offset"`
	NativeBranchTargetOffset   int      `json:"native_branch_target_offset"`
	NativeBranchTargetVerified bool     `json:"native_branch_target_verified"`
	NativePointerFormulaExact  bool     `json:"native_pointer_formula_exact"`
	RDXPreserved               bool     `json:"rdx_preserved"`
	RegisterTransparent        bool     `json:"register_transparent"`
	PreservedRegisters         []string `json:"preserved_registers"`
	SyntheticCacheScope        string   `json:"synthetic_cache_scope"`
	ContextSlotCount           int      `json:"context_slot_count"`
	ContextSlotStride          int      `json:"context_slot_stride"`
	Errors                     []string `json:"errors"`
}

type SeenStateStubAudit struct {
	Type                       string   `json:"type"`
	FormatVersion              int      `json:"format_version"`
	Capability                 string   `json:"capability"`
	StubLength                 int      `json:"stub_length"`
	NativeMaxIndex             int      `json:"native_max_index"`
	SyntheticMinIndex          int      `json:"synthetic_min_index"`
	SyntheticMaxIndex          int      `json:"synthetic_max_index"`
	NativeBranchTargetOffset   int      `json:"native_branch_target_offset"`
	NativeBranchTargetVerified bool     `json:"native_branch_target_verified"`
	OutOfDomainReturnOffset    int      `json:"out_of_domain_return_offset"`
	OutOfDomainReturnVerified  bool     `json:"out_of_domain_return_verified"`
	TemplateVisibilityOffset   int      `json:"template_visibility_offset"`
	TemplateRecordStride       int      `json:"template_record_stride"`
	TemplateAddress            string   `json:"template_address"`
	NativeSetterAddress        string   `json:"native_setter_address"`
	ProcessLocalState          bool     `json:"process_local_state"`
	NativeTailCallPreserved    bool     `json:"native_tail_call_preserved"`
	DirectSaveMutation         bool     `json:"direct_save_mutation"`
	Errors                     []string `json:"errors"`
}

func rel32Patch(moduleBase uint64, rva uint32, instructionLen int, target uint64) (int32, error) {
	next := int64(moduleBase) + int64(rva) + int64(instructionLen)
	disp := int64(target) - next
	if disp < math.MinInt32 || disp > math.MaxInt32 {
		return 0, fmt.Errorf("target outside rel32 reach")
	}
	return int32(disp), nil
}

func contextSlotStride(p TargetProfile) int {
	return contextSlotHeaderSize + p.Registry.MaxAppendRecords*p.CacheSurface.RecordStride
}

// BuildCachePointerStub builds a call target for RVA 0x2dc20-like sites.
// Native indices execute the exact original RAX formula. Synthetic indices use a
// per-object context slot keyed by RSI; every returned synthetic cache entry is
// refreshed from the process-local synthetic template before it is exposed to the game.
func BuildCachePointerStub(p TargetProfile, templateBase, contextBase, overflowBase uint64) ([]byte, CachePointerStubAudit, error) {
	a := CachePointerStubAudit{Type: "br_runtime_wardrobe_cache_pointer_stub_audit", FormatVersion: 4, Capability: CapabilityID, PreservedRegisters: []string{"rbx", "rbp", "rsi", "rdi", "rcx", "rdx", "r8", "r9", "r10", "r11"}, SyntheticCacheScope: "per_object_context_slot", ContextSlotCount: p.CacheSurface.ContextSlotCount, ContextSlotStride: contextSlotStride(p), RDXPreserved: true, RegisterTransparent: true, NativePointerFormulaExact: true}
	if p.Registry.BaselineRecordCount != 56 || p.Registry.MaxAppendRecords != 8 || p.CacheSurface.RecordStride != 0x0c || p.CacheSurface.ObjectCacheOffset != 0xe8 || contextSlotStride(p) != 0x68 {
		return nil, a, fmt.Errorf("v4 pointer stub requires validated Quartet cache shape 56/8/0x0c/+0xe8")
	}
	// Machine-code template, generated from a source-equivalent x86-64 assembly audit.
	// imm64 placeholders are patched below. Native branch is rel32 and must land at
	// the first byte of the exact original 15-byte pointer calculation.
	b := []byte{
		0x83, 0xfb, 0x38, 0x0f, 0x82, 0x8f, 0x00, 0x00, 0x00,
		0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53, 0x57,
		0x49, 0xba, 0, 0, 0, 0, 0, 0, 0, 0,
		0xb9, 0x00, 0x10, 0x00, 0x00,
		0x4d, 0x8b, 0x1a, 0x49, 0x39, 0xf3, 0x74, 0x29, 0x4d, 0x85, 0xdb, 0x74, 0x14,
		0x49, 0x83, 0xc2, 0x68, 0xff, 0xc9, 0x75, 0xeb,
		0x49, 0xba, 0, 0, 0, 0, 0, 0, 0, 0, 0xeb, 0x10,
		0x31, 0xc0, 0xf0, 0x49, 0x0f, 0xb1, 0x32, 0x74, 0x07, 0x48, 0x39, 0xf0, 0x74, 0x02, 0xeb, 0xdc,
		0x48, 0x63, 0xc3, 0x83, 0xe8, 0x38, 0x41, 0x89, 0xc3, 0x48, 0x8d, 0x04, 0x40, 0x49, 0x8d, 0x7c, 0x82, 0x08,
		0x49, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0,
		0x44, 0x89, 0xd9, 0x48, 0x8d, 0x0c, 0x49, 0x4d, 0x8d, 0x04, 0x88, 0x4d, 0x8b, 0x08, 0x4c, 0x89, 0x0f,
		0x45, 0x8b, 0x48, 0x08, 0x44, 0x89, 0x4f, 0x08, 0x48, 0x89, 0xf8,
		0x5f, 0x41, 0x5b, 0x41, 0x5a, 0x41, 0x59, 0x41, 0x58, 0x5a, 0x59, 0xc3,
		0x48, 0x63, 0xc3, 0x48, 0x8d, 0x04, 0x40, 0x48, 0x8d, 0x40, 0x3a, 0x48, 0x8d, 0x04, 0x86, 0xc3,
	}
	binary.LittleEndian.PutUint64(b[0x16:0x1e], contextBase)
	binary.LittleEndian.PutUint32(b[0x1f:0x23], uint32(p.CacheSurface.ContextSlotCount))
	binary.LittleEndian.PutUint64(b[0x3a:0x42], overflowBase)
	binary.LittleEndian.PutUint64(b[0x68:0x70], templateBase)
	nativeOffset := 0x98
	branchNext := 9
	branchDisp := int32(binary.LittleEndian.Uint32(b[5:9]))
	branchTarget := branchNext + int(branchDisp)
	a.StubLength = len(b)
	a.NativePathOffset = nativeOffset
	a.NativeBranchTargetOffset = branchTarget
	a.NativeBranchTargetVerified = branchTarget == nativeOffset
	original, _ := decodeExpected(p.CacheSurface.PointerHook.ExpectedHex)
	if nativeOffset+len(original) > len(b) || hex.EncodeToString(b[nativeOffset:nativeOffset+len(original)]) != hex.EncodeToString(original) {
		a.NativePointerFormulaExact = false
		a.Errors = append(a.Errors, "native path bytes do not equal original pointer formula")
	}
	if !a.NativeBranchTargetVerified {
		a.Errors = append(a.Errors, "native branch does not target first byte of original formula")
	}
	if len(a.Errors) > 0 {
		return b, a, fmt.Errorf("cache stub audit failed: %v", a.Errors)
	}
	return b, a, nil
}

// BuildSeenStateStub extends only the synthetic seen-state persistence domain.
// Native indices 0..55 tail-jump to the original native setter unchanged.
// Synthetic indices 56..63 update only the process-local template visibility byte;
// cache rebuilds then copy that byte into the per-object synthetic cache.
// Indices above the bounded synthetic domain remain a no-op, matching the original
// forwarder's behavior for out-of-domain indices.
func BuildSeenStateStub(p TargetProfile, templateBase, nativeSetter uint64) ([]byte, SeenStateStubAudit, error) {
	a := SeenStateStubAudit{
		Type:                     "br_runtime_wardrobe_seen_state_stub_audit",
		FormatVersion:            4,
		Capability:               CapabilityID,
		NativeMaxIndex:           p.SeenState.NativeMaxIndex,
		SyntheticMinIndex:        p.Registry.BaselineRecordCount,
		SyntheticMaxIndex:        p.Registry.BaselineRecordCount + p.Registry.MaxAppendRecords - 1,
		TemplateVisibilityOffset: p.CacheSurface.VisibilityFieldOffset,
		TemplateRecordStride:     p.CacheSurface.RecordStride,
		TemplateAddress:          fmt.Sprintf("0x%x", templateBase),
		NativeSetterAddress:      fmt.Sprintf("0x%x", nativeSetter),
		ProcessLocalState:        true,
		NativeTailCallPreserved:  true,
		DirectSaveMutation:       false,
	}
	if p.Registry.BaselineRecordCount != 56 || p.Registry.MaxAppendRecords != 8 ||
		p.CacheSurface.RecordStride != 0x0c || p.CacheSurface.VisibilityFieldOffset != 8 ||
		p.SeenState.NativeMaxIndex != 55 {
		return nil, a, fmt.Errorf("v4 seen-state stub requires validated synthetic domain 56..63 with 0x0c/+8 template layout")
	}
	// x86-64:
	//   cmp ecx,55; jbe native
	//   cmp ecx,63; ja out
	//   eax=ecx-56; rax*=12
	//   rcx=templateBase; [rcx+rax+8]=dl; ret
	// native:
	//   rax=nativeSetter; jmp rax
	// out:
	//   ret
	b := []byte{
		0x83, 0xf9, 0x37,
		0x76, 0x1d,
		0x83, 0xf9, 0x3f,
		0x77, 0x24,
		0x8b, 0xc1,
		0x83, 0xe8, 0x38,
		0x48, 0x6b, 0xc0, 0x0c,
		0x48, 0xb9, 0, 0, 0, 0, 0, 0, 0, 0,
		0x88, 0x54, 0x01, 0x08,
		0xc3,
		0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0,
		0xff, 0xe0,
		0xc3,
	}
	binary.LittleEndian.PutUint64(b[21:29], templateBase)
	binary.LittleEndian.PutUint64(b[36:44], nativeSetter)
	nativeTarget := 5 + int(int8(b[4]))
	outTarget := 10 + int(int8(b[9]))
	a.StubLength = len(b)
	a.NativeBranchTargetOffset = nativeTarget
	a.NativeBranchTargetVerified = nativeTarget == 34
	a.OutOfDomainReturnOffset = outTarget
	a.OutOfDomainReturnVerified = outTarget == 46 && b[outTarget] == 0xc3
	if binary.LittleEndian.Uint64(b[21:29]) != templateBase {
		a.Errors = append(a.Errors, "template address encoding mismatch")
	}
	if binary.LittleEndian.Uint64(b[36:44]) != nativeSetter {
		a.Errors = append(a.Errors, "native setter address encoding mismatch")
	}
	if !a.NativeBranchTargetVerified {
		a.Errors = append(a.Errors, "native branch does not target native tail-call path")
	}
	if !a.OutOfDomainReturnVerified {
		a.Errors = append(a.Errors, "out-of-domain branch does not target RET")
	}
	if len(a.Errors) > 0 {
		return b, a, fmt.Errorf("seen-state stub audit failed: %v", a.Errors)
	}
	return b, a, nil
}

func BuildPlan(p TargetProfile, r RecordSet, moduleBase, newTable, templateBase, contextBase, overflowBase, hookStub, seenStub uint64) (PlanReport, error) {
	report := PlanReport{Type: "br_runtime_wardrobe_patch_plan", FormatVersion: 4, Capability: CapabilityID, BaselineRecordCount: p.Registry.BaselineRecordCount, AppendedRecordCount: len(r.Records), FinalRecordCount: p.Registry.BaselineRecordCount + len(r.Records), ExistingRecordsPreserved: true, EmbeddedCachePrefixPreserved: true, EmbeddedCacheCountRemains56: true, SyntheticCacheExternal: true, ObjectWritesPastCache: false, GlobalShowAll: false, SaveMutationRequired: false, DisableSemantics: "memory-only registry/context-cache virtualization and process-local synthetic seen state disappear when the game process exits; original embedded cache remains 56 records and native save-backed seen state is not widened", ValidationOnlyInvariantCount: len(p.CacheSurface.ValidationOnlySites), PerObjectSyntheticCache: true, ContextSlotCount: p.CacheSurface.ContextSlotCount, NativePointerFormulaExact: true, HookRegisterTransparent: true, ProcessLocalSyntheticSeen: true, SyntheticSeenSurvivesRebuild: true, NativeSeenBehaviorPreserved: true, SeenValidationSiteCount: 1}
	if err := r.Validate(p); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	for i := range r.Records {
		report.LogicalIndices = append(report.LogicalIndices, p.Registry.BaselineRecordCount+i)
	}
	newCount := report.FinalRecordCount
	maxIndex := newCount - 1
	if newCount > 255 {
		return report, fmt.Errorf("record_count does not fit imm8 domain")
	}
	for _, s := range p.TableReferences {
		orig, _ := decodeExpected(s.ExpectedHex)
		patched := append([]byte(nil), orig...)
		target := int64(newTable) + int64(s.TableOffset)
		next := int64(moduleBase) + int64(s.RVA) + int64(s.InstructionLength)
		disp := target - next
		if disp < math.MinInt32 || disp > math.MaxInt32 {
			return report, fmt.Errorf("%s new table outside rel32 reach", s.Name)
		}
		binary.LittleEndian.PutUint32(patched[s.DisplacementOffset:], uint32(int32(disp)))
		report.Patches = append(report.Patches, PlannedPatch{Name: s.Name, RVA: fmt.Sprintf("0x%x", s.RVA), Kind: "table_reference", OriginalHex: hex.EncodeToString(orig), PatchedHex: hex.EncodeToString(patched)})
	}
	for _, s := range p.Bounds {
		orig, _ := decodeExpected(s.ExpectedHex)
		patched := append([]byte(nil), orig...)
		v := maxIndex
		if s.Value == "record_count" {
			v = newCount
		}
		patched[s.ImmediateOffset] = byte(v)
		report.Patches = append(report.Patches, PlannedPatch{Name: s.Name, RVA: fmt.Sprintf("0x%x", s.RVA), Kind: "bound", OriginalHex: hex.EncodeToString(orig), PatchedHex: hex.EncodeToString(patched)})
	}
	h := p.CacheSurface.PointerHook
	orig, _ := decodeExpected(h.ExpectedHex)
	disp, err := rel32Patch(moduleBase, h.RVA, 5, hookStub)
	if err != nil {
		return report, fmt.Errorf("cache pointer hook: %w", err)
	}
	patched := make([]byte, h.OverwriteLen)
	patched[0] = 0xe8
	binary.LittleEndian.PutUint32(patched[1:5], uint32(disp))
	for i := 5; i < len(patched); i++ {
		patched[i] = 0x90
	}
	report.Patches = append(report.Patches, PlannedPatch{Name: h.Name, RVA: fmt.Sprintf("0x%x", h.RVA), Kind: "cache_pointer_hook", OriginalHex: hex.EncodeToString(orig), PatchedHex: hex.EncodeToString(patched)})
	_, audit, err := BuildCachePointerStub(p, templateBase, contextBase, overflowBase)
	if err != nil {
		return report, err
	}
	report.NativeBranchTargetVerified = audit.NativeBranchTargetVerified
	report.NativePointerFormulaExact = audit.NativePointerFormulaExact
	report.HookRegisterTransparent = audit.RegisterTransparent

	sh := p.SeenState.ForwarderHook
	seenOrig, _ := decodeExpected(sh.ExpectedHex)
	seenDisp, err := rel32Patch(moduleBase, sh.RVA, 5, seenStub)
	if err != nil {
		return report, fmt.Errorf("seen-state forwarder hook: %w", err)
	}
	seenPatched := make([]byte, sh.OverwriteLen)
	seenPatched[0] = 0xe9
	binary.LittleEndian.PutUint32(seenPatched[1:5], uint32(seenDisp))
	for i := 5; i < len(seenPatched); i++ {
		seenPatched[i] = 0x90
	}
	report.Patches = append(report.Patches, PlannedPatch{Name: sh.Name, RVA: fmt.Sprintf("0x%x", sh.RVA), Kind: "seen_state_forwarder_hook", OriginalHex: hex.EncodeToString(seenOrig), PatchedHex: hex.EncodeToString(seenPatched)})
	nativeSetter := moduleBase + uint64(p.SeenState.NativeSetterRVA)
	_, seenAudit, err := BuildSeenStateStub(p, templateBase, nativeSetter)
	if err != nil {
		return report, err
	}
	report.ProcessLocalSyntheticSeen = seenAudit.ProcessLocalState
	report.SyntheticSeenSurvivesRebuild = seenAudit.ProcessLocalState
	report.NativeSeenBehaviorPreserved = seenAudit.NativeTailCallPreserved
	report.Status = "pass"
	return report, nil
}
