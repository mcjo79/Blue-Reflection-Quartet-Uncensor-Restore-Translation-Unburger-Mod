package translationbundle

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strings"
	"unicode/utf8"
)

const maxEBMString = 2048

var ebmDuration1Lengths = []int{0, 2}
var ebmDuration2Lengths = []int{0, 1, 2}

type ebmMessage struct {
	Index                                            int
	Type, VoiceID, Unknown1, NameID, ExtraID, ExprID uint32
	Duration1                                        []uint32
	MsgID, Unknown2                                  uint32
	Text                                             string
	Duration2                                        []uint32
}

type ebmFile struct {
	SignedCount int32
	D1, D2      int
	Messages    []ebmMessage
	Extra       []byte
}

func parseEBMCandidate(data []byte, d1, d2 int) (*ebmFile, bool) {
	if len(data) < 4 {
		return nil, false
	}
	signed := int32(binary.LittleEndian.Uint32(data[:4]))
	count64 := int64(signed)
	if count64 < 0 {
		count64 = -count64
	}
	if count64 > 2_000_000 {
		return nil, false
	}
	count := int(count64)
	off := 4
	messages := make([]ebmMessage, 0, count)
	readU32 := func(at int) (uint32, bool) {
		if at < 0 || at+4 > len(data) {
			return 0, false
		}
		return binary.LittleEndian.Uint32(data[at : at+4]), true
	}
	for i := 0; i < count; i++ {
		words := 9 + d1
		if off+words*4 > len(data) {
			return nil, false
		}
		vals := make([]uint32, words)
		for j := 0; j < words; j++ {
			v, ok := readU32(off + j*4)
			if !ok {
				return nil, false
			}
			vals[j] = v
		}
		c := 0
		m := ebmMessage{Index: i}
		m.Type = vals[c]
		c++
		m.VoiceID = vals[c]
		c++
		m.Unknown1 = vals[c]
		c++
		m.NameID = vals[c]
		c++
		m.ExtraID = vals[c]
		c++
		m.ExprID = vals[c]
		c++
		m.Duration1 = append([]uint32(nil), vals[c:c+d1]...)
		c += d1
		m.MsgID = vals[c]
		c++
		m.Unknown2 = vals[c]
		c++
		msgLen := int(vals[c])
		if msgLen <= 0 || msgLen > maxEBMString {
			return nil, false
		}
		start := off + words*4
		end := start + msgLen
		durEnd := end + d2*4
		if durEnd > len(data) {
			return nil, false
		}
		raw := data[start:end]
		if len(raw) == 0 || raw[len(raw)-1] != 0 || bytes.IndexByte(raw[:len(raw)-1], 0) >= 0 || !utf8.Valid(raw[:len(raw)-1]) {
			return nil, false
		}
		m.Text = string(raw[:len(raw)-1])
		for j := 0; j < d2; j++ {
			v, ok := readU32(end + j*4)
			if !ok {
				return nil, false
			}
			m.Duration2 = append(m.Duration2, v)
		}
		off = durEnd
		messages = append(messages, m)
	}
	if (len(data)-off)%4 != 0 {
		return nil, false
	}
	return &ebmFile{SignedCount: signed, D1: d1, D2: d2, Messages: messages, Extra: append([]byte(nil), data[off:]...)}, true
}

