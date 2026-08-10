package quartetdlc

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

const (
	secondLightEBMMaxString = 0x1000
	secondLightEBMMaxType   = 0x10
)

type secondLightEBMMessage struct {
	Type      uint32
	VoiceID   uint32
	Unknown1  uint32
	NameID    uint32
	ExtraID   uint32
	ExprID    uint32
	Duration1 []uint32
	MessageID uint32
	Unknown2  uint32
	Text      []byte
	Duration2 []uint32
}

type secondLightEBMFile struct {
	MessageCount   int32
	Duration1Words int
	Duration2Words int
	Messages       []secondLightEBMMessage
	Trailer        []byte
}

func parseSecondLightEBM(data []byte) (*secondLightEBMFile, error) {
	if len(data) < 4 {
		return nil, fmt.Errorf("EBM is truncated")
	}
	var best *secondLightEBMFile
	bestTrailing := int(^uint(0) >> 1)
	for _, d1 := range []int{0, 2} {
		for _, d2 := range []int{0, 1, 2} {
			doc, used, ok := trySecondLightEBMShape(data, d1, d2)
			if !ok {
				continue
			}
			trailing := len(data) - used
			if best == nil || trailing < bestTrailing {
				best = doc
				bestTrailing = trailing
			}
		}
	}
	if best == nil {
		return nil, fmt.Errorf("unsupported EBM record shape")
	}
	return best, nil
}

func trySecondLightEBMShape(data []byte, d1, d2 int) (*secondLightEBMFile, int, bool) {
	rawCount := int32(binary.LittleEndian.Uint32(data[:4]))
	count := int64(rawCount)
	if count < 0 {
		count = -count
	}
	if count > 1_000_000 {
		return nil, 0, false
	}
	off := 4
	headerWords := 9 + d1
	messages := make([]secondLightEBMMessage, 0, int(count))
	for i := int64(0); i < count; i++ {
		end := off + headerWords*4
		if end > len(data) {
			return nil, 0, false
		}
		word := func(index int) uint32 { return binary.LittleEndian.Uint32(data[off+index*4:]) }
		if word(0) > secondLightEBMMaxType {
			return nil, 0, false
		}
		textLen := int(word(headerWords - 1))
		if textLen <= 0 || textLen > secondLightEBMMaxString || end+textLen > len(data) {
			return nil, 0, false
		}
		rawText := data[end : end+textLen]
		if rawText[len(rawText)-1] != 0 || bytes.IndexByte(rawText[:len(rawText)-1], 0) >= 0 {
			return nil, 0, false
		}
		msg := secondLightEBMMessage{
			Type: word(0), VoiceID: word(1), Unknown1: word(2), NameID: word(3), ExtraID: word(4), ExprID: word(5),
			Duration1: make([]uint32, d1), MessageID: word(6 + d1), Unknown2: word(7 + d1), Text: append([]byte(nil), rawText[:len(rawText)-1]...),
			Duration2: make([]uint32, d2),
		}
		for j := 0; j < d1; j++ {
			msg.Duration1[j] = word(6 + j)
		}
		off = end + textLen
		if off+d2*4 > len(data) {
			return nil, 0, false
		}
		for j := 0; j < d2; j++ {
			msg.Duration2[j] = binary.LittleEndian.Uint32(data[off+j*4:])
		}
		off += d2 * 4
		messages = append(messages, msg)
	}
	return &secondLightEBMFile{MessageCount: rawCount, Duration1Words: d1, Duration2Words: d2, Messages: messages, Trailer: append([]byte(nil), data[off:]...)}, off, true
}

func buildSecondLightEBM(doc *secondLightEBMFile) ([]byte, error) {
	var out bytes.Buffer
	if err := binary.Write(&out, binary.LittleEndian, doc.MessageCount); err != nil {
		return nil, err
	}
	for _, msg := range doc.Messages {
		if len(msg.Duration1) != doc.Duration1Words || len(msg.Duration2) != doc.Duration2Words {
			return nil, fmt.Errorf("EBM duration arity mismatch")
		}
		words := []uint32{msg.Type, msg.VoiceID, msg.Unknown1, msg.NameID, msg.ExtraID, msg.ExprID}
		words = append(words, msg.Duration1...)
		words = append(words, msg.MessageID, msg.Unknown2, uint32(len(msg.Text)+1))
		for _, v := range words {
			if err := binary.Write(&out, binary.LittleEndian, v); err != nil {
				return nil, err
			}
		}
		out.Write(msg.Text)
		out.WriteByte(0)
		for _, v := range msg.Duration2 {
			if err := binary.Write(&out, binary.LittleEndian, v); err != nil {
				return nil, err
			}
		}
	}
	out.Write(doc.Trailer)
	return out.Bytes(), nil
}

type secondLightEBMSignature struct{ Type, NameID, VoiceID uint32 }

