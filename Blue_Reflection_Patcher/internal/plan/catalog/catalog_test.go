package catalog

import "testing"

func TestLoad(t *testing.T) {
	modules, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if len(modules) != 5 {
		t.Fatalf("expected 5 modules, got %d", len(modules))
	}
	if modules[0].ModuleID != "blue_reflection_translation" {
		t.Fatalf("unexpected first module: %+v", modules[0])
	}
}