func ebmScore(f *ebmFile) float64 {
	score := 0.0
	for _, m := range f.Messages {
		switch {
		case m.Type == 2:
			score += 10
		case m.Type == 0 || m.Type == 3:
			score += 8
		case m.Type <= 0x10:
			score += 2
		default:
			score -= 20
		}
		for _, item := range []struct {
			v, max uint32
			w      float64
		}{{m.VoiceID, 1_000_000, 1}, {m.NameID, 1_000_000, 1}, {m.ExtraID, 1_000_000, .5}, {m.ExprID, 1_000_000, .5}} {
			if item.v == math.MaxUint32 || item.v <= item.max {
				score += item.w
			} else {
				score -= 5 * item.w
			}
		}
		if m.Unknown1 == 0 || m.Unknown1 == 1 || m.Unknown1 == 2 || m.Unknown1 == math.MaxUint32 {
			score += 1
		} else if m.Unknown1 < 100_000 {
			score += .1
		} else {
			score -= 3
		}
		if m.Unknown2 == 0 || m.Unknown2 == 1 || m.Unknown2 == 2 || m.Unknown2 == math.MaxUint32 {
			score += 3
		} else if m.Unknown2 < 1_000 {
			score += .2
		} else {
			score -= 5
		}
		if m.MsgID != math.MaxUint32 && m.MsgID < 100_000_000 {
			score += 4
		} else if m.MsgID == math.MaxUint32 {
			score -= 1
		} else {
			score -= 5
		}
		bad := 0
		for _, r := range m.Text {
			if r < 32 && r != '\n' && r != '\r' && r != '\t' {
				bad++
			}
		}
		if bad == 0 {
			score += 6
		} else {
			score -= 20 * float64(bad)
		}
	}
	ids := make([]uint32, 0, len(f.Messages))
	for _, m := range f.Messages {
		if m.MsgID != math.MaxUint32 {
			ids = append(ids, m.MsgID)
		}
	}
	if len(ids) >= 2 {
		mono, step := 0, 0
		for i := 0; i+1 < len(ids); i++ {
			if ids[i+1] >= ids[i] {
				mono++
			}
			d := ids[i+1] - ids[i]
			if ids[i+1] >= ids[i] && (d == 0 || d == 1) {
				step++
			}
		}
		score += 6 * float64(mono) / float64(len(ids)-1)
		score += 4 * float64(step) / float64(len(ids)-1)
	}
	return score
}

func parseEBM(data []byte) (*ebmFile, error) {
	type candidate struct {
		score  float64
		d1, d2 int
		f      *ebmFile
	}
	var candidates []candidate
	for _, d1 := range ebmDuration1Lengths {
		for _, d2 := range ebmDuration2Lengths {
			if f, ok := parseEBMCandidate(data, d1, d2); ok {
				candidates = append(candidates, candidate{ebmScore(f), d1, d2, f})
			}
		}
	}
	if len(candidates) == 0 {
		return nil, fmt.Errorf("unsupported EBM record structure")
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		if candidates[i].score != candidates[j].score {
			return candidates[i].score > candidates[j].score
		}
		if candidates[i].d1 != candidates[j].d1 {
			return candidates[i].d1 < candidates[j].d1
		}
		return candidates[i].d2 < candidates[j].d2
	})
	return candidates[0].f, nil
}

func serializeEBM(f *ebmFile) ([]byte, error) {
	var out bytes.Buffer
	if err := binary.Write(&out, binary.LittleEndian, f.SignedCount); err != nil {
		return nil, err
	}
	for _, m := range f.Messages {
		raw := append([]byte(m.Text), 0)
		words := []uint32{m.Type, m.VoiceID, m.Unknown1, m.NameID, m.ExtraID, m.ExprID}
		words = append(words, m.Duration1...)
		words = append(words, m.MsgID, m.Unknown2, uint32(len(raw)))
		for _, v := range words {
			if err := binary.Write(&out, binary.LittleEndian, v); err != nil {
				return nil, err
			}
		}
		out.Write(raw)
		for _, v := range m.Duration2 {
			if err := binary.Write(&out, binary.LittleEndian, v); err != nil {
				return nil, err
			}
		}
	}
	out.Write(f.Extra)
	return out.Bytes(), nil
}

func metadataMatches(m ebmMessage, want *EBMMetadata) bool {
	if want == nil {
		return true
	}
	return m.Type == want.Type && m.VoiceID == want.VoiceID && m.Unknown1 == want.Unknown1 && m.NameID == want.NameID && m.ExtraID == want.ExtraID && m.ExprID == want.ExprID && m.MsgID == want.MsgID && m.Unknown2 == want.Unknown2
}

