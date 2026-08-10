package br1rebuild

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/assetkey"
	"local/blue-reflection-patcher/internal/workspace"
	"local/blue-reflection-patcher/internal/zstddec"
)

var sourceAssetsV3Magic = [8]byte{'U', 'N', 'B', 'A', 'S', '3', 0, 1}

const (
	sourceAssetsV3HeaderSize = 64
	sourceAssetsV3ChunkSize  = 1 << 20
)

type sourceAssetV3Object struct {
	ID          string `json:"id"`
	Path        string `json:"path"`
	Size        int64  `json:"size"`
	SHA256      string `json:"sha256"`
	Offset      int64  `json:"offset"`
	StoredBytes int64  `json:"stored_bytes"`
	Compression string `json:"compression"`
	Encryption  string `json:"encryption"`
}

type sourceAssetV3Manifest struct {
	Type                   string                `json:"type"`
	ContainerFormatVersion int                   `json:"container_format_version"`
	SourceManifest         SourceAssetManifest   `json:"source_manifest"`
	Objects                []sourceAssetV3Object `json:"objects"`
}

type sourceAssetsV3Header struct {
	ManifestOffset uint64
	ManifestLength uint64
	ManifestNonce  [12]byte
	ObjectCount    uint32
}

func isSourceAssetV3(path string) (bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer f.Close()
	var got [8]byte
	if _, err := io.ReadFull(f, got[:]); err != nil {
		return false, err
	}
	return got == sourceAssetsV3Magic, nil
}

func sourceAssetsAEAD() (cipher.AEAD, error) {
	key, err := assetkey.Key()
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func packageSourceAssetImageV3(stage, outputPath string, manifest SourceAssetManifest) error {
	if _, err := exec.LookPath("zstd"); err != nil {
		return fmt.Errorf("zstd is required to build encrypted .unburger-assets v3: %w", err)
	}
	aead, err := sourceAssetsAEAD()
	if err != nil {
		return fmt.Errorf("assets encryption key: %w", err)
	}
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return err
	}
	f, err := os.OpenFile(outputPath, os.O_CREATE|os.O_TRUNC|os.O_RDWR, 0o600)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = f.Close()
		if !ok {
			_ = os.Remove(outputPath)
		}
	}()
	if _, err := f.Write(make([]byte, sourceAssetsV3HeaderSize)); err != nil {
		return err
	}

	objects := make([]sourceAssetV3Object, 0, len(manifest.ImageFiles))
	files := append([]SourceAssetImageFile(nil), manifest.ImageFiles...)
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	for _, item := range files {
		path := filepath.Join(stage, filepath.FromSlash(item.Path))
		obj, err := writeSourceAssetV3Object(f, path, item, aead)
		if err != nil {
			return err
		}
		objects = append(objects, obj)
	}

	containerManifest := sourceAssetV3Manifest{
		Type:                   "unburger_assets_encrypted_container",
		ContainerFormatVersion: 3,
		SourceManifest:         manifest,
		Objects:                objects,
	}
	plain, err := json.Marshal(containerManifest)
	if err != nil {
		return err
	}
	var nonce [12]byte
	if _, err := io.ReadFull(rand.Reader, nonce[:]); err != nil {
		return err
	}
	manifestOffset, err := f.Seek(0, io.SeekCurrent)
	if err != nil {
		return err
	}
	ciphertext := aead.Seal(nil, nonce[:], plain, sourceAssetsV3Magic[:])
	if _, err := f.Write(ciphertext); err != nil {
		return err
	}
	header := sourceAssetsV3Header{ManifestOffset: uint64(manifestOffset), ManifestLength: uint64(len(ciphertext)), ManifestNonce: nonce, ObjectCount: uint32(len(objects))}
	if err := writeSourceAssetsV3Header(f, header); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	ok = true
	return f.Close()
}