func secondLightMessageSignature(m secondLightEBMMessage) secondLightEBMSignature {
	return secondLightEBMSignature{Type: m.Type, NameID: m.NameID, VoiceID: m.VoiceID}
}

func secondLightBlankText(v []byte) bool {
	trimmed := bytes.TrimSpace(v)
	return len(trimmed) == 0 || bytes.Equal(trimmed, []byte("-"))
}

func secondLightEBMHeaderEqual(a, b secondLightEBMMessage) bool {
	if a.Type != b.Type || a.VoiceID != b.VoiceID || a.Unknown1 != b.Unknown1 || a.NameID != b.NameID || a.ExtraID != b.ExtraID || a.ExprID != b.ExprID || a.MessageID != b.MessageID || a.Unknown2 != b.Unknown2 {
		return false
	}
	if len(a.Duration1) != len(b.Duration1) || len(a.Duration2) != len(b.Duration2) {
		return false
	}
	for i := range a.Duration1 {
		if a.Duration1[i] != b.Duration1[i] {
			return false
		}
	}
	for i := range a.Duration2 {
		if a.Duration2[i] != b.Duration2[i] {
			return false
		}
	}
	return true
}

func alignSecondLightMessages(target, source []secondLightEBMMessage) [][2]int {
	if len(target) == len(source) {
		pairs := make([][2]int, len(target))
		for i := range target {
			pairs[i] = [2]int{i, i}
		}
		return pairs
	}
	// Longest-common-subsequence anchors by stable structural signature. Equal-sized
	// gaps between anchors are paired positionally so harmless target-side ID churn
	// does not hide restorable text.
	n, m := len(target), len(source)
	dp := make([][]int, n+1)
	for i := range dp {
		dp[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if secondLightMessageSignature(target[i]) == secondLightMessageSignature(source[j]) {
				dp[i][j] = dp[i+1][j+1] + 1
			} else if dp[i+1][j] >= dp[i][j+1] {
				dp[i][j] = dp[i+1][j]
			} else {
				dp[i][j] = dp[i][j+1]
			}
		}
	}
	anchors := [][2]int{}
	for i, j := 0, 0; i < n && j < m; {
		if secondLightMessageSignature(target[i]) == secondLightMessageSignature(source[j]) {
			anchors = append(anchors, [2]int{i, j})
			i++
			j++
		} else if dp[i+1][j] >= dp[i][j+1] {
			i++
		} else {
			j++
		}
	}
	result := [][2]int{}
	ti, si := 0, 0
	for _, a := range append(anchors, [2]int{n, m}) {
		if a[0]-ti == a[1]-si {
			for k := 0; k < a[0]-ti; k++ {
				result = append(result, [2]int{ti + k, si + k})
			}
		}
		if a[0] < n && a[1] < m {
			result = append(result, a)
		}
		ti, si = a[0]+1, a[1]+1
	}
	return result
}

func restoreSecondLightEBMText(target, source []byte) ([]byte, int, error) {
	td, err := parseSecondLightEBM(target)
	if err != nil {
		return nil, 0, err
	}
	sd, err := parseSecondLightEBM(source)
	if err != nil {
		return nil, 0, err
	}
	roundTrip, err := buildSecondLightEBM(td)
	if err != nil {
		return nil, 0, err
	}
	if !bytes.Equal(roundTrip, target) {
		return nil, 0, fmt.Errorf("target EBM does not round-trip byte-identically")
	}
	before := append([]secondLightEBMMessage(nil), td.Messages...)
	changed := 0
	for _, pair := range alignSecondLightMessages(td.Messages, sd.Messages) {
		t, s := &td.Messages[pair[0]], sd.Messages[pair[1]]
		// Match standalone exactly whenever Quartet blanked the target. Some
		// Japanese-only events are empty in standalone but were replaced by a
		// literal dash in Quartet; copying only non-blank source strings would
		// leave that censorship/removal artefact visible. Real Quartet-authored
		// text is never touched because the guard is on the target value.
		if secondLightBlankText(t.Text) && !bytes.Equal(t.Text, s.Text) {
			t.Text = append([]byte(nil), s.Text...)
			changed++
		}
	}
	if changed == 0 {
		return target, 0, nil
	}
	out, err := buildSecondLightEBM(td)
	if err != nil {
		return nil, 0, err
	}
	verify, err := parseSecondLightEBM(out)
	if err != nil {
		return nil, 0, err
	}
	if verify.MessageCount != td.MessageCount || verify.Duration1Words != td.Duration1Words || verify.Duration2Words != td.Duration2Words || !bytes.Equal(verify.Trailer, td.Trailer) || len(verify.Messages) != len(before) {
		return nil, 0, fmt.Errorf("EBM structural metadata drift")
	}
	for i := range before {
		if !secondLightEBMHeaderEqual(before[i], verify.Messages[i]) {
			return nil, 0, fmt.Errorf("EBM message metadata drift at %d", i)
		}
	}
	return out, changed, nil
}
