package br1rebuild

import (
	"bytes"
	"compress/gzip"
	"compress/zlib"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	bathroomContainerMember = `\data\b1\x64\field\s89_s_hinako_bath_room_01\s89_s_hinako_bath_room_01.elixir.gz`
	bathroomInnerName       = "s89_s_hinako_bath_room_01_river.bin"
	bathroomInnerBefore     = "2683b4e50507995c0ee779a3683b875fc76aa0fa1f63e17eff377c0731911a89"
	bathroomInnerAfter      = "062e39915e7df9e632c5bcaba592f9598572135efad8fa8aea24175f9bf06d7a"
	earcMagic               = 0x45415243
	earcHeaderBytes         = 0x1c
)

var bathroomWordEdits = []struct {
	Offset int
	Before [4]byte
	After  [4]byte
}{
	{60, [4]byte{0x00, 0x00, 0x00, 0x40}, [4]byte{0x00, 0x00, 0x20, 0x42}},
	{168, [4]byte{0x71, 0x9d, 0x35, 0x3f}, [4]byte{0x21, 0x6e, 0x9e, 0x3e}},
	{172, [4]byte{0x61, 0x52, 0x43, 0x3f}, [4]byte{0xa4, 0x39, 0xb7, 0x3e}},
	{176, [4]byte{0xcd, 0x04, 0x63, 0x3f}, [4]byte{0x9a, 0x99, 0x19, 0x3f}},
	{208, [4]byte{0x9f, 0x57, 0x94, 0x42}, [4]byte{0x00, 0x00, 0x88, 0x42}},
	{224, [4]byte{0x9f, 0x57, 0x94, 0x42}, [4]byte{0x00, 0x00, 0x88, 0x42}},
	{240, [4]byte{0x9f, 0x57, 0x94, 0x42}, [4]byte{0x00, 0x00, 0x88, 0x42}},
}

type RestorationLayerAudit struct {
	ArchiveRelativePath string `json:"archive_relative_path"`
	ContainerMember     string `json:"container_member"`
	InnerMember         string `json:"inner_member"`
	InnerBytes          int    `json:"inner_bytes"`
	InnerSHA256Before   string `json:"inner_sha256_before"`
	InnerSHA256After    string `json:"inner_sha256_after"`
	EditedWords         int    `json:"edited_words"`
	ContainerKind       string `json:"container_kind"`
	OutputSHA256        string `json:"output_sha256"`
}

type encodedContainer struct {
	Kind       string
	Plain      []byte
	ChunkSizes []int
}

func decodeSceneContainer(data []byte) (encodedContainer, error) {
	if len(data) >= 2 && data[0] == 0x1f && data[1] == 0x8b {
		reader, err := gzip.NewReader(bytes.NewReader(data))
		if err != nil {
			return encodedContainer{}, err
		}
		plain, err := io.ReadAll(reader)
		closeErr := reader.Close()
		if err != nil {
			return encodedContainer{}, err
		}
		if closeErr != nil {
			return encodedContainer{}, closeErr
		}
		return encodedContainer{Kind: "gzip", Plain: plain}, nil
	}
	var plain bytes.Buffer
	var chunks []int
	cursor := 0
	for {
		if cursor+4 > len(data) {
			return encodedContainer{}, fmt.Errorf("truncated chunk length")
		}
		size := int(binary.LittleEndian.Uint32(data[cursor : cursor+4]))
		cursor += 4
		if size == 0 {
			if cursor != len(data) || len(chunks) == 0 {
				return encodedContainer{}, fmt.Errorf("invalid chunked container terminator")
			}
			return encodedContainer{Kind: "chunked_zlib", Plain: plain.Bytes(), ChunkSizes: chunks}, nil
		}
		if size < 2 || cursor+size > len(data) {
			return encodedContainer{}, fmt.Errorf("invalid compressed chunk size %d", size)
		}
		reader, err := zlib.NewReader(bytes.NewReader(data[cursor : cursor+size]))
		if err != nil {
			return encodedContainer{}, fmt.Errorf("open compressed chunk: %w", err)
		}
		chunk, err := io.ReadAll(reader)
		closeErr := reader.Close()
		if err != nil {
			return encodedContainer{}, err
		}
		if closeErr != nil {
			return encodedContainer{}, closeErr
		}
		plain.Write(chunk)
		chunks = append(chunks, len(chunk))
		cursor += size
	}
}

