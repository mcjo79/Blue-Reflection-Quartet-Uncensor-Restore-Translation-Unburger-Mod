package wardrobe

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"fmt"
)

type ProcessMemory interface {
	Read(addr uint64, size int) ([]byte, error)
	Write(addr uint64, data []byte) error
	AllocateNear(moduleBase uint64, size int) (uint64, error)
	Free(addr uint64) error
	ProtectRWX(addr uint64, size int) (restore func() error, err error)
	SetExecutable(addr uint64, size int) error
	Flush(addr uint64, size int) error
}

type originalWrite struct {
	addr uint64
	data []byte
	code bool
}

func syntheticCacheBytes(p TargetProfile, records RecordSet) []byte {
	out := make([]byte, len(records.Records)*p.CacheSurface.RecordStride)
	for i, rec := range records.Records {
		off := i * p.CacheSurface.RecordStride
		binary.LittleEndian.PutUint32(out[off+p.CacheSurface.IndexFieldOffset:], uint32(p.Registry.BaselineRecordCount+i))
		binary.LittleEndian.PutUint32(out[off+p.CacheSurface.LabelFieldOffset:], rec.LabelID)
		if rec.Visible {
			out[off+p.CacheSurface.VisibilityFieldOffset] = 1
		}
	}
	return out
}

func preflightSite(mem ProcessMemory, moduleBase uint64, name string, rva uint32, expectedHex string) error {
	expected, _ := decodeExpected(expectedHex)
	actual, err := mem.Read(moduleBase+uint64(rva), len(expected))
	if err != nil {
		return fmt.Errorf("preflight %s: %w", name, err)
	}
	if !bytes.Equal(actual, expected) {
		return fmt.Errorf("preflight %s signature mismatch: expected %s actual %s", name, expectedHex, hex.EncodeToString(actual))
	}
	return nil
}

