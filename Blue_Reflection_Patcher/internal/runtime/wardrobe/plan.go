package wardrobe

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math"
)

func rel32Patch(moduleBase uint64, rva uint32, instructionLen int, target uint64) (int32, error) {
	next := int64(moduleBase) + int64(rva) + int64(instructionLen)
	disp := int64(target) - next
	if disp < math.MinInt32 || disp > math.MaxInt32 {
		return 0, fmt.Errorf("target outside rel32 reach")
	}
	return int32(disp), nil
}

func BuildCachePointerStub(p TargetProfile, shadowCache uint64) ([]byte, error) {
	base := p.Registry.BaselineRecordCount
	if base > 127 || p.CacheSurface.RecordStride > 127 {
		return nil, fmt.Errorf("cache stub imm8 domain exceeded")
	}
	b := []byte{
		0x83, 0xfb, byte(base), // cmp ebx, baseline
		0x72, 0x1f, // jb existing (+31)
		0x41, 0x52, // push r10
		0x41, 0x89, 0xda, // mov r10d,ebx
		0x41, 0x83, 0xea, byte(base), // sub r10d,baseline
		0x4d, 0x6b, 0xd2, byte(p.CacheSurface.RecordStride), // imul r10,r10,stride
		0x48, 0xb8, // mov rax,imm64
	}
	imm := make([]byte, 8)
	binary.LittleEndian.PutUint64(imm, shadowCache)
	b = append(b, imm...)
	b = append(b,
		0x4c, 0x01, 0xd0, // add rax,r10
		0x41, 0x5a, // pop r10
		0xc3,             // ret
		0x48, 0x63, 0xc3, // existing: movsxd rax,ebx
		0x48, 0x8d, 0x04, 0x40, // lea rax,[rax+rax*2]
		0x48, 0x8d, 0x40, 0x3a, // lea rax,[rax+0x3a]
		0x48, 0x8d, 0x04, 0x86, // lea rax,[rsi+rax*4]
		0xc3, // ret
	)
	return b, nil
}

func BuildPlan(p TargetProfile, r RecordSet, moduleBase, newTable, shadowCache, hookStub uint64) (PlanReport, error) {
	report := PlanReport{Type: "br_runtime_wardrobe_patch_plan", FormatVersion: 2, Capability: CapabilityID, BaselineRecordCount: p.Registry.BaselineRecordCount, AppendedRecordCount: len(r.Records), FinalRecordCount: p.Registry.BaselineRecordCount + len(r.Records), ExistingRecordsPreserved: true, EmbeddedCachePrefixPreserved: true, EmbeddedCacheCountRemains56: true, SyntheticCacheExternal: true, ObjectWritesPastCache: false, GlobalShowAll: false, SaveMutationRequired: false, DisableSemantics: "memory-only registry/cache virtualization disappears when the game process exits; original embedded cache remains 56 records and baseline object fields are untouched", ValidationOnlyInvariantCount: len(p.CacheSurface.ValidationOnlySites)}
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
	if _, err := BuildCachePointerStub(p, shadowCache); err != nil {
		return report, err
	}
	report.Status = "pass"
	return report, nil
}