func writeSourceAssetsV3Header(f *os.File, h sourceAssetsV3Header) error {
	buf := make([]byte, sourceAssetsV3HeaderSize)
	copy(buf[:8], sourceAssetsV3Magic[:])
	binary.LittleEndian.PutUint64(buf[8:16], h.ManifestOffset)
	binary.LittleEndian.PutUint64(buf[16:24], h.ManifestLength)
	copy(buf[24:36], h.ManifestNonce[:])
	binary.LittleEndian.PutUint32(buf[36:40], h.ObjectCount)
	_, err := f.WriteAt(buf, 0)
	return err
}

func readSourceAssetsV3Header(f *os.File) (sourceAssetsV3Header, error) {
	var out sourceAssetsV3Header
	buf := make([]byte, sourceAssetsV3HeaderSize)
	if _, err := f.ReadAt(buf, 0); err != nil {
		return out, err
	}
	if string(buf[:8]) != string(sourceAssetsV3Magic[:]) {
		return out, fmt.Errorf("not an encrypted .unburger-assets v3 container")
	}
	out.ManifestOffset = binary.LittleEndian.Uint64(buf[8:16])
	out.ManifestLength = binary.LittleEndian.Uint64(buf[16:24])
	copy(out.ManifestNonce[:], buf[24:36])
	out.ObjectCount = binary.LittleEndian.Uint32(buf[36:40])
	return out, nil
}

func writeSourceAssetV3Object(out *os.File, path string, expected SourceAssetImageFile, aead cipher.AEAD) (sourceAssetV3Object, error) {
	var result sourceAssetV3Object
	start, err := out.Seek(0, io.SeekCurrent)
	if err != nil {
		return result, err
	}
	id := make([]byte, 16)
	if _, err := io.ReadFull(rand.Reader, id); err != nil {
		return result, err
	}
	if _, err := out.Write(id); err != nil {
		return result, err
	}

	cmd := exec.Command("zstd", "-q", "-19", "--no-progress", "-c", path)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return result, err
	}
	var stderr strings.Builder
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		return result, err
	}
	buf := make([]byte, sourceAssetsV3ChunkSize)
	var chunkIndex uint64
	for {
		n, readErr := stdout.Read(buf)
		if n > 0 {
			var nonce [12]byte
			if _, err := io.ReadFull(rand.Reader, nonce[:]); err != nil {
				_ = cmd.Process.Kill()
				return result, err
			}
			aad := sourceAssetChunkAAD(id, chunkIndex)
			sealed := aead.Seal(nil, nonce[:], buf[:n], aad)
			var lenBuf [4]byte
			binary.LittleEndian.PutUint32(lenBuf[:], uint32(len(sealed)))
			if _, err := out.Write(lenBuf[:]); err != nil {
				_ = cmd.Process.Kill()
				return result, err
			}
			if _, err := out.Write(nonce[:]); err != nil {
				_ = cmd.Process.Kill()
				return result, err
			}
			if _, err := out.Write(sealed); err != nil {
				_ = cmd.Process.Kill()
				return result, err
			}
			chunkIndex++
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			_ = cmd.Process.Kill()
			return result, readErr
		}
	}
	if err := cmd.Wait(); err != nil {
		return result, fmt.Errorf("zstd %s: %w: %s", expected.Path, err, strings.TrimSpace(stderr.String()))
	}
	end, err := out.Seek(0, io.SeekCurrent)
	if err != nil {
		return result, err
	}
	result = sourceAssetV3Object{
		ID: hex.EncodeToString(id), Path: expected.Path, Size: expected.Size, SHA256: expected.SHA256,
		Offset: start, StoredBytes: end - start, Compression: "zstd", Encryption: "aes-256-gcm-chunked",
	}
	return result, nil
}

func sourceAssetChunkAAD(id []byte, index uint64) []byte {
	aad := make([]byte, len(id)+8)
	copy(aad, id)
	binary.LittleEndian.PutUint64(aad[len(id):], index)
	return aad
}

