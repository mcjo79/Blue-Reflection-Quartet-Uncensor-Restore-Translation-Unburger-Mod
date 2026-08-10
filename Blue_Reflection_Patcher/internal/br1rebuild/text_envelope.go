package br1rebuild

import (
	"bytes"
	"encoding/binary"
	"fmt"
)

// EncryptedTextTool provides the BLUE REFLECTION text-envelope codec used by
// strcombineall.xml.e. The implementation is deterministic and self-contained.
type EncryptedTextTool struct{}

func (EncryptedTextTool) Validate() error { return nil }

var brTextSeeds = textEnvelopeSeeds{
	main:   [3]uint32{0x6947, 0xcb63, 0x7597},
	table:  [3]uint32{0xa829, 0xb047, 0x8af5},
	length: [3]uint32{0x1d, 0x13, 0x0b},
	fence:  0x0b23,
}

// secondLightA21TextSeeds is the A21 profile used by BLUE REFLECTION: Second Light
// for encrypted XML table siblings (for example stream.xml.e). It is deliberately
// separate from the original BLUE REFLECTION profile above: using BR seeds creates
// a self-consistent round trip in this package, but the Second Light runtime cannot
// decode that ciphertext.
var secondLightA21TextSeeds = textEnvelopeSeeds{
	main:   [3]uint32{0x6d3f, 0xcb53, 0x74b9},
	table:  [3]uint32{0xa83b, 0xb11d, 0x88a5},
	length: [3]uint32{0x1d, 0x13, 0x0b},
	fence:  0x0a31,
}

type textEnvelopeSeeds struct {
	main   [3]uint32
	table  [3]uint32
	length [3]uint32
	fence  uint16
}

type textPRNG struct {
	mul   uint32
	state uint32
}

func newTextPRNG(offset, state uint32) *textPRNG {
	return &textPRNG{mul: uint32(0x3b9a73c9) + offset, state: state}
}

func (r *textPRNG) u15() uint16 {
	r.state = r.mul*r.state + 0x2f09
	return uint16((r.state >> 16) & 0x7fff)
}

func (r *textPRNG) u16() uint16 {
	r.state = r.mul*r.state + 0x2f09
	return uint16(r.state >> 16)
}

func shuffleTextBits(buf []byte, sliceBytes int, rng *textPRNG, reverse bool) error {
	if sliceBytes <= 0 || sliceBytes*8 < 4 {
		return fmt.Errorf("invalid text bit-slice size")
	}
	for off := 0; off < len(buf); off += sliceBytes {
		span := minInt(sliceBytes, len(buf)-off)
		bitCount := span * 8
		available := make([]uint16, bitCount)
		order := make([]uint16, bitCount)
		for i := range available {
			available[i] = uint16(i)
		}
		for i := 0; i < bitCount; i++ {
			pick := int(rng.u15()) % (bitCount - i)
			order[i] = available[pick]
			copy(available[pick:], available[pick+1:bitCount-i])
		}
		if reverse {
			for i := 0; i < bitCount; i += 2 {
				a, b := order[i], order[i+1]
				ap, ab := int(a>>3), uint(a&7)
				bp, bb := int(b>>3), uint(b&7)
				av := (buf[off+ap] >> ab) & 1
				bv := (buf[off+bp] >> bb) & 1
				buf[off+ap] = (buf[off+ap] &^ (1 << ab)) | (bv << ab)
				buf[off+bp] = (buf[off+bp] &^ (1 << bb)) | (av << bb)
			}
			continue
		}
		for i := bitCount - 2; i >= 0; i -= 2 {
			a, b := order[i], order[i+1]
			ap, ab := int(a>>3), uint(a&7)
			bp, bb := int(b>>3), uint(b&7)
			av := (buf[off+ap] >> ab) & 1
			bv := (buf[off+bp] >> bb) & 1
			buf[off+ap] = (buf[off+ap] &^ (1 << ab)) | (bv << ab)
			buf[off+bp] = (buf[off+bp] &^ (1 << bb)) | (av << bb)
		}
	}
	return nil
}

func rotateTextBytes(buf []byte, seeds textEnvelopeSeeds, rng *textPRNG) {
	states := seeds.table
	index := 0
	cycleExtra := uint32(0)
	processed := uint32(0)
	for i := range buf {
		buf[i] ^= byte(rng.u16())
		processed++
		if processed >= seeds.length[index]+cycleExtra {
			states[index] = rng.state
			index++
			if index == len(states) {
				index = 0
				cycleExtra++
			}
			rng.state = states[index]
			processed = 0
		}
	}
}

func fenceTextWords(buf []byte, fence uint16, rng *textPRNG, reverse bool) error {
	if len(buf)%2 != 0 {
		return fmt.Errorf("text envelope word span is not aligned")
	}
	limit := uint32(fence) * 2
	for i := 0; i < len(buf); i += 2 {
		x := rng.u15()
		w := binary.BigEndian.Uint16(buf[i : i+2])
		if reverse {
			if uint32(x)%limit >= uint32(fence) {
				w ^= x
			}
			w -= x
		} else {
			w += x
			if uint32(x)%limit >= uint32(fence) {
				w ^= x
			}
		}
		binary.BigEndian.PutUint16(buf[i:i+2], w)
	}
	return nil
}

