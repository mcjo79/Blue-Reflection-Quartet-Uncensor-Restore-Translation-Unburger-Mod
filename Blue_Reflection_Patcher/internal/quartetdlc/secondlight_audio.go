package quartetdlc

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const (
	ktsrHeaderBytes          = 0x40
	ktsrSoundSection         = uint32(0x368C88BD)
	ktsrStreamSection        = uint32(0x70CBCCC5)
	ktsrOldStreamPayload     = uint32(0x7D43D038)
	ktsrQuartetStreamPayload = uint32(0xD71F3A79)
	ktsrQuartetBuildStamp    = uint32(0x063BFA31)
	ktsrStreamDataSection    = uint32(0x15F4D409)
)

var secondLightQuartetAudioKey = []byte{0x7a, 0x23, 0xeb, 0x7d, 0x77, 0x2a, 0x22}
var secondLightCollabTags = []string{"SEED_BGM_046", "SEED_BGM_047", "SEED_BGM_048", "SEED_BGM_049", "SEED_BGM_050", "SEED_BGM_051"}
var secondLightStubHashes = map[uint32]bool{0x250C912D: true, 0x138F97AE: true, 0x02129E2F: true, 0xF095A4B0: true, 0x95AC0F86: true, 0x842F1607: true}

type secondLightAudioAudit struct{ ConvertedSections, EncryptedStreams, StubsRemoved int }

type ktsrSection struct {
	pos   int
	magic uint32
	size  int
	blob  []byte
}

func parseKTSRSections(data []byte) ([]ktsrSection, error) {
	if len(data) < ktsrHeaderBytes {
		return nil, fmt.Errorf("KTSR bank is truncated")
	}
	out := []ktsrSection{}
	pos := ktsrHeaderBytes
	for pos+8 <= len(data) {
		magic := binary.LittleEndian.Uint32(data[pos:])
		size := int(binary.LittleEndian.Uint32(data[pos+4:]))
		if size == 0 || pos+size > len(data) {
			break
		}
		out = append(out, ktsrSection{pos: pos, magic: magic, size: size, blob: data[pos : pos+size]})
		pos += size
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("KTSR bank has no parseable sections")
	}
	return out, nil
}

func setKTSRHeaderKey(header []byte, key []byte) ([]byte, error) {
	if len(header) < ktsrHeaderBytes {
		return nil, fmt.Errorf("KTSR header truncated")
	}
	if len(key) > 7 {
		return nil, fmt.Errorf("KTSR inline key too long")
	}
	out := append([]byte(nil), header...)
	out[0x20] = byte(len(key))
	copy(out[0x21:0x28], make([]byte, 7))
	copy(out[0x21:], key)
	return out, nil
}

func convertSecondLightASBin(data []byte) ([]byte, int, error) {
	sections, err := parseKTSRSections(data)
	if err != nil {
		return nil, 0, err
	}
	header := append([]byte(nil), data[:ktsrHeaderBytes]...)
	binary.LittleEndian.PutUint32(header[0x0c:], ktsrQuartetBuildStamp)
	header, err = setKTSRHeaderKey(header, secondLightQuartetAudioKey)
	if err != nil {
		return nil, 0, err
	}
	var body bytes.Buffer
	for _, s := range sections {
		var converted []byte
		switch s.magic {
		case ktsrSoundSection:
			converted, err = convertSecondLightSoundSection(s.blob)
		case ktsrStreamSection:
			converted, err = convertSecondLightStreamSection(s.blob)
		default:
			return nil, 0, fmt.Errorf("unsupported Second Light KTSR section 0x%08x", s.magic)
		}
		if err != nil {
			return nil, 0, err
		}
		body.Write(converted)
	}
	total := ktsrHeaderBytes + body.Len()
	binary.LittleEndian.PutUint32(header[0x18:], uint32(total))
	binary.LittleEndian.PutUint32(header[0x1c:], uint32(total))
	return append(header, body.Bytes()...), len(sections), nil
}

func convertSecondLightSoundSection(src []byte) ([]byte, error) {
	if len(src) != 240 {
		return nil, fmt.Errorf("unsupported Second Light sound record size %d", len(src))
	}
	p24 := binary.LittleEndian.Uint32(src[0x24:])
	p28 := binary.LittleEndian.Uint32(src[0x28:])
	if p24 != 0x40 || p28 != 0x30 {
		return nil, fmt.Errorf("unsupported Second Light sound record layout 0x24=%x 0x28=%x", p24, p28)
	}
	out := append([]byte(nil), src[:0x30]...)
	out = append(out, src[0x40:]...)
	binary.LittleEndian.PutUint32(out[4:], uint32(len(out)))
	out[0x0d] = 0
	binary.LittleEndian.PutUint32(out[0x24:], p24-0x10)
	binary.LittleEndian.PutUint32(out[0x28:], 0)
	v := binary.LittleEndian.Uint32(out[0x30:])
	if v < 0x10 {
		return nil, fmt.Errorf("invalid sound internal offset")
	}
	binary.LittleEndian.PutUint32(out[0x30:], v-0x10)
	return out, nil
}