func ApplyWithMemory(mem ProcessMemory, moduleBase uint64, p TargetProfile, records RecordSet) (ApplyReport, error) {
	report := ApplyReport{Type: "br_runtime_wardrobe_apply", FormatVersion: 2, Capability: CapabilityID, ModuleBase: fmt.Sprintf("0x%x", moduleBase), BaselineRecordCount: p.Registry.BaselineRecordCount, AppendedRecordCount: len(records.Records), FinalRecordCount: p.Registry.BaselineRecordCount + len(records.Records), ExistingCostumeFlagsTouched: false, ExistingEmbeddedCachePreserved: true, EmbeddedCacheBoundRemainedBaseline: true, ObjectWritesPastOriginalCache: false, SaveMutationPerformed: false, OnDiskModuleModified: false, RollbackSemantics: "memory-only registry, shadow-cache and trampoline disappear on process exit; apply failure restores every patched byte and synthetic flag then frees allocations; original 56-entry embedded cache is never extended"}
	if err := p.Validate(); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	if err := records.Validate(p); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	for _, s := range p.TableReferences {
		if err := preflightSite(mem, moduleBase, s.Name, s.RVA, s.ExpectedHex); err != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, err.Error())
			return report, nil
		}
	}
	for _, s := range p.Bounds {
		if err := preflightSite(mem, moduleBase, s.Name, s.RVA, s.ExpectedHex); err != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, err.Error())
			return report, nil
		}
	}
	if err := preflightSite(mem, moduleBase, p.CacheSurface.PointerHook.Name, p.CacheSurface.PointerHook.RVA, p.CacheSurface.PointerHook.ExpectedHex); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	for _, s := range p.CacheSurface.ValidationOnlySites {
		if err := preflightSite(mem, moduleBase, s.Name, s.RVA, s.ExpectedHex); err != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, err.Error())
			return report, nil
		}
		report.ValidationOnlySites = append(report.ValidationOnlySites, s.Name)
	}

	tableSize := p.Registry.BaselineRecordCount * p.Registry.Stride
	baseline, err := mem.Read(moduleBase+uint64(p.Registry.TableRVA), tableSize)
	if err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("read baseline registry: %v", err))
		return report, nil
	}
	newSize := report.FinalRecordCount * p.Registry.Stride
	dataSize := newSize + len(records.Records)*p.CacheSurface.RecordStride
	dataBlock, err := mem.AllocateNear(moduleBase, dataSize)
	if err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("allocate registry/cache: %v", err))
		return report, nil
	}
	report.AllocatedTable = fmt.Sprintf("0x%x", dataBlock)
	shadow := dataBlock + uint64(newSize)
	report.AllocatedSyntheticCache = fmt.Sprintf("0x%x", shadow)
	stubBytes, _ := BuildCachePointerStub(p, shadow)
	stub, err := mem.AllocateNear(moduleBase, len(stubBytes))
	if err != nil {
		_ = mem.Free(dataBlock)
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("allocate hook stub: %v", err))
		return report, nil
	}
	report.AllocatedHookStub = fmt.Sprintf("0x%x", stub)
	committed := false
	writes := []originalWrite{}
	defer func() {
		if committed {
			return
		}
		for i := len(writes) - 1; i >= 0; i-- {
			w := writes[i]
			if w.code {
				restore, e := mem.ProtectRWX(w.addr, len(w.data))
				if e == nil {
					_ = mem.Write(w.addr, w.data)
					_ = mem.Flush(w.addr, len(w.data))
					_ = restore()
				}
			} else {
				_ = mem.Write(w.addr, w.data)
			}
		}
		_ = mem.Free(stub)
		_ = mem.Free(dataBlock)
	}()

	synthetic := make([]byte, newSize)
	copy(synthetic, baseline)
	for i, rec := range records.Records {
		copy(synthetic[tableSize+i*p.Registry.Stride:], EncodeRecord(rec))
	}
	if err := mem.Write(dataBlock, synthetic); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("write synthetic registry: %v", err))
		return report, nil
	}
	cache := syntheticCacheBytes(p, records)
	if err := mem.Write(shadow, cache); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("write shadow cache: %v", err))
		return report, nil
	}
	if err := mem.Write(stub, stubBytes); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("write hook stub: %v", err))
		return report, nil
	}
	if err := mem.SetExecutable(stub, len(stubBytes)); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("make hook stub executable: %v", err))
		return report, nil
	}
	if err := mem.Flush(stub, len(stubBytes)); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, fmt.Sprintf("flush hook stub: %v", err))
		return report, nil
	}
	check, err := mem.Read(dataBlock, tableSize)
	if err != nil || !bytes.Equal(check, baseline) {
		report.Status = "failed"
		if err != nil {
			report.Errors = append(report.Errors, fmt.Sprintf("verify registry prefix: %v", err))
		} else {
			report.Errors = append(report.Errors, "verify registry prefix mismatch")
		}
		return report, nil
	}
	report.ExistingTableBytesPreserved = true
	cacheCheck, err := mem.Read(shadow, len(cache))
	if err != nil || !bytes.Equal(cacheCheck, cache) {
		report.Status = "failed"
		if err != nil {
			report.Errors = append(report.Errors, fmt.Sprintf("verify shadow cache: %v", err))
		} else {
			report.Errors = append(report.Errors, "verify shadow cache mismatch")
		}
		return report, nil
	}
	plan, err := BuildPlan(p, records, moduleBase, dataBlock, shadow, stub)
	if err != nil || plan.Status != "pass" {
		report.Status = "failed"
		if err != nil {
			report.Errors = append(report.Errors, err.Error())
		}
		report.Errors = append(report.Errors, plan.Errors...)
		return report, nil
	}
	for _, patch := range plan.Patches {
		var rva uint32
		var expected []byte
		switch patch.Kind {
		case "table_reference":
			for _, s := range p.TableReferences {
				if s.Name == patch.Name {
					rva = s.RVA
					expected, _ = decodeExpected(s.ExpectedHex)
					break
				}
			}
		case "bound":
			for _, s := range p.Bounds {
				if s.Name == patch.Name {
					rva = s.RVA
					expected, _ = decodeExpected(s.ExpectedHex)
					break
				}
			}
		case "cache_pointer_hook":
			rva = p.CacheSurface.PointerHook.RVA
			expected, _ = decodeExpected(p.CacheSurface.PointerHook.ExpectedHex)
		}
		addr := moduleBase + uint64(rva)
		patched, _ := hex.DecodeString(patch.PatchedHex)
		writes = append(writes, originalWrite{addr: addr, data: append([]byte(nil), expected...), code: true})
		restore, e := mem.ProtectRWX(addr, len(patched))
		if e != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, fmt.Sprintf("protect %s: %v", patch.Name, e))
			return report, nil
		}
		if e = mem.Write(addr, patched); e == nil {
			verify, re := mem.Read(addr, len(patched))
			if re != nil {
				e = re
			} else if !bytes.Equal(verify, patched) {
				e = fmt.Errorf("post-write verification mismatch")
			}
		}
		if e == nil {
			e = mem.Flush(addr, len(patched))
		}
		re := restore()
		if e == nil && re != nil {
			e = re
		}
		if e != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, fmt.Sprintf("patch %s: %v", patch.Name, e))
			return report, nil
		}
		report.PatchedSites = append(report.PatchedSites, patch.Name)
	}
	for i, rec := range records.Records {
		if !rec.Visible {
			continue
		}
		idx := p.Registry.BaselineRecordCount + i
		addr := moduleBase + uint64(p.RuntimeStorage.CostumeFlagRVA) + uint64(idx)
		old, e := mem.Read(addr, 1)
		if e != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, fmt.Sprintf("read synthetic costumeFlag[%d]: %v", idx, e))
			return report, nil
		}
		writes = append(writes, originalWrite{addr: addr, data: append([]byte(nil), old...), code: false})
		if e := mem.Write(addr, []byte{1}); e != nil {
			report.Status = "failed"
			report.Errors = append(report.Errors, fmt.Sprintf("write synthetic costumeFlag[%d]: %v", idx, e))
			return report, nil
		}
		verify, e := mem.Read(addr, 1)
		if e != nil || len(verify) != 1 || verify[0] != 1 {
			report.Status = "failed"
			report.Errors = append(report.Errors, fmt.Sprintf("verify synthetic costumeFlag[%d]", idx))
			return report, nil
		}
		report.SyntheticVisibleIndices = append(report.SyntheticVisibleIndices, idx)
	}
	// Re-read the validation-only embedded-cache count guard after patching. It must still be baseline 56.
	for _, s := range p.CacheSurface.ValidationOnlySites {
		if s.Name == "embedded_cache_initializer_count_guard" {
			if err := preflightSite(mem, moduleBase, s.Name, s.RVA, s.ExpectedHex); err != nil {
				report.Status = "failed"
				report.Errors = append(report.Errors, "embedded cache bound changed unexpectedly: "+err.Error())
				return report, nil
			}
		}
	}
	committed = true
	report.Status = "applied"
	return report, nil
}
