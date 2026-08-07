package br1rebuild

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"sort"
)

type peSection struct {
	Index, HeaderOff           int
	Name                       string
	VSize, VAddr, RawSize, Raw uint32
}
type peImage struct {
	D                                        []byte
	PE, NsecOff, Nsec, OptSize, Opt, SectOff int
	SectAlign, FileAlign                     uint32
	SizeOfImageOff                           int
	SizeOfHeaders                            uint32
	ImageBase                                uint64
	sections                                 []peSection
}

func parsePE(data []byte) (*peImage, error) {
	if len(data) < 0x100 {
		return nil, fmt.Errorf("PE too small")
	}
	pe := int(binary.LittleEndian.Uint32(data[0x3c:0x40]))
	if pe+24 > len(data) || string(data[pe:pe+4]) != "PE\x00\x00" {
		return nil, fmt.Errorf("invalid PE signature")
	}
	n := int(binary.LittleEndian.Uint16(data[pe+6 : pe+8]))
	optSize := int(binary.LittleEndian.Uint16(data[pe+20 : pe+22]))
	opt := pe + 24
	if opt+optSize > len(data) {
		return nil, fmt.Errorf("truncated PE optional header")
	}
	p := &peImage{D: append([]byte(nil), data...), PE: pe, NsecOff: pe + 6, Nsec: n, OptSize: optSize, Opt: opt, SectOff: opt + optSize}
	p.SectAlign = binary.LittleEndian.Uint32(data[opt+32 : opt+36])
	p.FileAlign = binary.LittleEndian.Uint32(data[opt+36 : opt+40])
	p.SizeOfImageOff = opt + 56
	p.SizeOfHeaders = binary.LittleEndian.Uint32(data[opt+60 : opt+64])
	p.ImageBase = binary.LittleEndian.Uint64(data[opt+24 : opt+32])
	for i := 0; i < n; i++ {
		o := p.SectOff + i*40
		if o+40 > len(data) {
			return nil, fmt.Errorf("truncated section table")
		}
		nm := string(bytes.TrimRight(data[o:o+8], "\x00"))
		p.sections = append(p.sections, peSection{i, o, nm, binary.LittleEndian.Uint32(data[o+8 : o+12]), binary.LittleEndian.Uint32(data[o+12 : o+16]), binary.LittleEndian.Uint32(data[o+16 : o+20]), binary.LittleEndian.Uint32(data[o+20 : o+24])})
	}
	return p, nil
}
func (p *peImage) section(name string) (peSection, bool) {
	for _, s := range p.sections {
		if s.Name == name {
			return s, true
		}
	}
	return peSection{}, false
}
func (p *peImage) fileOffsetRVA(off int) (uint32, bool) {
	for _, s := range p.sections {
		if off >= int(s.Raw) && off < int(s.Raw+s.RawSize) {
			return s.VAddr + uint32(off-int(s.Raw)), true
		}
	}
	return 0, false
}
func alignU(v, a uint32) uint32 {
	if a == 0 {
		return v
	}
	return (v + a - 1) / a * a
}

func EncodeWardrobeTable(cs *WardrobePlan) ([]WardrobeRecord, error) {
	if len(cs.TargetRoster) != 56 {
		return nil, fmt.Errorf("expected stock Quartet roster 56, got %d", len(cs.TargetRoster))
	}
	records := append([]WardrobeRecord(nil), cs.TargetRoster...)
	group := map[int32]int32{}
	seven := map[int32]int32{}
	for _, r := range cs.TargetRoster {
		if _, ok := group[r[slotCharacter]]; !ok {
			group[r[slotCharacter]] = r[slotGroup]
			seven[r[slotCharacter]] = r[slotConstant]
		}
	}
	for _, c := range cs.Importable {
		v := c.Record
		ch := v[slotCharacter]
		var nr WardrobeRecord
		nr[slotTextID] = v[slotTextID]
		nr[slotCharacter] = ch
		for j, f := range []int{slotBase, slotWet, slotWetAlt} {
			vidx := int(v[f])
			if vidx < 0 || vidx >= len(cs.SourceCharacterCatalog.Order) {
				return nil, fmt.Errorf("source charabase index %d", vidx)
			}
			tag := cs.SourceCharacterCatalog.Order[vidx]
			qidx, ok := cs.TargetCharacterCatalog.Index[tag]
			if !ok {
				return nil, fmt.Errorf("BaseTag %s missing from Quartet charabase", tag)
			}
			nr[[]int{slotBase, slotWet, slotWetAlt}[j]] = int32(qidx)
		}
		nr[slotGroup] = group[ch]
		nr[slotDLCFlag] = 0
		nr[slotProduct] = 0
		nr[slotConstant] = seven[ch]
		records = append(records, nr)
	}
	if len(records) > 127 {
		return nil, fmt.Errorf("roster %d exceeds imm8-safe bound", len(records))
	}
	return records, nil
}

