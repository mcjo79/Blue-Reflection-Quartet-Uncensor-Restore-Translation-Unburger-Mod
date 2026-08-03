package catalog

import "testing"

func TestLoad(t *testing.T) {
	modules, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(modules) != 4 {
		t.Fatalf("expected 4 modules, got %d", len(modules))
	}
	if modules[0].ModuleID != "blue_reflection_translation" {
		t.Fatalf("unexpected first module: %+v", modules[0])
	}
}
