package br1rebuild

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
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
		enc, err := encodeTextEnvelope(plain, brTextSeeds)
		if err != nil {
			t.Fatalf("case %d encode: %v", i, err)
		}
		dec, err := decodeTextEnvelope(enc, brTextSeeds)
		if err != nil {
			t.Fatalf("case %d decode: %v", i, err)
		}
		if !bytes.Equal(dec, plain) {
			t.Fatalf("case %d mismatch", i)
		}
		enc2, err := encodeTextEnvelope(plain, brTextSeeds)
		if err != nil {
			t.Fatalf("case %d second encode: %v", i, err)
		}
		if !bytes.Equal(enc, enc2) {
			t.Fatalf("case %d encoding is not deterministic", i)
		}
	}
}

func TestA21TextEnvelopeProfileIsDistinctFromBR(t *testing.T) {
	plain := bytes.Repeat([]byte(`<elem id="STREAM_DLC" route="Legacy_BGM"/>\r\n`), 37)
	tool := EncryptedTextTool{}

	a21, err := tool.EncryptA21(plain)
	if err != nil {
		t.Fatalf("A21 encode: %v", err)
	}
	br, err := tool.EncryptBR(plain, "stream.xml")
	if err != nil {
		t.Fatalf("BR encode: %v", err)
	}
	if bytes.Equal(a21, br) {
		t.Fatal("A21 and BR ciphertext unexpectedly match; seed profiles are not separated")
	}
	vector := sha256.Sum256(a21)
	if got := hex.EncodeToString(vector[:]); got != "75415548e2fa3c7f28b7bbe91f3633ded3de52281cb2141435a0f02c781badc5" {
		t.Fatalf("A21 fixed-vector hash drifted: %s", got)
	}
	got, err := tool.DecryptA21(a21)
	if err != nil {
		t.Fatalf("A21 decode: %v", err)
	}
	if !bytes.Equal(got, plain) {
		t.Fatal("A21 round trip mismatch")
	}
	if _, err := tool.DecryptA21(br); err == nil {
		t.Fatal("A21 decoder accepted BR-seeded ciphertext")
	}
}