type rosterRef struct {
	DispOff int
	Delta   uint32
}
type boundPatch struct {
	ImmOff int
	Old    byte
	Kind   string
}

func findRosterRefs(p *peImage, tableOff, count int) ([]rosterRef, error) {
	trva, ok := p.fileOffsetRVA(tableOff)
	if !ok {
		return nil, fmt.Errorf("roster offset 0x%x not in PE section", tableOff)
	}
	text, ok := p.section(".text")
	if !ok {
		return nil, fmt.Errorf("no .text")
	}
	lo, hi := int(text.Raw), int(text.Raw+text.RawSize)
	delta := int64(text.VAddr) - int64(text.Raw)
	span := uint32(count * rosterRecordSize)
	var out []rosterRef
	d := p.D
	for i := lo; i < hi-4; i++ {
		disp := int64(int32(binary.LittleEndian.Uint32(d[i : i+4])))
		tgt := uint32(int64(i+4) + delta + disp)
		if tgt < trva || tgt >= trva+span {
			continue
		}
		valid := false
		if i >= 3 {
			b := d[i-3 : i]
			if (b[0] == 0x48 || b[0] == 0x4c) && (b[1] == 0x8d || b[1] == 0x8b) && (b[2]&0xc7) == 0x05 {
				valid = true
			}
		}
		if i >= 2 {
			b := d[i-2 : i]
			if (b[0] == 0x8b || b[0] == 0x8d) && (b[1]&0xc7) == 0x05 {
				valid = true
			}
		}
		if valid {
			out = append(out, rosterRef{i, tgt - trva})
		}
	}
	return out, nil
}

type functionSpan struct{ A, B int }

func ripRelTarget(d []byte, i int, delta int64) (uint32, int, bool) {
	if i+7 > len(d) {
		return 0, 0, false
	}
	b := d[i : i+3]
	if (b[0] == 0x48 || b[0] == 0x4c) && (b[1] == 0x8d || b[1] == 0x8b) && (b[2]&0xc7) == 0x05 {
		return uint32(int64(i+7) + delta + int64(int32(binary.LittleEndian.Uint32(d[i+3:i+7])))), 7, true
	}
	if (b[0] == 0x8b || b[0] == 0x8d) && (b[1]&0xc7) == 0x05 {
		return uint32(int64(i+6) + delta + int64(int32(binary.LittleEndian.Uint32(d[i+2:i+6])))), 6, true
	}
	return 0, 0, false
}

var costumeArrays = []struct {
	RVA  uint32
	Size uint32
}{{0x0166fe00, 60}, {0x0166fe3c, 256}, {0x0166ff3c, 256}}