func convertSecondLightStreamSection(src []byte) ([]byte, error) {
	if len(src) < 0x40 {
		return nil, fmt.Errorf("Second Light stream section is truncated")
	}
	sid := binary.LittleEndian.Uint32(src[8:])
	flags := binary.LittleEndian.Uint32(src[0x0c:]) & 0xffffff00
	sub := -1
	for i := 0x10; i+8 <= len(src); i += 4 {
		if binary.LittleEndian.Uint32(src[i:]) == ktsrOldStreamPayload {
			sub = i
			break
		}
	}
	if sub < 0 {
		return nil, fmt.Errorf("legacy stream payload chunk not found")
	}
	if binary.LittleEndian.Uint32(src[sub+4:]) != 0x40 || sub+0x40 > len(src) {
		return nil, fmt.Errorf("legacy stream payload chunk has unexpected size")
	}
	pay := make([]uint32, 17)
	for i := 0; i < 14; i++ {
		pay[i] = binary.LittleEndian.Uint32(src[sub+8+i*4:])
	}
	pay[14] = 0x3f800000
	pay[15] = 1
	pay[16] = (pay[12] + 7) &^ 7
	out := make([]byte, 112)
	binary.LittleEndian.PutUint32(out[0:], ktsrStreamSection)
	binary.LittleEndian.PutUint32(out[4:], 112)
	binary.LittleEndian.PutUint32(out[8:], sid)
	binary.LittleEndian.PutUint32(out[0x0c:], flags)
	binary.LittleEndian.PutUint32(out[0x10:], 1)
	binary.LittleEndian.PutUint32(out[0x14:], 0x1c)
	binary.LittleEndian.PutUint32(out[0x18:], 0)
	binary.LittleEndian.PutUint32(out[0x1c:], 0x20)
	binary.LittleEndian.PutUint32(out[0x20:], ktsrQuartetStreamPayload)
	binary.LittleEndian.PutUint32(out[0x24:], 0x4c)
	for i, v := range pay {
		binary.LittleEndian.PutUint32(out[0x28+i*4:], v)
	}
	return out, nil
}

func routeSecondLightCollabAudio(data []byte) ([]byte, int, error) {
	re := regexp.MustCompile(`<sound\s+hash="0x[0-9A-Fa-f]+"\s+tag="([^"]*)"\s+file="([^"]*)"`)
	wanted := map[string]bool{}
	for _, t := range secondLightCollabTags {
		wanted[t] = true
	}
	seen := map[string]bool{}
	matches := re.FindAllSubmatchIndex(data, -1)
	var out bytes.Buffer
	last := 0
	changed := 0
	for _, m := range matches {
		tag := string(data[m[2]:m[3]])
		if !wanted[tag] {
			continue
		}
		bank := string(data[m[4]:m[5]])
		seen[tag] = true
		out.Write(data[last:m[4]])
		switch strings.ToUpper(bank) {
		case "DUMMY":
			out.WriteString("Legacy_BGM")
			changed++
		case "LEGACY_BGM":
			out.Write(data[m[4]:m[5]])
		default:
			return nil, 0, fmt.Errorf("unexpected audio bank %q for %s", bank, tag)
		}
		last = m[5]
	}
	if len(seen) != len(wanted) {
		missing := []string{}
		for t := range wanted {
			if !seen[t] {
				missing = append(missing, t)
			}
		}
		return nil, 0, fmt.Errorf("Second Light stream table missing collaboration tags: %s", strings.Join(missing, ","))
	}
	if changed == 0 {
		return data, 0, nil
	}
	out.Write(data[last:])
	return out.Bytes(), changed, nil
}

func stripSecondLightStubSounds(data []byte) ([]byte, int, error) {
	sections, err := parseKTSRSections(data)
	if err != nil {
		return nil, 0, err
	}
	header := append([]byte(nil), data[:ktsrHeaderBytes]...)
	var body bytes.Buffer
	dropped := map[uint32]bool{}
	for _, s := range sections {
		if s.magic == ktsrSoundSection && len(s.blob) > 0x0c {
			h := binary.LittleEndian.Uint32(s.blob[8:])
			if secondLightStubHashes[h] && s.blob[0x0c] == 0 {
				dropped[h] = true
				continue
			}
		}
		body.Write(s.blob)
	}
	if len(dropped) != len(secondLightStubHashes) {
		return nil, 0, fmt.Errorf("expected %d collaboration stubs, found %d", len(secondLightStubHashes), len(dropped))
	}
	total := ktsrHeaderBytes + body.Len()
	binary.LittleEndian.PutUint32(header[0x18:], uint32(total))
	binary.LittleEndian.PutUint32(header[0x1c:], uint32(total))
	return append(header, body.Bytes()...), len(dropped), nil
}