func textAdler32(buf []byte) uint32 {
	const mod = uint32(65521)
	a, b := uint32(1), uint32(0)
	for _, v := range buf {
		a = (a + uint32(v)) % mod
		b = (b + a) % mod
	}
	return b<<16 | a
}

func textChecksumSub(buf []byte) uint32 {
	var sum uint32
	for i := 0; i+4 <= len(buf); i += 4 {
		sum -= binary.BigEndian.Uint32(buf[i : i+4])
	}
	return sum
}

func textChecksumXOR(buf []byte) uint32 {
	var sum uint32
	for i := 0; i+4 <= len(buf); i += 4 {
		sum ^= ^binary.BigEndian.Uint32(buf[i : i+4])
	}
	return sum
}

func literalTextStream(src []byte) ([]byte, uint32, error) {
	if len(src) < 14 {
		return nil, 0, fmt.Errorf("text payload is too small")
	}
	rem := len(src) % 256
	blocks := (len(src) + 255) / 256
	mergeTail := blocks > 1 && rem > 0 && rem <= 13
	if mergeTail {
		blocks--
	}
	if blocks <= 0 {
		return nil, 0, fmt.Errorf("text payload cannot be represented")
	}
	bits := blocks * 5
	bitBytes := (bits + 7) / 8
	out := make([]byte, 12+bitBytes+4+len(src)+4+blocks)
	binary.BigEndian.PutUint32(out[0:4], uint32(len(src)))
	binary.BigEndian.PutUint32(out[4:8], uint32(bitBytes+4))
	binary.BigEndian.PutUint32(out[8:12], uint32(blocks))
	stream := out[12 : 12+bitBytes]
	bitPos := 0
	for i := 0; i < blocks; i++ {
		// The literal-copy opcode is the five-bit value 00111.
		for bit := 4; bit >= 0; bit-- {
			if (7>>bit)&1 != 0 {
				stream[bitPos/8] |= 1 << (7 - uint(bitPos%8))
			}
			bitPos++
		}
	}
	pos := 12 + bitBytes
	binary.BigEndian.PutUint32(out[pos:pos+4], uint32(len(src)))
	pos += 4
	copy(out[pos:pos+len(src)], src)
	pos += len(src)
	binary.BigEndian.PutUint32(out[pos:pos+4], uint32(blocks))
	pos += 4
	for i := 0; i < blocks-1; i++ {
		out[pos+i] = 242
	}
	last := rem
	if rem == 0 {
		last = 256
	} else if mergeTail {
		last += 256
	}
	out[pos+blocks-1] = byte(last - 14)
	return out, uint32(blocks), nil
}

func unwrapLiteralTextStream(src []byte) ([]byte, error) {
	if len(src) < 20 {
		return nil, fmt.Errorf("text stream header is truncated")
	}
	plainSize := int(binary.BigEndian.Uint32(src[0:4]))
	streamSpan := int(binary.BigEndian.Uint32(src[4:8]))
	blocks := int(binary.BigEndian.Uint32(src[8:12]))
	if plainSize < 0 || streamSpan < 4 || blocks <= 0 || 8+streamSpan+4 > len(src) {
		return nil, fmt.Errorf("text stream header is invalid")
	}
	bitBytes := streamSpan - 4
	stream := src[12 : 12+bitBytes]
	bitPos := 0
	for i := 0; i < blocks; i++ {
		var code byte
		for bit := 0; bit < 5; bit++ {
			if bitPos/8 >= len(stream) {
				return nil, fmt.Errorf("text stream opcode table is truncated")
			}
			code <<= 1
			code |= (stream[bitPos/8] >> (7 - uint(bitPos%8))) & 1
			bitPos++
		}
		if code != 7 {
			return nil, fmt.Errorf("unsupported text stream opcode %d", code)
		}
	}
	pos := 12 + bitBytes
	if pos+4 > len(src) {
		return nil, fmt.Errorf("text stream dictionary header is truncated")
	}
	dictSize := int(binary.BigEndian.Uint32(src[pos : pos+4]))
	pos += 4
	if dictSize < 0 || pos+dictSize+4 > len(src) {
		return nil, fmt.Errorf("text stream dictionary is truncated")
	}
	dict := src[pos : pos+dictSize]
	pos += dictSize
	lengthCount := int(binary.BigEndian.Uint32(src[pos : pos+4]))
	pos += 4
	if lengthCount != blocks || pos+lengthCount > len(src) {
		return nil, fmt.Errorf("text stream length table is invalid")
	}
	lengths := src[pos : pos+lengthCount]
	out := make([]byte, 0, plainSize)
	dictPos := 0
	for _, raw := range lengths {
		n := int(raw) + 14
		if dictPos+n > len(dict) {
			return nil, fmt.Errorf("text stream dictionary copy exceeds bounds")
		}
		out = append(out, dict[dictPos:dictPos+n]...)
		dictPos += n
	}
	if len(out) != plainSize || dictPos != dictSize {
		return nil, fmt.Errorf("text stream decoded length mismatch")
	}
	return out, nil
}

