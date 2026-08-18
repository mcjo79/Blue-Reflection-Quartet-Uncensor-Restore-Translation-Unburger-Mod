package assetkey

import (
	"crypto/sha256"
	"errors"
)

var embeddedSeed []byte

// Key derives the 256-bit developer source-assets key from build-time embedded
// seed fragments. The repository intentionally contains no production seed.
func derivedKey(label string) ([]byte, error) {
	if len(embeddedSeed) != 32 {
		return nil, errors.New("encrypted UNBURGER payload support is unavailable in this build")
	}
	h := sha256.New()
	h.Write([]byte(label))
	h.Write(embeddedSeed)
	return h.Sum(nil), nil
}

func Key() ([]byte, error) {
	return derivedKey("UNBURGER assets v3 key\x00")
}

// RuntimeKey derives a domain-separated key for the always-shipped encrypted
// .unburger runtime bundle. It intentionally uses the same local build seed as
// .unburger-assets without reusing the AES key itself.
func RuntimeKey() ([]byte, error) {
	return derivedKey("UNBURGER runtime v4 key\x00")
}

// InstallEmbeddedSeed is used only by a generated, non-committed build file.
func InstallEmbeddedSeed(seed []byte) {
	if len(seed) != 32 {
		panic("invalid embedded assets seed")
	}
	embeddedSeed = append(embeddedSeed[:0], seed...)
}