type secondLightBlowfish struct {
	p [18]uint32
	s [4][256]uint32
}

func newSecondLightBlowfish(key []byte) (*secondLightBlowfish, error) {
	if len(key) < 4 || len(key) > 56 {
		return nil, fmt.Errorf("Blowfish key length %d outside 4..56", len(key))
	}
	raw, err := base64.StdEncoding.DecodeString(secondLightBlowfishTablesB64)
	if err != nil || len(raw) != 4168 {
		return nil, fmt.Errorf("embedded Blowfish tables are invalid")
	}
	b := &secondLightBlowfish{}
	for i := 0; i < 18; i++ {
		b.p[i] = binary.LittleEndian.Uint32(raw[i*4:])
	}
	base := 72
	for box := 0; box < 4; box++ {
		for i := 0; i < 256; i++ {
			b.s[box][i] = binary.LittleEndian.Uint32(raw[base+box*1024+i*4:])
		}
	}
	for n := 0; n < 18; n++ {
		var v uint32
		for m := 0; m < 4; m++ {
			v = (v << 8) | uint32(key[(n*4+m)%len(key)])
		}
		b.p[n] ^= v
	}
	var l, r uint32
	for n := 0; n < 18; n += 2 {
		l, r = b.encryptBlock(l, r)
		b.p[n], b.p[n+1] = l, r
	}
	for box := 0; box < 4; box++ {
		for n := 0; n < 256; n += 2 {
			l, r = b.encryptBlock(l, r)
			b.s[box][n], b.s[box][n+1] = l, r
		}
	}
	return b, nil
}
func (b *secondLightBlowfish) f(x uint32) uint32 {
	return ((b.s[0][byte(x>>24)] + b.s[1][byte(x>>16)]) ^ b.s[2][byte(x>>8)]) + b.s[3][byte(x)]
}
func (b *secondLightBlowfish) encryptBlock(l, r uint32) (uint32, uint32) {
	for n := 0; n < 16; n++ {
		l ^= b.p[n]
		r ^= b.f(l)
		l, r = r, l
	}
	l, r = r, l
	r ^= b.p[16]
	l ^= b.p[17]
	return l, r
}
func (b *secondLightBlowfish) decryptBlock(l, r uint32) (uint32, uint32) {
	for n := 17; n > 1; n-- {
		l ^= b.p[n]
		r ^= b.f(l)
		l, r = r, l
	}
	l, r = r, l
	r ^= b.p[1]
	l ^= b.p[0]
	return l, r
}
func (b *secondLightBlowfish) transform(data []byte, encrypt bool) []byte {
	out := append([]byte(nil), data...)
	n := len(data) - (len(data) % 8)
	for off := 0; off < n; off += 8 {
		l := binary.BigEndian.Uint32(data[off:])
		r := binary.BigEndian.Uint32(data[off+4:])
		if encrypt {
			l, r = b.encryptBlock(l, r)
		} else {
			l, r = b.decryptBlock(l, r)
		}
		binary.BigEndian.PutUint32(out[off:], l)
		binary.BigEndian.PutUint32(out[off+4:], r)
	}
	return out
}

func parseSecondLightSTBinSections(data []byte) ([]struct{ pos, size, id, payoff, paysz int }, error) {
	out := []struct{ pos, size, id, payoff, paysz int }{}
	for pos := ktsrHeaderBytes; pos+0x20 <= len(data); {
		magic := binary.LittleEndian.Uint32(data[pos:])
		size := int(binary.LittleEndian.Uint32(data[pos+4:]))
		if magic != ktsrStreamDataSection || size == 0 || pos+size > len(data) {
			break
		}
		payoff := int(binary.LittleEndian.Uint32(data[pos+0x0c:]))
		paysz := int(binary.LittleEndian.Uint32(data[pos+0x10:]))
		if payoff < 0 || paysz < 0 || payoff+paysz > size {
			return nil, fmt.Errorf("invalid KTSR stream payload bounds")
		}
		out = append(out, struct{ pos, size, id, payoff, paysz int }{pos, size, int(binary.LittleEndian.Uint32(data[pos+8:])), payoff, paysz})
		pos += size
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("KTSR stream bank has no sections")
	}
	return out, nil
}