func costumeScope(p *peImage, rosterRVA, rosterSpan uint32) ([]functionSpan, error) {
	d := p.D
	text, ok := p.section(".text")
	if !ok {
		return nil, fmt.Errorf("no .text")
	}
	pdata, ok := p.section(".pdata")
	if !ok {
		return nil, fmt.Errorf("no .pdata")
	}
	lo, hi := int(text.Raw), int(text.Raw+text.RawSize)
	delta := int64(text.VAddr) - int64(text.Raw)
	var funcs []functionSpan
	for o := int(pdata.Raw); o+12 <= int(pdata.Raw+pdata.RawSize); o += 12 {
		beg := binary.LittleEndian.Uint32(d[o : o+4])
		end := binary.LittleEndian.Uint32(d[o+4 : o+8])
		if beg == 0 && end == 0 {
			break
		}
		funcs = append(funcs, functionSpan{int(int64(beg) - delta), int(int64(end) - delta)})
	}
	sort.Slice(funcs, func(i, j int) bool { return funcs[i].A < funcs[j].A })
	spanOf := func(off int) functionSpan {
		idx := sort.Search(len(funcs), func(i int) bool { return funcs[i].A > off }) - 1
		if idx >= 0 && funcs[idx].A <= off && off < funcs[idx].B {
			return funcs[idx]
		}
		a := off
		for a > lo+1 && !(d[a-1] == 0xcc && d[a-2] == 0xcc) {
			a--
		}
		b := off
		for b < hi-1 && !(d[b] == 0xcc && d[b+1] == 0xcc) {
			b++
		}
		return functionSpan{a, b}
	}
	isCostume := func(t uint32) bool {
		if t >= rosterRVA && t < rosterRVA+rosterSpan {
			return true
		}
		for _, a := range costumeArrays {
			if t >= a.RVA && t < a.RVA+a.Size {
				return true
			}
		}
		return false
	}
	seed := map[functionSpan]bool{}
	for i := lo; i < hi-7; {
		t, n, ok := ripRelTarget(d, i, delta)
		if ok {
			if isCostume(t) {
				seed[spanOf(i)] = true
			}
			i += n
		} else {
			i++
		}
	}
	starts := map[int]bool{}
	scope := map[functionSpan]bool{}
	for s := range seed {
		starts[s.A] = true
		scope[s] = true
	}
	for i := lo; i < hi-6; {
		var tgt int
		step := 1
		has := false
		switch {
		case d[i] == 0xe8 || d[i] == 0xe9:
			tgt = i + 5 + int(int32(binary.LittleEndian.Uint32(d[i+1:i+5])))
			step = 5
			has = true
		case d[i] == 0x0f && d[i+1] >= 0x80 && d[i+1] <= 0x8f:
			tgt = i + 6 + int(int32(binary.LittleEndian.Uint32(d[i+2:i+6])))
			step = 6
			has = true
		case d[i] >= 0x70 && d[i] <= 0x7f:
			tgt = i + 2 + int(int8(d[i+1]))
			step = 2
			has = true
		}
		if has && starts[tgt] {
			scope[spanOf(i)] = true
		}
		i += step
	}
	out := make([]functionSpan, 0, len(scope))
	for s := range scope {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].A < out[j].A })
	return out, nil
}
func findRosterBounds(p *peImage, rosterRVA uint32, rosterSpan uint32) ([]boundPatch, error) {
	scope, err := costumeScope(p, rosterRVA, rosterSpan)
	if err != nil {
		return nil, err
	}
	text, _ := p.section(".text")
	lo, hi := int(text.Raw), int(text.Raw+text.RawSize)
	inside := func(off int) bool {
		for _, s := range scope {
			if off >= s.A && off < s.B {
				return true
			}
		}
		return false
	}
	seen := map[int]boundPatch{}
	for _, spec := range []struct {
		imm  byte
		kind string
	}{{55, "index"}, {56, "count"}} {
		for i := lo; i < hi-5; i++ {
			if p.D[i] != 0x83 || p.D[i+1] < 0xf8 || p.D[i+1] > 0xff || p.D[i+2] != spec.imm {
				continue
			}
			jccLen := 0
			if p.D[i+3] >= 0x70 && p.D[i+3] <= 0x7f {
				jccLen = 1
			} else if i+5 < hi && p.D[i+3] == 0x0f && p.D[i+4] >= 0x80 && p.D[i+4] <= 0x8f {
				jccLen = 2
			}
			if jccLen > 0 && inside(i) {
				seen[i+2] = boundPatch{i + 2, spec.imm, spec.kind}
			}
		}
	}
	out := make([]boundPatch, 0, len(seen))
	for _, b := range seen {
		out = append(out, b)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ImmOff < out[j].ImmOff })
	return out, nil
}