func readSourceAssetV3Manifest(path string) (sourceAssetV3Manifest, error) {
	var result sourceAssetV3Manifest
	f, err := os.Open(path)
	if err != nil {
		return result, err
	}
	defer f.Close()
	h, err := readSourceAssetsV3Header(f)
	if err != nil {
		return result, err
	}
	info, err := f.Stat()
	if err != nil {
		return result, err
	}
	if h.ManifestLength == 0 || h.ManifestOffset < sourceAssetsV3HeaderSize || h.ManifestOffset+h.ManifestLength > uint64(info.Size()) || h.ManifestLength > 64<<20 {
		return result, fmt.Errorf("invalid encrypted assets manifest bounds")
	}
	ciphertext := make([]byte, h.ManifestLength)
	if _, err := f.ReadAt(ciphertext, int64(h.ManifestOffset)); err != nil {
		return result, err
	}
	aead, err := sourceAssetsAEAD()
	if err != nil {
		return result, fmt.Errorf("assets decryption key: %w", err)
	}
	plain, err := aead.Open(nil, h.ManifestNonce[:], ciphertext, sourceAssetsV3Magic[:])
	if err != nil {
		return result, fmt.Errorf("decrypt .unburger-assets manifest: %w", err)
	}
	if err := json.Unmarshal(plain, &result); err != nil {
		return result, err
	}
	if result.Type != "unburger_assets_encrypted_container" || result.ContainerFormatVersion != 3 || len(result.Objects) != int(h.ObjectCount) {
		return result, fmt.Errorf("unsupported encrypted assets container manifest")
	}
	seenID := map[string]bool{}
	seenPath := map[string]bool{}
	for _, obj := range result.Objects {
		if len(obj.ID) != 32 || obj.Offset < sourceAssetsV3HeaderSize || obj.StoredBytes <= 16 || uint64(obj.Offset+obj.StoredBytes) > h.ManifestOffset || obj.Compression != "zstd" || obj.Encryption != "aes-256-gcm-chunked" {
			return result, fmt.Errorf("invalid encrypted asset object metadata")
		}
		if seenID[obj.ID] || seenPath[obj.Path] {
			return result, fmt.Errorf("duplicate encrypted asset object metadata")
		}
		seenID[obj.ID] = true
		seenPath[obj.Path] = true
	}
	return result, nil
}

type sourceAssetDecryptReader struct {
	r          *io.SectionReader
	aead       cipher.AEAD
	id         []byte
	chunkIndex uint64
	buf        []byte
	off        int
}

func newSourceAssetDecryptReader(f *os.File, obj sourceAssetV3Object, aead cipher.AEAD) (*sourceAssetDecryptReader, error) {
	id, err := hex.DecodeString(obj.ID)
	if err != nil || len(id) != 16 {
		return nil, fmt.Errorf("invalid encrypted asset object id")
	}
	r := io.NewSectionReader(f, obj.Offset, obj.StoredBytes)
	storedID := make([]byte, 16)
	if _, err := io.ReadFull(r, storedID); err != nil {
		return nil, err
	}
	if !equalBytes(storedID, id) {
		return nil, fmt.Errorf("encrypted asset object id mismatch")
	}
	return &sourceAssetDecryptReader{r: r, aead: aead, id: id}, nil
}

func (r *sourceAssetDecryptReader) Read(p []byte) (int, error) {
	if r.off < len(r.buf) {
		n := copy(p, r.buf[r.off:])
		r.off += n
		return n, nil
	}
	var lenBuf [4]byte
	if _, err := io.ReadFull(r.r, lenBuf[:]); err != nil {
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			return 0, io.EOF
		}
		return 0, err
	}
	cipherLen := binary.LittleEndian.Uint32(lenBuf[:])
	if cipherLen < 16 || cipherLen > sourceAssetsV3ChunkSize+64 {
		return 0, fmt.Errorf("invalid encrypted asset chunk size")
	}
	var nonce [12]byte
	if _, err := io.ReadFull(r.r, nonce[:]); err != nil {
		return 0, err
	}
	ciphertext := make([]byte, cipherLen)
	if _, err := io.ReadFull(r.r, ciphertext); err != nil {
		return 0, err
	}
	plain, err := r.aead.Open(nil, nonce[:], ciphertext, sourceAssetChunkAAD(r.id, r.chunkIndex))
	if err != nil {
		return 0, fmt.Errorf("decrypt encrypted asset chunk: %w", err)
	}
	r.chunkIndex++
	r.buf = plain
	r.off = 0
	if len(r.buf) == 0 {
		return r.Read(p)
	}
	n := copy(p, r.buf)
	r.off = n
	return n, nil
}