func encodeTextEnvelope(plain []byte, seeds textEnvelopeSeeds) ([]byte, error) {
	stream, codeBytes, err := literalTextStream(plain)
	if err != nil {
		return nil, err
	}
	working := uint32(len(plain))
	if need := uint32(len(stream)) + codeBytes; need > working {
		working = need
	}
	payload := append([]byte(nil), stream...)
	check2 := textAdler32(payload)
	begin := minInt(len(payload), 0x800)
	if err := shuffleTextBits(payload[:begin], 0x80, newTextPRNG(check2, seeds.main[2]), false); err != nil {
		return nil, err
	}
	check0 := textChecksumSub(payload)
	check1 := textChecksumXOR(payload)
	rotateTextBytes(payload, seeds, newTextPRNG(check2, seeds.table[0]))

	aligned := (len(payload) + 1 + 15) &^ 15
	main := make([]byte, aligned+16)
	copy(main, payload)
	main[len(payload)] = 0xff
	binary.BigEndian.PutUint32(main[aligned+4:aligned+8], check0)
	binary.BigEndian.PutUint32(main[aligned+8:aligned+12], check1)
	binary.BigEndian.PutUint32(main[aligned+12:aligned+16], check2)
	if err := fenceTextWords(main, seeds.fence, newTextPRNG(0, seeds.main[1]), false); err != nil {
		return nil, err
	}
	end := minInt(len(main), 0x800)
	if err := shuffleTextBits(main[len(main)-end:], 0x100, newTextPRNG(0, seeds.main[0]), false); err != nil {
		return nil, err
	}
	out := make([]byte, 16+len(main))
	binary.BigEndian.PutUint32(out[0:4], 2)
	binary.BigEndian.PutUint32(out[4:8], working)
	copy(out[16:], main)
	return out, nil
}

func decodeTextEnvelope(encoded []byte, seeds textEnvelopeSeeds) ([]byte, error) {
	if len(encoded) <= 32 || len(encoded)%4 != 0 {
		return nil, fmt.Errorf("text envelope size is invalid")
	}
	if binary.BigEndian.Uint32(encoded[0:4]) != 2 {
		return nil, fmt.Errorf("unsupported text envelope version")
	}
	working := binary.BigEndian.Uint32(encoded[4:8])
	if working == 0 || working > 256*1024*1024 {
		return nil, fmt.Errorf("text envelope workspace is invalid")
	}
	main := append([]byte(nil), encoded[16:]...)
	end := minInt(len(main), 0x800)
	if err := shuffleTextBits(main[len(main)-end:], 0x100, newTextPRNG(0, seeds.main[0]), true); err != nil {
		return nil, err
	}
	if err := fenceTextWords(main, seeds.fence, newTextPRNG(0, seeds.main[1]), true); err != nil {
		return nil, err
	}
	if len(main) < 16 {
		return nil, fmt.Errorf("text envelope footer is missing")
	}
	aligned := len(main) - 16
	footer := main[aligned:]
	check0 := binary.BigEndian.Uint32(footer[4:8])
	check1 := binary.BigEndian.Uint32(footer[8:12])
	check2 := binary.BigEndian.Uint32(footer[12:16])
	marker := aligned
	for marker > 0 && main[marker] != 0xff {
		marker--
	}
	if marker < 4 || main[marker] != 0xff {
		return nil, fmt.Errorf("text envelope end marker is missing")
	}
	payload := main[:marker]
	rotateTextBytes(payload, seeds, newTextPRNG(check2, seeds.table[0]))
	if textChecksumSub(payload) != check0 || textChecksumXOR(payload) != check1 {
		return nil, fmt.Errorf("text envelope checksum mismatch")
	}
	begin := minInt(len(payload), 0x800)
	if err := shuffleTextBits(payload[:begin], 0x80, newTextPRNG(check2, seeds.main[2]), true); err != nil {
		return nil, err
	}
	plain, err := unwrapLiteralTextStream(payload)
	if err != nil {
		return nil, err
	}
	if uint32(len(plain)) > working {
		return nil, fmt.Errorf("text envelope workspace is too small")
	}
	return plain, nil
}

func (EncryptedTextTool) DecryptA21(blob []byte) ([]byte, error) {
	return decodeTextEnvelope(blob, secondLightA21TextSeeds)
}

func (EncryptedTextTool) EncryptA21(blob []byte) ([]byte, error) {
	return encodeTextEnvelope(blob, secondLightA21TextSeeds)
}

func (EncryptedTextTool) EncryptBR(blob []byte, _ string) ([]byte, error) {
	return encodeTextEnvelope(blob, brTextSeeds)
}

func (EncryptedTextTool) VerifyBRRoundTrip(plain, encrypted []byte, stem string) error {
	got, err := decodeTextEnvelope(encrypted, brTextSeeds)
	if err != nil {
		return fmt.Errorf("text envelope verification failed for %s: %w", stem, err)
	}
	if !bytes.Equal(got, plain) {
		return fmt.Errorf("text envelope round-trip mismatch for %s", stem)
	}
	return nil
}