// structuralIdentityMatches deliberately excludes MsgID and text. Some Quartet
// targets preserve the source record order/role while assigning a different
// target-native message ID. These fields describe the stable record role and
// survive Translation text updates, so they can confirm a target-specific index
// without depending on any historical text hash or external patcher state.
func structuralIdentityMatches(m ebmMessage, want *EBMMetadata) bool {
	if want == nil {
		return false
	}
	return m.Type == want.Type && m.VoiceID == want.VoiceID && m.Unknown1 == want.Unknown1 && m.NameID == want.NameID && m.ExtraID == want.ExtraID && m.ExprID == want.ExprID && m.Unknown2 == want.Unknown2
}

func ebmStructuralSHAFromFile(f *ebmFile) string {
	h := sha256.New()
	write32 := func(v uint32) { _ = binary.Write(h, binary.LittleEndian, v) }
	write32(uint32(f.SignedCount))
	write32(uint32(f.D1))
	write32(uint32(f.D2))
	write32(uint32(len(f.Messages)))
	for i, m := range f.Messages {
		write32(uint32(i))
		for _, v := range []uint32{m.Type, m.VoiceID, m.Unknown1, m.NameID, m.ExtraID, m.ExprID} {
			write32(v)
		}
		write32(uint32(len(m.Duration1)))
		for _, v := range m.Duration1 {
			write32(v)
		}
		write32(m.MsgID)
		write32(m.Unknown2)
		write32(uint32(len(m.Duration2)))
		for _, v := range m.Duration2 {
			write32(v)
		}
	}
	write32(uint32(len(f.Extra)))
	_, _ = h.Write(f.Extra)
	return hex.EncodeToString(h.Sum(nil))
}

func ebmStructuralSHA(data []byte) (string, error) {
	f, err := parseEBM(data)
	if err != nil {
		return "", err
	}
	return ebmStructuralSHAFromFile(f), nil
}

func canonicalTargetBindingValid(f *ebmFile, records []Record, targetRecordCount int) bool {
	if targetRecordCount <= 0 || len(f.Messages) != targetRecordCount {
		return false
	}
	used := map[int]bool{}
	for _, r := range records {
		if r.TargetIndex < 0 || r.TargetIndex >= targetRecordCount || used[r.TargetIndex] {
			return false
		}
		used[r.TargetIndex] = true
	}
	return true
}

func applyEBM(data []byte, records []Record) ([]byte, int, int, error) {
	return applyEBMManaged(data, records, false, 0)
}