func RewriteBR1Module(stock []byte, cs *WardrobePlan) ([]byte, *BinaryLayoutReport, error) {
	records, err := EncodeWardrobeTable(cs)
	if err != nil {
		return nil, nil, err
	}
	if len(records) != 122 {
		return nil, nil, fmt.Errorf("wardrobe reconstruction requires 122 total records (56 retained + 66 sourced), got %d", len(records))
	}
	p, err := parsePE(stock)
	if err != nil {
		return nil, nil, err
	}
	if _, ok := p.section(".b1cos"); ok {
		return nil, nil, fmt.Errorf("B1.dll already has .b1cos section")
	}
	refs, err := findRosterRefs(p, targetRosterOffset, 56)
	if err != nil {
		return nil, nil, err
	}
	oldRVA, ok := p.fileOffsetRVA(targetRosterOffset)
	if !ok {
		return nil, nil, fmt.Errorf("old roster offset not mapped")
	}
	bounds, err := findRosterBounds(p, oldRVA, 56*rosterRecordSize)
	if err != nil {
		return nil, nil, err
	}
	if len(refs) != 10 || len(bounds) != 36 {
		return nil, nil, fmt.Errorf("B1.dll signature mismatch: roster refs=%d/10 scoped bounds=%d/36", len(refs), len(bounds))
	}
	hdrEnd := p.SectOff + p.Nsec*40
	if hdrEnd+40 > int(p.SizeOfHeaders) {
		return nil, nil, fmt.Errorf("no PE header room for .b1cos")
	}
	blob := make([]byte, len(records)*rosterRecordSize)
	for i, r := range records {
		for j, v := range r {
			binary.LittleEndian.PutUint32(blob[i*48+j*4:i*48+j*4+4], uint32(v))
		}
	}
	vsize := uint32(len(blob))
	rawSize := alignU(vsize, p.FileAlign)
	var maxVA uint32
	for _, s := range p.sections {
		if e := s.VAddr + s.VSize; e > maxVA {
			maxVA = e
		}
	}
	newRVA := alignU(maxVA, p.SectAlign)
	newRaw := alignU(uint32(len(p.D)), p.FileAlign)
	if int(newRaw) > len(p.D) {
		p.D = append(p.D, make([]byte, int(newRaw)-len(p.D))...)
	}
	p.D = append(p.D, blob...)
	p.D = append(p.D, make([]byte, int(rawSize-vsize))...)
	hdr := make([]byte, 40)
	copy(hdr[:8], []byte(".b1cos"))
	binary.LittleEndian.PutUint32(hdr[8:12], vsize)
	binary.LittleEndian.PutUint32(hdr[12:16], newRVA)
	binary.LittleEndian.PutUint32(hdr[16:20], rawSize)
	binary.LittleEndian.PutUint32(hdr[20:24], newRaw)
	binary.LittleEndian.PutUint32(hdr[36:40], 0xC0000040)
	copy(p.D[hdrEnd:hdrEnd+40], hdr)
	binary.LittleEndian.PutUint16(p.D[p.NsecOff:p.NsecOff+2], uint16(p.Nsec+1))
	binary.LittleEndian.PutUint32(p.D[p.SizeOfImageOff:p.SizeOfImageOff+4], alignU(newRVA+vsize, p.SectAlign))
	text, _ := p.section(".text")
	tdelta := int64(text.VAddr) - int64(text.Raw)
	for _, r := range refs {
		disp := int64(newRVA+r.Delta) - int64(r.DispOff+4) - tdelta
		binary.LittleEndian.PutUint32(p.D[r.DispOff:r.DispOff+4], uint32(int32(disp)))
	}
	for _, b := range bounds {
		if b.Kind == "index" {
			p.D[b.ImmOff] = byte(len(records) - 1)
		} else {
			p.D[b.ImmOff] = byte(len(records))
		}
	}
	// Relocate the embedded 56-entry Dressing Room array to +0x400 and grow it to final count.
	if err := patchRelocatedCostumeArray(p.D, len(records)); err != nil {
		return nil, nil, err
	}
	extra, err := patchExtraCostumeBounds(p.D, len(records))
	if err != nil {
		return nil, nil, err
	}
	rep := &BinaryLayoutReport{RosterBefore: 56, RosterAfter: len(records), RosterRefs: len(refs), ScopedBounds: len(bounds), ExtraBounds: extra, SectionRVA: newRVA, SectionRaw: newRaw}
	// Final structural verification.
	p2, err := parsePE(p.D)
	if err != nil {
		return nil, nil, err
	}
	refs2, err := findRosterRefs(p2, int(newRaw), len(records))
	if err != nil {
		return nil, nil, err
	}
	if len(refs2) != 10 {
		return nil, nil, fmt.Errorf("post-patch .b1cos refs=%d, expected 10", len(refs2))
	}
	oldRefs, _ := findRosterRefs(p2, targetRosterOffset, 56)
	if len(oldRefs) != 0 {
		return nil, nil, fmt.Errorf("%d refs still point to old roster", len(oldRefs))
	}
	newSec, ok := p2.section(".b1cos")
	if !ok {
		return nil, nil, fmt.Errorf("post-patch .b1cos section missing")
	}
	if int(newSec.Raw)+len(blob) > len(p2.D) || !bytes.Equal(p2.D[int(newSec.Raw):int(newSec.Raw)+len(blob)], blob) {
		return nil, nil, fmt.Errorf("post-patch .b1cos payload differs from generated roster")
	}
	remainingBounds, err := findRosterBounds(p2, newRVA, uint32(len(records)*rosterRecordSize))
	if err != nil {
		return nil, nil, fmt.Errorf("post-patch scoped bound audit: %w", err)
	}
	if len(remainingBounds) != 0 {
		return nil, nil, fmt.Errorf("rewritten wardrobe scope still contains %d legacy 55/56 bounds", len(remainingBounds))
	}
	return p.D, rep, nil
}