func encodeSceneContainer(container encodedContainer) ([]byte, error) {
	switch container.Kind {
	case "gzip":
		var out bytes.Buffer
		writer, err := gzip.NewWriterLevel(&out, gzip.BestCompression)
		if err != nil {
			return nil, err
		}
		writer.Header.ModTime = time.Unix(0, 0)
		writer.Header.OS = 255
		if _, err := writer.Write(container.Plain); err != nil {
			return nil, err
		}
		if err := writer.Close(); err != nil {
			return nil, err
		}
		return out.Bytes(), nil
	case "chunked_zlib":
		var out bytes.Buffer
		position := 0
		for _, plainSize := range container.ChunkSizes {
			if plainSize < 0 || position+plainSize > len(container.Plain) {
				return nil, fmt.Errorf("invalid decoded chunk layout")
			}
			var compressed bytes.Buffer
			writer, err := zlib.NewWriterLevel(&compressed, zlib.BestCompression)
			if err != nil {
				return nil, err
			}
			if _, err := writer.Write(container.Plain[position : position+plainSize]); err != nil {
				return nil, err
			}
			if err := writer.Close(); err != nil {
				return nil, err
			}
			if compressed.Len() > int(^uint32(0)) {
				return nil, fmt.Errorf("compressed chunk too large")
			}
			var size [4]byte
			binary.LittleEndian.PutUint32(size[:], uint32(compressed.Len()))
			out.Write(size[:])
			out.Write(compressed.Bytes())
			position += plainSize
		}
		if position != len(container.Plain) {
			return nil, fmt.Errorf("decoded chunk layout does not cover payload")
		}
		out.Write([]byte{0, 0, 0, 0})
		return out.Bytes(), nil
	default:
		return nil, fmt.Errorf("unsupported scene container kind %q", container.Kind)
	}
}

type earcMember struct {
	Name   string
	Offset int
	Size   int
	Index  int
}

func decodeEARCName(raw []byte) string {
	if at := bytes.IndexByte(raw, 0); at >= 0 {
		raw = raw[:at]
	}
	return string(raw)
}

func parseEARCMembers(payload []byte) ([]earcMember, error) {
	if len(payload) < earcHeaderBytes {
		return nil, fmt.Errorf("scene archive header is truncated")
	}
	magic := binary.LittleEndian.Uint32(payload[0:4])
	filenameUnits := binary.LittleEndian.Uint32(payload[4:8])
	payloadBytes := binary.LittleEndian.Uint32(payload[8:12])
	headerBytes := binary.LittleEndian.Uint32(payload[12:16])
	tableBytes := binary.LittleEndian.Uint32(payload[16:20])
	count := binary.LittleEndian.Uint32(payload[20:24])
	if magic != earcMagic || headerBytes != earcHeaderBytes || filenameUnits > 0x100 || count > 100000 {
		return nil, fmt.Errorf("unsupported scene archive layout")
	}
	entryBytes := 8 + 0x20 + int(filenameUnits)*0x10
	if uint64(tableBytes) != uint64(count)*uint64(entryBytes) || uint64(headerBytes)+uint64(tableBytes)+uint64(payloadBytes) != uint64(len(payload)) {
		return nil, fmt.Errorf("scene archive size table mismatch")
	}
	members := make([]earcMember, 0, count)
	nameBytes := entryBytes - 8
	for index := 0; index < int(count); index++ {
		at := int(headerBytes) + index*entryBytes
		offset := int(binary.LittleEndian.Uint32(payload[at : at+4]))
		size := int(binary.LittleEndian.Uint32(payload[at+4 : at+8]))
		if offset < 0 || size < 0 || offset+size > len(payload) {
			return nil, fmt.Errorf("scene archive member %d is outside payload", index)
		}
		members = append(members, earcMember{Name: decodeEARCName(payload[at+8 : at+8+nameBytes]), Offset: offset, Size: size, Index: index})
	}
	return members, nil
}

func digestBytes(data []byte) string {
	h := sha256.Sum256(data)
	return hex.EncodeToString(h[:])
}

