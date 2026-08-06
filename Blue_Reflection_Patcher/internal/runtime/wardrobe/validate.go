package wardrobe

import (
	"bytes"
	"encoding/hex"
	"fmt"
)

func ValidateModule(path string, p TargetProfile) (ModuleValidationReport, error) {
	report := ModuleValidationReport{Type: "br_runtime_wardrobe_module_validation", FormatVersion: 2, ReadOnly: true, ModulePath: path, ProfileTargetID: p.TargetID, BaselineRecordCount: p.Registry.BaselineRecordCount, Stride: p.Registry.Stride, MaxAppendRecords: p.Registry.MaxAppendRecords, CacheEndExclusive: fmt.Sprintf("0x%x", p.CacheSurface.ObjectCacheOffset+p.CacheSurface.RecordStride*p.CacheSurface.BaselineRecordCount), NextLiveFieldOffset: fmt.Sprintf("0x%x", p.CacheSurface.NextLiveFieldOffset), EmbeddedCacheExtensionSafe: false}
	img, err := OpenPE(path)
	if err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	defer img.Close()
	report.ModuleSize = img.Size
	report.ImageBase = fmt.Sprintf("0x%x", img.ImageBase)
	report.Machine = fmt.Sprintf("0x%x", img.PE.FileHeader.Machine)
	tableBytes := p.Registry.BaselineRecordCount * p.Registry.Stride
	_, backed, terr := img.RVABytes(p.Registry.TableRVA, tableBytes)
	if terr != nil {
		report.Errors = append(report.Errors, terr.Error())
	}
	report.TableFileBacked = backed
	validate := func(name string, rva uint32, kind, role, expectedHex string) {
		expected, _ := decodeExpected(expectedHex)
		actual, ok, e := img.RVABytes(rva, len(expected))
		sv := SiteValidation{Name: name, RVA: fmt.Sprintf("0x%x", rva), Kind: kind, Role: role, ExpectedHex: expectedHex}
		if e != nil {
			report.Errors = append(report.Errors, fmt.Sprintf("%s: %v", name, e))
		} else if !ok {
			report.Errors = append(report.Errors, fmt.Sprintf("%s: RVA is not file-backed", name))
		} else {
			sv.ActualHex = hex.EncodeToString(actual)
			sv.Match = bytes.Equal(actual, expected)
			if !sv.Match {
				report.Errors = append(report.Errors, fmt.Sprintf("%s: signature mismatch", name))
			}
		}
		report.Sites = append(report.Sites, sv)
	}
	for _, s := range p.TableReferences {
		validate(s.Name, s.RVA, "table_reference", "", s.ExpectedHex)
	}
	for _, s := range p.Bounds {
		validate(s.Name, s.RVA, "bound", "", s.ExpectedHex)
	}
	validate(p.CacheSurface.PointerHook.Name, p.CacheSurface.PointerHook.RVA, "cache_pointer_hook", "redirect synthetic indices to external shadow cache", p.CacheSurface.PointerHook.ExpectedHex)
	for _, s := range p.CacheSurface.ValidationOnlySites {
		validate(s.Name, s.RVA, "validation_only", s.Role, s.ExpectedHex)
	}
	if !report.TableFileBacked {
		report.Errors = append(report.Errors, "baseline registry is not fully file-backed")
	}
	if p.CacheSurface.NextLiveFieldOffset != p.CacheSurface.ObjectCacheOffset+p.CacheSurface.RecordStride*p.CacheSurface.BaselineRecordCount {
		report.Errors = append(report.Errors, "cache arithmetic invariant failed")
	}
	if len(report.Errors) == 0 {
		report.Status = "pass"
	} else {
		report.Status = "failed"
	}
	return report, nil
}
