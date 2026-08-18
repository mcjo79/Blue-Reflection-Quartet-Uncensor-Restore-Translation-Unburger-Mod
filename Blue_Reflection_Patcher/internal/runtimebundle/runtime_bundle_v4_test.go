package runtimebundle

import (
	"archive/tar"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"local/blue-reflection-patcher/internal/assetkey"
)

func TestEncryptedRuntimeV4RoundTrip(t *testing.T) {
	if _, err := exec.LookPath("zstd"); err != nil {
		t.Skip("zstd CLI unavailable")
	}
	assetkey.InstallEmbeddedSeed(bytes.Repeat([]byte{0x51}, 32))
	root := t.TempDir()
	files := map[string][]byte{
		"RELEASE_MANIFEST.json":                        []byte("{\"type\":\"unburger_release_manifest\",\"format_version\":4,\"core_version\":\"0.0.115\",\"canonical_restoration_payload_embedded\":true}\n"),
		"content/translation/records.v1.json":          []byte("{}\n"),
		"content/restoration/wet-school/MANIFEST.json": []byte("{\"type\":\"fixture\"}\n"),
	}
	var sums string
	for name, data := range files {
		h := sha256.Sum256(data)
		sums += fmt.Sprintf("%s  ./%s\n", hex.EncodeToString(h[:]), name)
	}
	files["SHA256SUMS"] = []byte(sums)
	tarPath := filepath.Join(root, "payload.tar")
	f, err := os.Create(tarPath)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	for _, name := range []string{"RELEASE_MANIFEST.json", "content/translation/records.v1.json", "content/restoration/wet-school/MANIFEST.json", "SHA256SUMS"} {
		data := files[name]
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o644, Size: int64(len(data))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	zstdPath := filepath.Join(root, "payload.tar.zst")
	if out, err := exec.Command("zstd", "-q", "-19", "-f", tarPath, "-o", zstdPath).CombinedOutput(); err != nil {
		t.Fatalf("zstd: %v: %s", err, out)
	}
	bundle := filepath.Join(root, "UNBURGER_0.0.115.unburger")
	if err := EncryptRuntimeBundleV4(zstdPath, bundle); err != nil {
		t.Fatal(err)
	}
	if ok, err := isRuntimeV4(bundle); err != nil || !ok {
		t.Fatalf("v4 detection: ok=%v err=%v", ok, err)
	}
	version, err := CoreVersion(bundle)
	if err != nil {
		t.Fatal(err)
	}
	if version != "0.0.115" {
		t.Fatalf("version=%q", version)
	}
	if err := VerifyBundleFile(bundle); err != nil {
		t.Fatal(err)
	}

	stage := t.TempDir()
	if err := extractRuntimeBundle(bundle, stage); err != nil {
		t.Fatal(err)
	}
	if err := validateMaterialized(stage); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(stage, "content", "restoration", "wet-school", "MANIFEST.json")); err != nil {
		t.Fatal(err)
	}
}

func TestEncryptedRuntimeV4RejectsTamper(t *testing.T) {
	if _, err := exec.LookPath("zstd"); err != nil {
		t.Skip("zstd CLI unavailable")
	}
	assetkey.InstallEmbeddedSeed(bytes.Repeat([]byte{0x52}, 32))
	root := t.TempDir()
	tarPath := filepath.Join(root, "payload.tar")
	f, err := os.Create(tarPath)
	if err != nil {
		t.Fatal(err)
	}
	tw := tar.NewWriter(f)
	manifest := []byte("{\"type\":\"unburger_release_manifest\",\"format_version\":4,\"core_version\":\"0.0.115\"}\n")
	records := []byte("{}\n")
	mh := sha256.Sum256(manifest)
	rh := sha256.Sum256(records)
	sums := []byte(fmt.Sprintf("%s  ./RELEASE_MANIFEST.json\n%s  ./content/translation/records.v1.json\n", hex.EncodeToString(mh[:]), hex.EncodeToString(rh[:])))
	for _, item := range []struct {
		name string
		data []byte
	}{{"RELEASE_MANIFEST.json", manifest}, {"content/translation/records.v1.json", records}, {"SHA256SUMS", sums}} {
		if err := tw.WriteHeader(&tar.Header{Name: item.name, Mode: 0o644, Size: int64(len(item.data))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(item.data); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	zstdPath := filepath.Join(root, "payload.zst")
	if out, err := exec.Command("zstd", "-q", "-f", tarPath, "-o", zstdPath).CombinedOutput(); err != nil {
		t.Fatalf("zstd: %v: %s", err, out)
	}
	bundle := filepath.Join(root, "UNBURGER.unburger")
	if err := EncryptRuntimeBundleV4(zstdPath, bundle); err != nil {
		t.Fatal(err)
	}
	blob, err := os.ReadFile(bundle)
	if err != nil {
		t.Fatal(err)
	}
	if len(blob) < runtimeV4HeaderLen+32 {
		t.Fatal("bundle too small")
	}
	blob[len(blob)-1] ^= 0x01
	if err := os.WriteFile(bundle, blob, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := VerifyBundleFile(bundle); err == nil {
		t.Fatal("tampered encrypted runtime was accepted")
	}
}