func applyEBMManaged(data []byte, records []Record, trustedManagedMember bool, targetRecordCount int) ([]byte, int, int, error) {
	f, err := parseEBM(data)
	if err != nil {
		return nil, 0, 0, err
	}
	canonicalTarget := canonicalTargetBindingValid(f, records, targetRecordCount)
	trustedTargetBinding := trustedManagedMember || canonicalTarget
	byID := map[uint32][]int{}
	for i, m := range f.Messages {
		byID[m.MsgID] = append(byID[m.MsgID], i)
	}
	used := map[int]bool{}
	already, rebase := 0, 0
	for _, r := range records {
		if r.MsgID == nil {
			return nil, 0, 0, fmt.Errorf("EBM patch has no msg_id: %s", r.LogicalID)
		}
		candidates := byID[*r.MsgID]
		idx := -1

		// The canonical target alignment is member-level data. It is safe to use
		// directly only when the complete target index set proves the expected
		// target record count, or when a prior game-root structural fingerprint
		// proves that this member still has the same non-text structure.
		if trustedTargetBinding {
			if r.TargetIndex < 0 || r.TargetIndex >= len(f.Messages) {
				return nil, 0, 0, fmt.Errorf("trusted EBM binding is out of range for %s", r.LogicalID)
			}
			idx = r.TargetIndex
		}

		if idx < 0 && r.TargetIndex >= 0 && r.TargetIndex < len(f.Messages) {
			targetTextHash := textHash(f.Messages[r.TargetIndex].Text)
			if targetTextHash == textHash(r.DesiredText) || (r.ExpectedTextSHA256 != "" && targetTextHash == r.ExpectedTextSHA256) {
				idx = r.TargetIndex
			}
		}
		if idx < 0 && r.TargetIndex >= 0 && r.TargetIndex < len(f.Messages) && structuralIdentityMatches(f.Messages[r.TargetIndex], r.Metadata) {
			idx = r.TargetIndex
		}
		if idx < 0 && len(candidates) == 1 {
			idx = candidates[0]
		}
		if idx < 0 && r.TargetIndex >= 0 && r.TargetIndex < len(f.Messages) && f.Messages[r.TargetIndex].MsgID == *r.MsgID {
			idx = r.TargetIndex
		}
		if idx < 0 && r.ExpectedTextSHA256 != "" {
			for _, i := range candidates {
				if textHash(f.Messages[i].Text) == r.ExpectedTextSHA256 {
					if idx >= 0 {
						idx = -2
						break
					}
					idx = i
				}
			}
		}
		if idx < 0 && r.Metadata != nil {
			metadataIdx := -1
			for _, i := range candidates {
				if metadataMatches(f.Messages[i], r.Metadata) {
					if metadataIdx >= 0 {
						metadataIdx = -2
						break
					}
					metadataIdx = i
				}
			}
			if metadataIdx >= 0 {
				idx = metadataIdx
			}
		}
		if idx < 0 {
			targetDetail := "out_of_range"
			if r.TargetIndex >= 0 && r.TargetIndex < len(f.Messages) {
				tm := f.Messages[r.TargetIndex]
				targetDetail = fmt.Sprintf("index=%d,msg_id=%d,text_sha256=%s", r.TargetIndex, tm.MsgID, textHash(tm.Text))
			}
			candidateDetails := make([]string, 0, len(candidates))
			for _, i := range candidates {
				candidateDetails = append(candidateDetails, fmt.Sprintf("%d:%s", i, textHash(f.Messages[i].Text)))
			}
			return nil, 0, 0, fmt.Errorf("cannot uniquely resolve EBM record %s (target=%s source_msg_id=%d candidates=[%s])", r.LogicalID, targetDetail, *r.MsgID, strings.Join(candidateDetails, ","))
		}
		if used[idx] {
			return nil, 0, 0, fmt.Errorf("multiple Translation records resolve to EBM index %d", idx)
		}
		used[idx] = true
		m := &f.Messages[idx]
		if textHash(m.Text) == textHash(r.DesiredText) {
			already++
			continue
		}
		if len(r.ExpectedTechnicalTokens) > 0 {
			actual := technicalTokenRE.FindAllString(m.Text, -1)
			if len(actual) != len(r.ExpectedTechnicalTokens) {
				return nil, 0, 0, fmt.Errorf("technical token count changed for %s", r.LogicalID)
			}
			for i := range actual {
				if actual[i] != r.ExpectedTechnicalTokens[i] {
					return nil, 0, 0, fmt.Errorf("technical token sequence changed for %s", r.LogicalID)
				}
			}
		}
		if r.ExpectedTextSHA256 != "" && textHash(m.Text) != r.ExpectedTextSHA256 {
			if !trustedTargetBinding && !metadataMatches(*m, r.Metadata) && !structuralIdentityMatches(*m, r.Metadata) {
				return nil, 0, 0, fmt.Errorf("EBM record structurally changed for %s", r.LogicalID)
			}
			rebase++
		}
		m.Text = r.DesiredText
	}
	out, err := serializeEBM(f)
	if err != nil {
		return nil, 0, 0, err
	}
	verify, err := parseEBM(out)
	if err != nil {
		return nil, 0, 0, err
	}
	if len(verify.Messages) != len(f.Messages) {
		return nil, 0, 0, fmt.Errorf("EBM round-trip record count changed")
	}
	if ebmStructuralSHAFromFile(verify) != ebmStructuralSHAFromFile(f) {
		return nil, 0, 0, fmt.Errorf("EBM non-text structure changed during Translation rewrite")
	}
	for idx := range used {
		if verify.Messages[idx].Text != f.Messages[idx].Text {
			return nil, 0, 0, fmt.Errorf("EBM round-trip text mismatch at %d", idx)
		}
	}
	return out, already, rebase, nil
}
