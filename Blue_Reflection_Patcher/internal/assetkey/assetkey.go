package assetkey

import (
	"crypto/sha256"
	"errors"
)

var embeddedSeed []byte

// Key derives the 256-bit developer source-assets key from build-time embedded
// seed fragments. The repository intentionally contains no production seed.
func Key() ([]byte, error) {
	if len(embeddedSeed) != 32 {
		return nil, errors.New("encrypted .unburger-assets support is unavailable in this build")
	}
	h := sha256.New()
	h.Write([]byte("UNBURGER assets v3 key\x00"))
	h.Write(embeddedSeed)
	return h.Sum(nil), nil
}

// InstallEmbeddedSeed is used only by a generated, non-committed build file.
func InstallEmbeddedSeed(seed []byte) {
	if len(seed) != 32 {
		panic("invalid embedded assets seed")
	}
	embeddedSeed = append(embeddedSeed[:0], seed...)
}
