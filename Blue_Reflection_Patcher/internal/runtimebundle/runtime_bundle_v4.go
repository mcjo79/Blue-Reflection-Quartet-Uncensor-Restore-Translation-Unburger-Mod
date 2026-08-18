package runtimebundle

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"io"
	"os"

	"local/blue-reflection-patcher/internal/assetkey"
)

var runtimeV4Magic = [8]byte{'U', 'N', 'B', 'R', 'T', 'V', '4', 0}

const (
	runtimeV4Version   = uint32(4)
	runtimeV4ChunkSize = uint32(1 << 20)
	runtimeV4HeaderLen = 16
)

func runtimeV4AEAD() (cipher.AEAD, error) {
	key, err := assetkey.RuntimeKey()
	if err != nil {
		return nil, err
	}
	block, err := aes.NewCipher(key)
	for i := range key {
		key[i] = 0
	}
	if err != nil {
		return nil, err
	}
	return cipher.NewGCM(block)
}

func runtimeV4AAD(index uint64) []byte {
	prefix := []byte("UNBURGER runtime v4 chunk\x00")
	out := make([]byte, len(prefix)+8)
	copy(out, prefix)
	binary.LittleEndian.PutUint64(out[len(prefix):], index)
	return out
}

// EncryptRuntimeBundleV4 wraps an already-compressed tar+Zstandard runtime
// image in chunked AES-256-GCM. The inner bundle retains SHA256SUMS and the
// external release still carries a whole-file SHA-256 sidecar.
func EncryptRuntimeBundleV4(inputPath, outputPath string) error {
	in, err := os.Open(inputPath)
	if err != nil {
		return err
	}
	defer in.Close()
	var zmagic [4]byte
	if _, err := io.ReadFull(in, zmagic[:]); err != nil {
		return fmt.Errorf("read runtime payload header: %w", err)
	}
	if zmagic != [4]byte{0x28, 0xb5, 0x2f, 0xfd} {
		return fmt.Errorf("runtime v4 input is not tar+Zstandard")
	}
	if _, err := in.Seek(0, io.SeekStart); err != nil {
		return err
	}
	aead, err := runtimeV4AEAD()
	if err != nil {
		return err
	}
	tmp := outputPath + ".tmp"
	_ = os.Remove(tmp)
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(tmp)
		}
	}()
	if _, err := out.Write(runtimeV4Magic[:]); err != nil {
		return err
	}
	var h [8]byte
	binary.LittleEndian.PutUint32(h[0:4], runtimeV4Version)
	binary.LittleEndian.PutUint32(h[4:8], runtimeV4ChunkSize)
	if _, err := out.Write(h[:]); err != nil {
		return err
	}
	buf := make([]byte, runtimeV4ChunkSize)
	var index uint64
	for {
		n, readErr := io.ReadFull(in, buf)
		if readErr == io.ErrUnexpectedEOF || readErr == io.EOF {
			if n == 0 {
				break
			}
		} else if readErr != nil {
			return readErr
		}
		nonce := make([]byte, aead.NonceSize())
		if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
			return err
		}
		sealed := aead.Seal(nil, nonce, buf[:n], runtimeV4AAD(index))
		var lb [4]byte
		binary.LittleEndian.PutUint32(lb[:], uint32(len(sealed)))
		if _, err := out.Write(lb[:]); err != nil {
			return err
		}
		if _, err := out.Write(nonce); err != nil {
			return err
		}
		if _, err := out.Write(sealed); err != nil {
			return err
		}
		index++
		if readErr == io.ErrUnexpectedEOF || readErr == io.EOF {
			break
		}
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmp, outputPath); err != nil {
		return err
	}
	ok = true
	return nil
}

type runtimeV4DecryptReader struct {
	f         *os.File
	aead      cipher.AEAD
	chunkSize uint32
	index     uint64
	current   *bytes.Reader
}

func openRuntimeV4(path string) (*runtimeV4DecryptReader, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	fail := func(err error) (*runtimeV4DecryptReader, error) {
		_ = f.Close()
		return nil, err
	}
	var magic [8]byte
	if _, err := io.ReadFull(f, magic[:]); err != nil {
		return fail(err)
	}
	if magic != runtimeV4Magic {
		return fail(fmt.Errorf("not an encrypted runtime v4 bundle"))
	}
	var h [8]byte
	if _, err := io.ReadFull(f, h[:]); err != nil {
		return fail(err)
	}
	version := binary.LittleEndian.Uint32(h[0:4])
	chunkSize := binary.LittleEndian.Uint32(h[4:8])
	if version != runtimeV4Version || chunkSize == 0 || chunkSize > 16<<20 {
		return fail(fmt.Errorf("unsupported encrypted runtime bundle header"))
	}
	aead, err := runtimeV4AEAD()
	if err != nil {
		return fail(err)
	}
	return &runtimeV4DecryptReader{f: f, aead: aead, chunkSize: chunkSize}, nil
}

func (r *runtimeV4DecryptReader) Close() error { return r.f.Close() }

func (r *runtimeV4DecryptReader) Read(p []byte) (int, error) {
	for {
		if r.current != nil && r.current.Len() > 0 {
			return r.current.Read(p)
		}
		var lb [4]byte
		_, err := io.ReadFull(r.f, lb[:])
		if err == io.EOF {
			return 0, io.EOF
		}
		if err != nil {
			return 0, fmt.Errorf("read encrypted runtime chunk length: %w", err)
		}
		sealedLen := binary.LittleEndian.Uint32(lb[:])
		if sealedLen < uint32(r.aead.Overhead()) || sealedLen > r.chunkSize+uint32(r.aead.Overhead()) {
			return 0, fmt.Errorf("invalid encrypted runtime chunk length")
		}
		nonce := make([]byte, r.aead.NonceSize())
		if _, err := io.ReadFull(r.f, nonce); err != nil {
			return 0, fmt.Errorf("read encrypted runtime nonce: %w", err)
		}
		sealed := make([]byte, sealedLen)
		if _, err := io.ReadFull(r.f, sealed); err != nil {
			return 0, fmt.Errorf("read encrypted runtime ciphertext: %w", err)
		}
		plain, err := r.aead.Open(nil, nonce, sealed, runtimeV4AAD(r.index))
		if err != nil {
			return 0, fmt.Errorf("decrypt runtime chunk %d: %w", r.index, err)
		}
		r.index++
		r.current = bytes.NewReader(plain)
	}
}

func isRuntimeV4(path string) (bool, error) {
	f, err := os.Open(path)
	if err != nil {
		return false, err
	}
	defer f.Close()
	var magic [8]byte
	if _, err := io.ReadFull(f, magic[:]); err != nil {
		return false, err
	}
	return magic == runtimeV4Magic, nil
}