func extractSourceAssetV3Object(bundle *os.File, obj sourceAssetV3Object, dst string, expected SourceAssetImageFile, report func(done, total int64)) error {
	if obj.Path != expected.Path || obj.Size != expected.Size || !strings.EqualFold(obj.SHA256, expected.SHA256) {
		return fmt.Errorf("encrypted source object metadata mismatch for %s", expected.Path)
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	aead, err := sourceAssetsAEAD()
	if err != nil {
		return err
	}
	decrypt, err := newSourceAssetDecryptReader(bundle, obj, aead)
	if err != nil {
		return err
	}
	zr := zstddec.NewReader(decrypt)
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	h := sha256.New()
	buf := make([]byte, 8<<20)
	var done int64
	for {
		n, readErr := zr.Read(buf)
		if n > 0 {
			if _, err := out.Write(buf[:n]); err != nil {
				_ = out.Close()
				return err
			}
			_, _ = h.Write(buf[:n])
			done += int64(n)
			if report != nil {
				report(done, expected.Size)
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			_ = out.Close()
			return readErr
		}
	}
	if err := out.Close(); err != nil {
		return err
	}
	if done != expected.Size || hex.EncodeToString(h.Sum(nil)) != expected.SHA256 {
		return fmt.Errorf("source image hash mismatch for %s", expected.Path)
	}
	return nil
}

func equalBytes(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	var diff byte
	for i := range a {
		diff |= a[i] ^ b[i]
	}
	return diff == 0
}

func materializeSourceAssetBundleV3(path string, manifest SourceAssetManifest, progress BuildProgressFunc) (string, string, error) {
	container, err := readSourceAssetV3Manifest(path)
	if err != nil {
		return "", "", err
	}
	if container.SourceManifest.SourceFingerprint != manifest.SourceFingerprint {
		return "", "", fmt.Errorf("encrypted assets manifest changed between inspection and materialization")
	}
	stage, err := workspace.MkdirTemp("unburger-br1-assets-")
	if err != nil {
		return "", "", err
	}
	ok := false
	defer func() {
		if !ok {
			_ = os.RemoveAll(stage)
		}
	}()
	root := filepath.Join(stage, "source")
	bundle, err := os.Open(path)
	if err != nil {
		return "", "", err
	}
	defer bundle.Close()
	byPath := map[string]sourceAssetV3Object{}
	for _, obj := range container.Objects {
		byPath[obj.Path] = obj
	}
	var total int64
	for _, item := range manifest.ImageFiles {
		total += item.Size
	}
	var done int64
	if progress != nil {
		progress(BuildProgress{Phase: "source_bundle_manifest", CurrentFile: filepath.Base(path)})
	}
	for _, item := range manifest.ImageFiles {
		obj, exists := byPath[item.Path]
		if !exists {
			return "", "", fmt.Errorf("encrypted source bundle missing object for %s", item.Path)
		}
		dst := filepath.Join(stage, filepath.FromSlash(item.Path))
		if err := extractSourceAssetV3Object(bundle, obj, dst, item, func(current, currentTotal int64) {
			if progress != nil {
				progress(BuildProgress{Phase: "source_bundle_extract", CurrentFile: item.Path, CurrentDone: current, CurrentTotal: currentTotal, OverallDone: min64(done+current, total), OverallTotal: total})
			}
		}); err != nil {
			return "", "", err
		}
		done += item.Size
	}
	if err := validateMaterializedSourceImage(stage, manifest, progress); err != nil {
		return "", "", err
	}
	ok = true
	return root, stage, nil
}