func encryptSecondLightSTBin(data []byte, key []byte) ([]byte, int, error) {
	bf, err := newSecondLightBlowfish(key)
	if err != nil {
		return nil, 0, err
	}
	sections, err := parseSecondLightSTBinSections(data)
	if err != nil {
		return nil, 0, err
	}
	out := append([]byte(nil), data...)
	binary.LittleEndian.PutUint32(out[0x0c:], ktsrQuartetBuildStamp)
	for _, s := range sections {
		o := s.pos + s.payoff
		copy(out[o:o+s.paysz], bf.transform(data[o:o+s.paysz], true))
	}
	header, err := setKTSRHeaderKey(out[:ktsrHeaderBytes], key)
	if err != nil {
		return nil, 0, err
	}
	copy(out[:ktsrHeaderBytes], header)
	return out, len(sections), nil
}
func decryptSecondLightSTBin(data []byte) ([]byte, int, error) {
	if len(data) < ktsrHeaderBytes {
		return nil, 0, fmt.Errorf("KTSR stream bank truncated")
	}
	n := int(data[0x20])
	if n == 0 {
		return append([]byte(nil), data...), 0, nil
	}
	if 0x21+n > 0x28 {
		return nil, 0, fmt.Errorf("invalid KTSR header key length")
	}
	key := append([]byte(nil), data[0x21:0x21+n]...)
	bf, err := newSecondLightBlowfish(key)
	if err != nil {
		return nil, 0, err
	}
	sections, err := parseSecondLightSTBinSections(data)
	if err != nil {
		return nil, 0, err
	}
	out := append([]byte(nil), data...)
	for _, s := range sections {
		o := s.pos + s.payoff
		copy(out[o:o+s.paysz], bf.transform(data[o:o+s.paysz], false))
	}
	header, _ := setKTSRHeaderKey(out[:ktsrHeaderBytes], nil)
	copy(out[:ktsrHeaderBytes], header)
	return out, len(sections), nil
}

func buildSecondLightAudio(sourceSound, targetSound, workspace string, overrides map[string]string) (map[string]string, secondLightAudioAudit, error) {
	audit := secondLightAudioAudit{}
	outputs := map[string]string{}
	srcAS, err := os.ReadFile(filepath.Join(sourceSound, "Le0000_BGM.ktsl2asbin"))
	if err != nil {
		return nil, audit, err
	}
	asOut, n, err := convertSecondLightASBin(srcAS)
	if err != nil {
		return nil, audit, err
	}
	audit.ConvertedSections = n
	asPath := filepath.Join(workspace, "Legacy_BGM.ktsl2asbin")
	if err := os.WriteFile(asPath, asOut, 0o644); err != nil {
		return nil, audit, err
	}
	outputs["Data/B4/x64/Sound/Legacy_BGM.ktsl2asbin"] = asPath
	srcST, err := os.ReadFile(filepath.Join(sourceSound, "Le0000_BGM.ktsl2stbin"))
	if err != nil {
		return nil, audit, err
	}
	stOut, n, err := encryptSecondLightSTBin(srcST, secondLightQuartetAudioKey)
	if err != nil {
		return nil, audit, err
	}
	plain, _, err := decryptSecondLightSTBin(stOut)
	if err != nil {
		return nil, audit, err
	}
	expected := append([]byte(nil), srcST...)
	binary.LittleEndian.PutUint32(expected[0x0c:], ktsrQuartetBuildStamp)
	if !bytes.Equal(plain, expected) {
		return nil, audit, fmt.Errorf("Second Light stream-bank encryption round-trip mismatch")
	}
	audit.EncryptedStreams = n
	stPath := filepath.Join(workspace, "Legacy_BGM.ktsl2stbin")
	if err := os.WriteFile(stPath, stOut, 0o644); err != nil {
		return nil, audit, err
	}
	outputs["Data/B4/x64/Sound/Legacy_BGM.ktsl2stbin"] = stPath
	rel := "Data/B4/x64/Sound/Seed_BGM.ktsl2asbin"
	seedInput := filepath.Join(targetSound, "Seed_BGM.ktsl2asbin")
	if p := overrides[rel]; strings.TrimSpace(p) != "" {
		seedInput = p
	}
	seed, err := os.ReadFile(seedInput)
	if err != nil {
		return nil, audit, err
	}
	seedOut, n, err := stripSecondLightStubSounds(seed)
	if err != nil {
		return nil, audit, err
	}
	audit.StubsRemoved = n
	seedPath := filepath.Join(workspace, "Seed_BGM.ktsl2asbin")
	if err := os.WriteFile(seedPath, seedOut, 0o644); err != nil {
		return nil, audit, err
	}
	outputs[rel] = seedPath
	return outputs, audit, nil
}
