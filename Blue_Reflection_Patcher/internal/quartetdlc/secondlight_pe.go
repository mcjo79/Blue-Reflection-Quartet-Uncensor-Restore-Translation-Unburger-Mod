package quartetdlc

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

const (
	secondLightCauldronBadPath  = "Saves/ui_CMN/seed_dev/uil_fm_remove_obstruction.xml"
	secondLightCauldronGoodPath = "Saves/B4/ui_CMN/seed_dev/uil_fm_remove_obstruction.xml"
)

type pe64Section struct {
	name    string
	vaddr   uint32
	vsize   uint32
	rawPtr  uint32
	rawSize uint32
}

type pe64Image struct {
	imageBase uint64
	sections  []pe64Section
}

func parsePE64Image(data []byte) (pe64Image, error) {
	if len(data) < 0x40 || string(data[:2]) != "MZ" {
		return pe64Image{}, fmt.Errorf("B4.dll is not a PE image")
	}
	peOff := int(binary.LittleEndian.Uint32(data[0x3c:]))
	if peOff < 0 || peOff+24 > len(data) || string(data[peOff:peOff+4]) != "PE\x00\x00" {
		return pe64Image{}, fmt.Errorf("B4.dll has invalid PE header")
	}
	coff := peOff + 4
	sectionCount := int(binary.LittleEndian.Uint16(data[coff+2:]))
	optionalSize := int(binary.LittleEndian.Uint16(data[coff+16:]))
	opt := coff + 20
	if optionalSize < 0x20 || opt+optionalSize > len(data) {
		return pe64Image{}, fmt.Errorf("B4.dll optional header is truncated")
	}
	if binary.LittleEndian.Uint16(data[opt:]) != 0x20b {
		return pe64Image{}, fmt.Errorf("B4.dll is not PE32+")
	}
	if optionalSize < 0x20 {
		return pe64Image{}, fmt.Errorf("B4.dll optional header too short")
	}
	imageBase := binary.LittleEndian.Uint64(data[opt+0x18:])
	secOff := opt + optionalSize
	if sectionCount <= 0 || secOff+sectionCount*40 > len(data) {
		return pe64Image{}, fmt.Errorf("B4.dll section table is invalid")
	}
	sections := make([]pe64Section, 0, sectionCount)
	for i := 0; i < sectionCount; i++ {
		off := secOff + i*40
		rawName := data[off : off+8]
		if z := bytes.IndexByte(rawName, 0); z >= 0 {
			rawName = rawName[:z]
		}
		sections = append(sections, pe64Section{
			name:    string(rawName),
			vsize:   binary.LittleEndian.Uint32(data[off+8:]),
			vaddr:   binary.LittleEndian.Uint32(data[off+12:]),
			rawSize: binary.LittleEndian.Uint32(data[off+16:]),
			rawPtr:  binary.LittleEndian.Uint32(data[off+20:]),
		})
	}
	return pe64Image{imageBase: imageBase, sections: sections}, nil
}

func (p pe64Image) fileOffsetToVA(off int) (uint64, bool) {
	for _, s := range p.sections {
		start := int(s.rawPtr)
		end := start + int(s.rawSize)
		if off >= start && off < end {
			return p.imageBase + uint64(s.vaddr) + uint64(off-start), true
		}
	}
	return 0, false
}

func countByteDiff(a, b []byte) int {
	if len(a) != len(b) {
		return -1
	}
	n := 0
	for i := range a {
		if a[i] != b[i] {
			n++
		}
	}
	return n
}

func findUniqueCString(data []byte, s string) (int, error) {
	needle := append([]byte(s), 0)
	first := bytes.Index(data, needle)
	if first < 0 {
		return -1, fmt.Errorf("B4.dll missing string %q", s)
	}
	if bytes.Index(data[first+1:], needle) >= 0 {
		return -1, fmt.Errorf("B4.dll contains multiple copies of string %q", s)
	}
	return first, nil
}

type pePointerRef struct {
	off     int
	section string
}

func findPEPointerRefs(pe pe64Image, data []byte, target uint64) []pePointerRef {
	packed := make([]byte, 8)
	binary.LittleEndian.PutUint64(packed, target)
	refs := []pePointerRef{}
	for _, sec := range pe.sections {
		start := int(sec.rawPtr)
		end := start + int(sec.rawSize)
		if start < 0 || end > len(data) || start > end {
			continue
		}
		block := data[start:end]
		for at := 0; ; {
			i := bytes.Index(block[at:], packed)
			if i < 0 {
				break
			}
			i += at
			// Match the reference proof: only naturally aligned qword slots count.
			if i%8 == start%8 {
				refs = append(refs, pePointerRef{off: start + i, section: sec.name})
			}
			at = i + 1
		}
	}
	return refs
}

func fixSecondLightCauldronPointer(data []byte) ([]byte, bool, error) {
	pe, err := parsePE64Image(data)
	if err != nil {
		return nil, false, err
	}
	badOff, err := findUniqueCString(data, secondLightCauldronBadPath)
	if err != nil {
		return nil, false, err
	}
	goodOff, err := findUniqueCString(data, secondLightCauldronGoodPath)
	if err != nil {
		return nil, false, err
	}
	badVA, ok := pe.fileOffsetToVA(badOff)
	if !ok {
		return nil, false, fmt.Errorf("B4.dll cauldron source string is outside mapped PE sections")
	}
	goodVA, ok := pe.fileOffsetToVA(goodOff)
	if !ok {
		return nil, false, fmt.Errorf("B4.dll cauldron replacement string is outside mapped PE sections")
	}

	badRefs := findPEPointerRefs(pe, data, badVA)
	goodRefs := findPEPointerRefs(pe, data, goodVA)
	if len(badRefs) == 0 {
		// The proven patched state has two adjacent .data qwords pointing to the
		// target-native B4/ path: the legitimate pointer and the corrected one.
		if len(goodRefs) == 2 && goodRefs[0].section == ".data" && goodRefs[1].section == ".data" && absInt(goodRefs[0].off-goodRefs[1].off) == 8 {
			return append([]byte(nil), data...), false, nil
		}
		return nil, false, fmt.Errorf("B4.dll cauldron pointer is neither clean nor the proven patched state")
	}
	if len(badRefs) != 1 {
		return nil, false, fmt.Errorf("B4.dll expected one cauldron pointer reference, found %d", len(badRefs))
	}
	if badRefs[0].section != ".data" {
		return nil, false, fmt.Errorf("B4.dll cauldron pointer sits in %s, expected .data", badRefs[0].section)
	}
	out := append([]byte(nil), data...)
	binary.LittleEndian.PutUint64(out[badRefs[0].off:], goodVA)
	if got := countByteDiff(data, out); got != 1 {
		return nil, false, fmt.Errorf("B4.dll cauldron fix expected one byte difference, got %d", got)
	}
	postBad := findPEPointerRefs(pe, out, badVA)
	postGood := findPEPointerRefs(pe, out, goodVA)
	if len(postBad) != 0 || len(postGood) != 2 || postGood[0].section != ".data" || postGood[1].section != ".data" || absInt(postGood[0].off-postGood[1].off) != 8 {
		return nil, false, fmt.Errorf("B4.dll cauldron fix did not produce the proven two-pointer state")
	}
	return out, true, nil
}

func absInt(v int) int {
	if v < 0 {
		return -v
	}
	return v
}
