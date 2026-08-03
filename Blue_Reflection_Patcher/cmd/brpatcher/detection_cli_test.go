package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func TestPromptedPathFallback(t *testing.T) {
	game := t.TempDir()
	marker := filepath.Join(game, "Data", "PACK02.PAK")
	if err := os.MkdirAll(filepath.Dir(marker), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(marker, []byte("pak"), 0o644); err != nil {
		t.Fatal(err)
	}

	old, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	empty := t.TempDir()
	if err := os.Chdir(empty); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(old)

	specs := []model.TargetSpec{{
		TargetID: "second_light", DisplayName: "Second Light",
		RequiredFiles: []string{"Data/PACK02.PAK"},
	}}
	var output bytes.Buffer
	items, err := detectWithFallback(specs, nil, true, strings.NewReader(game+"\n"), &output)
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].Source != "prompted_path" {
		t.Fatalf("unexpected detections: %+v", items)
	}
	if !strings.Contains(output.String(), "Enter the game directory path") {
		t.Fatalf("prompt was not written: %q", output.String())
	}
}
