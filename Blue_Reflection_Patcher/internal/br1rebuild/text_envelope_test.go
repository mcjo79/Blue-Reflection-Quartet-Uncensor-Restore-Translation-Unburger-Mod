package br1rebuild

import (
	"bytes"
	"testing"
)

func TestBRTextEnvelopeRoundTrip(t *testing.T) {
	cases := [][]byte{
		bytes.Repeat([]byte("<str String_No=\"393339\" Text=\"Bikini\"/>\r\n"), 31),
		bytes.Repeat([]byte("0123456789abcdef"), 64),
		bytes.Repeat([]byte{0, 1, 2, 3, 4, 5, 6, 7}, 97),
	}
	for _, size := range []int{14, 15, 241, 242, 255, 256, 257, 269, 270, 271, 511, 512, 513, 2047, 2048, 2049} {
		plain := make([]byte, size)
		for i := range plain {
			plain[i] = byte((i*37 + size*11) & 0xff)
		}
		cases = append(cases, plain)
	}
	for i, plain := range cases {
		enc, err := encodeBRTextEnvelope(plain)
		if err != nil {
			t.Fatalf("case %d encode: %v", i, err)
		}
		dec, err := decodeBRTextEnvelope(enc)
		if err != nil {
			t.Fatalf("case %d decode: %v", i, err)
		}
		if !bytes.Equal(dec, plain) {
			t.Fatalf("case %d mismatch", i)
		}
		enc2, err := encodeBRTextEnvelope(plain)
		if err != nil {
			t.Fatalf("case %d second encode: %v", i, err)
		}
		if !bytes.Equal(enc, enc2) {
			t.Fatalf("case %d encoding is not deterministic", i)
		}
	}
}