func patchBathroomDescriptor(containerBytes []byte) ([]byte, RestorationLayerAudit, error) {
	container, err := decodeSceneContainer(containerBytes)
	if err != nil {
		return nil, RestorationLayerAudit{}, err
	}
	members, err := parseEARCMembers(container.Plain)
	if err != nil {
		return nil, RestorationLayerAudit{}, err
	}
	matches := make([]earcMember, 0, 1)
	for _, member := range members {
		if strings.EqualFold(member.Name, bathroomInnerName) {
			matches = append(matches, member)
		}
	}
	if len(matches) != 1 {
		return nil, RestorationLayerAudit{}, fmt.Errorf("expected one %s member, found %d", bathroomInnerName, len(matches))
	}
	member := matches[0]
	if member.Size != 252 {
		return nil, RestorationLayerAudit{}, fmt.Errorf("unexpected descriptor size %d", member.Size)
	}
	current := append([]byte(nil), container.Plain[member.Offset:member.Offset+member.Size]...)
	before := digestBytes(current)
	if before == bathroomInnerAfter {
		return containerBytes, RestorationLayerAudit{ContainerMember: bathroomContainerMember, InnerMember: bathroomInnerName, InnerBytes: member.Size, InnerSHA256Before: before, InnerSHA256After: before, EditedWords: 0, ContainerKind: container.Kind}, nil
	}
	if before != bathroomInnerBefore {
		return nil, RestorationLayerAudit{}, fmt.Errorf("descriptor fingerprint is not recognized: %s", before)
	}
	for _, edit := range bathroomWordEdits {
		if edit.Offset+4 > len(current) || !bytes.Equal(current[edit.Offset:edit.Offset+4], edit.Before[:]) {
			return nil, RestorationLayerAudit{}, fmt.Errorf("descriptor word gate failed at 0x%x", edit.Offset)
		}
		copy(current[edit.Offset:edit.Offset+4], edit.After[:])
	}
	after := digestBytes(current)
	if after != bathroomInnerAfter {
		return nil, RestorationLayerAudit{}, fmt.Errorf("descriptor output fingerprint mismatch: %s", after)
	}
	copy(container.Plain[member.Offset:member.Offset+member.Size], current)
	encoded, err := encodeSceneContainer(container)
	if err != nil {
		return nil, RestorationLayerAudit{}, err
	}
	check, err := decodeSceneContainer(encoded)
	if err != nil || !bytes.Equal(check.Plain, container.Plain) {
		return nil, RestorationLayerAudit{}, fmt.Errorf("scene container round-trip verification failed")
	}
	return encoded, RestorationLayerAudit{ContainerMember: bathroomContainerMember, InnerMember: bathroomInnerName, InnerBytes: member.Size, InnerSHA256Before: before, InnerSHA256After: after, EditedWords: len(bathroomWordEdits), ContainerKind: container.Kind}, nil
}

func ApplyApprovedRestoration(workDir string, candidates map[string]string, progress BuildProgressFunc) (RestorationLayerAudit, map[string]string, error) {
	const archiveRelative = "Data/PACK10_03.PAK"
	source, ok := candidates[archiveRelative]
	if !ok {
		return RestorationLayerAudit{}, nil, fmt.Errorf("restoration base candidate missing: %s", archiveRelative)
	}
	archive, err := OpenA22(source)
	if err != nil {
		return RestorationLayerAudit{}, nil, err
	}
	entry, ok := archive.Find(bathroomContainerMember)
	if !ok {
		archive.Close()
		return RestorationLayerAudit{}, nil, fmt.Errorf("restoration container member missing: %s", bathroomContainerMember)
	}
	encoded, err := archive.Read(entry)
	archive.Close()
	if err != nil {
		return RestorationLayerAudit{}, nil, err
	}
	patched, audit, err := patchBathroomDescriptor(encoded)
	if err != nil {
		return audit, nil, err
	}
	audit.ArchiveRelativePath = archiveRelative
	result := map[string]string{}
	for k, v := range candidates {
		result[k] = v
	}
	if audit.EditedWords == 0 {
		hash, _, _ := hashPath(source)
		audit.OutputSHA256 = hash
		return audit, result, nil
	}
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return audit, nil, err
	}
	out := filepath.Join(workDir, "restoration-field-content.bin")
	progressFn := byteProgress(nil)
	if progress != nil {
		progressFn = func(phase, name string, done, total int64) {
			progress(BuildProgress{Phase: "restoration_" + phase, CurrentFile: archiveRelative + ": " + name, CurrentDone: done, CurrentTotal: total})
		}
	}
	replacements := map[string]ArchiveInput{bathroomContainerMember: MemoryEntry{Data: patched}}
	if _, err := RewriteA22(source, out, ArchiveEdits{Replacements: replacements}, progressFn); err != nil {
		return audit, nil, err
	}
	verify, err := AuditA22Rewrite(source, out, nil, replacements, progressFn)
	if err != nil {
		return audit, nil, err
	}
	if len(verify.Problems) > 0 {
		return audit, nil, fmt.Errorf("restoration archive audit failed: %s", strings.Join(verify.Problems, "; "))
	}
	finalArchive, err := OpenA22(out)
	if err != nil {
		return audit, nil, err
	}
	finalEntry, ok := finalArchive.Find(bathroomContainerMember)
	if !ok {
		finalArchive.Close()
		return audit, nil, fmt.Errorf("restoration output lost selected container")
	}
	finalEncoded, err := finalArchive.Read(finalEntry)
	finalArchive.Close()
	if err != nil {
		return audit, nil, err
	}
	_, finalAudit, err := patchBathroomDescriptor(finalEncoded)
	if err != nil {
		return audit, nil, fmt.Errorf("restoration output verification: %w", err)
	}
	if finalAudit.InnerSHA256After != bathroomInnerAfter {
		return audit, nil, fmt.Errorf("restoration output descriptor was not preserved")
	}
	hash, _, err := hashPath(out)
	if err != nil {
		return audit, nil, err
	}
	audit.OutputSHA256 = hash
	result[archiveRelative] = out
	return audit, result, nil
}
