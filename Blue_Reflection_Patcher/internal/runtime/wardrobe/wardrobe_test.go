package wardrobe

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"testing"
)

type fakeMemory struct {
	data   map[uint64]byte
	next   uint64
	allocs map[uint64]int
	freed  map[uint64]bool
	failAt uint64
	writes []uint64
}

func newFakeMemory() *fakeMemory {
	return &fakeMemory{data: map[uint64]byte{}, next: 0x180400000, allocs: map[uint64]int{}, freed: map[uint64]bool{}}
}
func (m *fakeMemory) put(a uint64, b []byte) {
	for i, v := range b {
		m.data[a+uint64(i)] = v
	}
}
func (m *fakeMemory) Read(a uint64, n int) ([]byte, error) {
	b := make([]byte, n)
	for i := range b {
		b[i] = m.data[a+uint64(i)]
	}
	return b, nil
}
func (m *fakeMemory) Write(a uint64, b []byte) error {
	m.writes = append(m.writes, a)
	if m.failAt != 0 && a == m.failAt {
		return fmt.Errorf("injected")
	}
	m.put(a, b)
	return nil
}
func (m *fakeMemory) AllocateNear(_ uint64, n int) (uint64, error) {
	a := m.next
	m.next += 0x10000
	m.allocs[a] = n
	return a, nil
}
func (m *fakeMemory) Free(a uint64) error { m.freed[a] = true; return nil }
func (m *fakeMemory) ProtectRWX(uint64, int) (func() error, error) {
	return func() error { return nil }, nil
}
func (m *fakeMemory) SetExecutable(uint64, int) error { return nil }
func (m *fakeMemory) Flush(uint64, int) error         { return nil }
func testProfile() TargetProfile {
	return TargetProfile{Type: ProfileType, FormatVersion: 2, Capability: CapabilityID, TargetID: "test", ModuleName: "B1.dll", PreferredImageBase: 0x180000000, Registry: RegistryProfile{TableRVA: 0x1000, BaselineRecordCount: 56, Stride: 0x30, MaxAppendRecords: 8}, RuntimeStorage: RuntimeStorageProfile{CostumeFlagRVA: 0x5000, CostumeFlagSize: 256, CurrentCostumeRVA: 0x5100, CurrentCostumeSize: 60, CharacterCount: 15, FallbackMetadataRVA: 0x6000, FallbackMetadataStride: 0x38, FallbackIndexFieldOffset: 0x0c}, CacheSurface: CacheSurfaceProfile{ObjectCacheOffset: 0xe8, RecordStride: 0x0c, BaselineRecordCount: 56, NextLiveFieldOffset: 0x388, IndexFieldOffset: 0, LabelFieldOffset: 4, VisibilityFieldOffset: 8, PointerHook: CodeHookPatch{Name: "cacheptr", RVA: 0x400, ExpectedHex: "4863c3488d0440488d403a488d0486", OverwriteLen: 15}, ValidationOnlySites: []ValidationSite{{Name: "embedded_cache_initializer_count_guard", RVA: 0x420, ExpectedHex: "83fb38", Role: "must remain 56"}, {Name: "cache_start", RVA: 0x430, ExpectedHex: "488d8fe8000000", Role: "cache start"}, {Name: "cache_end", RVA: 0x440, ExpectedHex: "488d91a0020000", Role: "cache end"}, {Name: "next_field", RVA: 0x450, ExpectedHex: "48639188030000", Role: "next live field"}}}, TableReferences: []TableReferencePatch{{Name: "table", RVA: 0x200, ExpectedHex: "488d0df90d0000", DisplacementOffset: 3, InstructionLength: 7, TableOffset: 0}}, Bounds: []BoundPatch{{Name: "max", RVA: 0x300, ExpectedHex: "83f937", ImmediateOffset: 2, Value: "max_index"}, {Name: "count", RVA: 0x310, ExpectedHex: "83fb38", ImmediateOffset: 2, Value: "record_count"}, {Name: "active_pointer_count", RVA: 0x320, ExpectedHex: "83fb38", ImmediateOffset: 2, Value: "record_count"}, {Name: "active_index_count", RVA: 0x330, ExpectedHex: "83fb38", ImmediateOffset: 2, Value: "record_count"}}}
}
func records8() RecordSet {
	r := RecordSet{Type: RecordsType, FormatVersion: 1, Capability: CapabilityIDV1}
	for i := 0; i < 8; i++ {
		r.Records = append(r.Records, LogicalRecord{LabelID: uint32(1000 + i), Character: uint32(i), Field18: 0, Visible: true})
	}
	return r
}
func seed(m *fakeMemory, p TargetProfile, base uint64) []byte {
	b := make([]byte, p.Registry.BaselineRecordCount*p.Registry.Stride)
	for i := range b {
		b[i] = byte((i*7 + 3) & 255)
	}
	m.put(base+uint64(p.Registry.TableRVA), b)
	for _, s := range p.TableReferences {
		x, _ := decodeExpected(s.ExpectedHex)
		m.put(base+uint64(s.RVA), x)
	}
	for _, s := range p.Bounds {
		x, _ := decodeExpected(s.ExpectedHex)
		m.put(base+uint64(s.RVA), x)
	}
	x, _ := decodeExpected(p.CacheSurface.PointerHook.ExpectedHex)
	m.put(base+uint64(p.CacheSurface.PointerHook.RVA), x)
	for _, s := range p.CacheSurface.ValidationOnlySites {
		x, _ := decodeExpected(s.ExpectedHex)
		m.put(base+uint64(s.RVA), x)
	}
	flags := make([]byte, 256)
	for i := 0; i < 56; i++ {
		flags[i] = byte(i + 1)
	}
	m.put(base+uint64(p.RuntimeStorage.CostumeFlagRVA), flags)
	return b
}
func TestCacheArithmeticStopsAtNextField(t *testing.T) {
	p := testProfile()
	if got := p.CacheSurface.ObjectCacheOffset + p.CacheSurface.RecordStride*p.CacheSurface.BaselineRecordCount; got != 0x388 {
		t.Fatalf("end=%x", got)
	}
}
func TestBuildPlanLeavesInitializerBoundValidationOnly(t *testing.T) {
	p := testProfile()
	pl, err := BuildPlan(p, records8(), 0x180000000, 0x180400000, 0x180410000, 0x180500000)
	if err != nil {
		t.Fatal(err)
	}
	if pl.Status != "pass" || !pl.EmbeddedCacheCountRemains56 || pl.ObjectWritesPastCache || !pl.SyntheticCacheExternal {
		t.Fatalf("bad plan %+v", pl)
	}
	for _, x := range pl.Patches {
		if x.RVA == "0x420" {
			t.Fatal("initializer count guard was patched")
		}
	}
}
func TestPointerStubContainsExternalCacheAndBaselineBranch(t *testing.T) {
	p := testProfile()
	s, err := BuildCachePointerStub(p, 0x1122334455667788)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(s, []byte{0x48, 0xb8, 0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11}) {
		t.Fatalf("shadow address absent %x", s)
	}
	if !bytes.Contains(s, []byte{0x48, 0x8d, 0x04, 0x86}) {
		t.Fatal("baseline object pointer path absent")
	}
}
func TestApplyPreserves56FlagsAndNeverWritesObjectCache(t *testing.T) {
	p := testProfile()
	base := uint64(0x180000000)
	m := newFakeMemory()
	baseline := seed(m, p, base)
	rep, err := ApplyWithMemory(m, base, p, records8())
	if err != nil {
		t.Fatal(err)
	}
	if rep.Status != "applied" || !rep.ExistingEmbeddedCachePreserved || !rep.EmbeddedCacheBoundRemainedBaseline || rep.ObjectWritesPastOriginalCache {
		t.Fatalf("bad report %+v", rep)
	}
	tableAddr := uint64(0x180400000)
	got, _ := m.Read(tableAddr, len(baseline))
	if !bytes.Equal(got, baseline) {
		t.Fatal("registry prefix changed")
	}
	flags, _ := m.Read(base+uint64(p.RuntimeStorage.CostumeFlagRVA), 64)
	for i := 0; i < 56; i++ {
		if flags[i] != byte(i+1) {
			t.Fatalf("flag %d changed", i)
		}
	}
	for i := 56; i < 64; i++ {
		if flags[i] != 1 {
			t.Fatalf("synthetic flag %d=%d", i, flags[i])
		}
	}
	object := uint64(0x700000000)
	for _, a := range m.writes {
		if a >= object+0xe8 && a < object+0x400 {
			t.Fatalf("unexpected object write 0x%x", a)
		}
	}
}
func TestSyntheticCacheLayout(t *testing.T) {
	p := testProfile()
	r := records8()
	b := syntheticCacheBytes(p, r)
	if len(b) != 8*0x0c {
		t.Fatalf("len=%d", len(b))
	}
	for i := 0; i < 8; i++ {
		off := i * 12
		if binary.LittleEndian.Uint32(b[off:]) != uint32(56+i) {
			t.Fatal("index")
		}
		if binary.LittleEndian.Uint32(b[off+4:]) != uint32(1000+i) {
			t.Fatal("label")
		}
		if b[off+8] != 1 {
			t.Fatal("visibility")
		}
	}
}
func TestFailClosedOnValidationOnlyMismatchBeforeAllocation(t *testing.T) {
	p := testProfile()
	base := uint64(0x180000000)
	m := newFakeMemory()
	seed(m, p, base)
	m.put(base+uint64(p.CacheSurface.ValidationOnlySites[0].RVA), []byte{0x83, 0xfb, 0x40})
	rep, _ := ApplyWithMemory(m, base, p, records8())
	if rep.Status != "failed" || len(m.allocs) != 0 {
		t.Fatalf("not fail closed %+v alloc=%v", rep, m.allocs)
	}
}
func TestRollbackFreesBothAllocations(t *testing.T) {
	p := testProfile()
	base := uint64(0x180000000)
	m := newFakeMemory()
	seed(m, p, base)
	m.failAt = base + uint64(p.Bounds[1].RVA)
	rep, _ := ApplyWithMemory(m, base, p, records8())
	if rep.Status != "failed" {
		t.Fatalf("expected fail %+v", rep)
	}
	if !m.freed[0x180400000] || !m.freed[0x180410000] {
		t.Fatalf("allocs not freed %#v", m.freed)
	}
}
