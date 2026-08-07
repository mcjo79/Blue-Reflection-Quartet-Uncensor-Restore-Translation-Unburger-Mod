package br1rebuild

import (
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"testing"
)

func makeTestEARC(name string, member []byte) []byte {
	filenameUnits := uint32(8)
	entryBytes := 8 + 0x20 + int(filenameUnits)*0x10
	headerBytes := 0x1c
	memberOffset := headerBytes + entryBytes
	out := make([]byte, memberOffset+len(member))
	binary.LittleEndian.PutUint32(out[0:4], earcMagic)
	binary.LittleEndian.PutUint32(out[4:8], filenameUnits)
	binary.LittleEndian.PutUint32(out[8:12], uint32(len(member)))
	binary.LittleEndian.PutUint32(out[12:16], uint32(headerBytes))
	binary.LittleEndian.PutUint32(out[16:20], uint32(entryBytes))
	binary.LittleEndian.PutUint32(out[20:24], 1)
	binary.LittleEndian.PutUint32(out[24:28], 0)
	binary.LittleEndian.PutUint32(out[headerBytes:headerBytes+4], uint32(memberOffset))
	binary.LittleEndian.PutUint32(out[headerBytes+4:headerBytes+8], uint32(len(member)))
	copy(out[headerBytes+8:headerBytes+8+entryBytes-8], []byte(name))
	copy(out[memberOffset:], member)
	return out
}

func makeChunkedZlib(t *testing.T, plain []byte) []byte {
	t.Helper()
	var compressed bytes.Buffer
	writer := zlib.NewWriter(&compressed)
	if _, err := writer.Write(plain); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	var size [4]byte
	binary.LittleEndian.PutUint32(size[:], uint32(compressed.Len()))
	out.Write(size[:])
	out.Write(compressed.Bytes())
	out.Write([]byte{0, 0, 0, 0})
	return out.Bytes()
}

func TestSceneContainerRoundTrip(t *testing.T) {
	plain := bytes.Repeat([]byte("abcd"), 1000)
	encoded := makeChunkedZlib(t, plain)
	container, err := decodeSceneContainer(encoded)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(container.Plain, plain) || container.Kind != "chunked_zlib" {
		t.Fatalf("decode mismatch")
	}
	reencoded, err := encodeSceneContainer(container)
	if err != nil {
		t.Fatal(err)
	}
	again, err := decodeSceneContainer(reencoded)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(again.Plain, plain) {
		t.Fatal("round-trip mismatch")
	}
}

func TestEARCParserLocatesSingleMember(t *testing.T) {
	payload := makeTestEARC("example.bin", []byte{1, 2, 3, 4})
	members, err := parseEARCMembers(payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(members) != 1 || members[0].Name != "example.bin" || members[0].Size != 4 {
		t.Fatalf("unexpected members: %+v", members)
	}
}