type BinaryLayoutReport struct {
	RosterBefore int    `json:"roster_before"`
	RosterAfter  int    `json:"roster_after"`
	RosterRefs   int    `json:"roster_refs"`
	ScopedBounds int    `json:"scoped_bounds"`
	ExtraBounds  int    `json:"extra_bounds"`
	SectionRVA   uint32 `json:"section_rva"`
	SectionRaw   uint32 `json:"section_raw"`
}

func patchRelocatedCostumeArray(d []byte, count int) error {
	const oldBase = 0xe8
	const newBase = 0x400
	const oldAlloc = 0x400
	const rec = 12
	if count != 122 {
		return fmt.Errorf("relocation count must be 122, got %d", count)
	}
	alloc := (newBase + count*rec + 0xff) &^ 0xff
	type site struct {
		off      int
		old, new uint32
		name     string
	}
	sites := []site{{0x2bdf9, oldAlloc, uint32(alloc), "operator new"}, {0x2d3d1, 0x2a0, uint32(count * rec), "array end"}, {0x2d3ca, oldBase, newBase, "init base"}, {0x2d42e, oldBase + 4, newBase + 4, "fill cursor"}, {0x2db94, oldBase + 4, newBase + 4, "refill chara"}, {0x2dbef, oldBase + 4, newBase + 4, "refill all"}}
	for _, s := range sites {
		if s.off+4 > len(d) {
			return fmt.Errorf("relocation site %s outside DLL", s.name)
		}
		cur := binary.LittleEndian.Uint32(d[s.off : s.off+4])
		if cur != s.old && cur != s.new {
			return fmt.Errorf("relocation site %s 0x%x unexpected 0x%x", s.name, s.off, cur)
		}
		binary.LittleEndian.PutUint32(d[s.off:s.off+4], s.new)
	}
	off := 0x2d023
	old := []byte{0x48, 0x8d, 0x04, 0x40, 0x48, 0x8d, 0x40, 0x3a, 0x48, 0x8d, 0x04, 0x86}
	neu := []byte{0x48, 0x8d, 0x04, 0x40, 0x48, 0x8d, 0x84, 0x86, 0x00, 0x04, 0x00, 0x00}
	cur := d[off : off+len(old)]
	if !bytes.Equal(cur, old) && !bytes.Equal(cur, neu) {
		return fmt.Errorf("relocation pointer-vector sequence unexpected: %x", cur)
	}
	copy(cur, neu)
	return nil
}

func patchExtraCostumeBounds(d []byte, count int) (int, error) {
	newBound := byte(count - 1)
	if newBound > 0x7f {
		return 0, fmt.Errorf("extra bound %d exceeds imm8", newBound)
	}
	sites := []struct {
		off    int
		old    byte
		prefix []byte
	}{{0x2b224, 0x37, []byte{0x83, 0xbe, 0x48, 0x01, 0x00, 0x00}}}
	const getter = 0x2f5f0
	for i := 0; i+25 < len(d); {
		if d[i] == 0xe8 {
			t := i + 5 + int(int32(binary.LittleEndian.Uint32(d[i+1:i+5])))
			if t == getter {
				w := d[i+5 : i+25]
				for j := 0; j+4 <= len(w); j++ {
					if w[j] == 0x83 && w[j+1] == 0xf8 && (w[j+2] == 0x37 || w[j+2] == 0x38) && w[j+3] >= 0x70 && w[j+3] <= 0x7f {
						sites = append(sites, struct {
							off    int
							old    byte
							prefix []byte
						}{i + 5 + j + 2, w[j+2], []byte{0x83, 0xf8}})
						break
					}
				}
			}
			i += 5
		} else {
			i++
		}
	}
	if len(sites) != 18 {
		return 0, fmt.Errorf("extra bounds signature mismatch: model+field sites=%d, expected 18 (1+17)", len(sites))
	}
	for _, s := range sites {
		if s.off >= len(d) || s.off-len(s.prefix) < 0 || !bytes.Equal(d[s.off-len(s.prefix):s.off], s.prefix) {
			return 0, fmt.Errorf("extra bound prefix mismatch at 0x%x", s.off)
		}
		cur := d[s.off]
		if cur != s.old && cur != newBound {
			return 0, fmt.Errorf("extra bound unexpected at 0x%x: 0x%x", s.off, cur)
		}
		d[s.off] = newBound
	}
	return len(sites), nil
}
