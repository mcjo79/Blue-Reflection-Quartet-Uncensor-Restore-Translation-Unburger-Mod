package managedstate

import (
	"os"
	"path/filepath"
	"testing"
)

func TestStateSurvivesWithoutExternalPatcherState(t *testing.T) {
	root := t.TempDir()
	members := []TranslationMember{{ArchiveRelativePath: "Data/PACK01_03.PAK", InternalPath: `\event\b4\event_en\dm03\x.ebm`, Kind: "ebm", InstalledContentSHA256: "abc", BindingSHA256: "def", StructuralSHA256: "struct"}}
	path := filepath.Join(root, FileName)
	if err := Write(path, "blue_reflection_quartet", "0.0.203", members); err != nil {
		t.Fatal(err)
	}
	// No AppData/state-root fixture exists at all. The durable state is resolved
	// strictly from the game root.
	got, ok := Load(root, "blue_reflection_quartet")
	if !ok {
		t.Fatal("expected game-root state")
	}
	m, ok := LookupTranslationMember(got, "Data/PACK01_03.PAK", `\event\b4\event_en\dm03\x.ebm`, "ebm")
	if !ok || m.InstalledContentSHA256 != "abc" || m.BindingSHA256 != "def" || m.StructuralSHA256 != "struct" {
		t.Fatalf("unexpected member: %#v", m)
	}
}

func TestMissingOrMalformedStateIsNeverRequired(t *testing.T) {
	root := t.TempDir()
	if _, ok := Load(root, "blue_reflection_quartet"); ok {
		t.Fatal("missing state must be unavailable")
	}
	if err := os.WriteFile(filepath.Join(root, FileName), []byte("not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, ok := Load(root, "blue_reflection_quartet"); ok {
		t.Fatal("malformed state must be ignored")
	}
}

func TestLoadAcceptsV1StateForMigration(t *testing.T) {
	root := t.TempDir()
	data := []byte(`{"type":"unburger_managed_game_state","format_version":1,"target_id":"blue_reflection_quartet","translation":{"version":"old","members":[{"archive_relative_path":"Data/PACK01_03.PAK","internal_path":"\\event\\b4\\event_en\\x.ebm","kind":"ebm","installed_content_sha256":"abc","binding_sha256":"def"}]}}`)
	if err := os.WriteFile(filepath.Join(root, FileName), data, 0o644); err != nil {
		t.Fatal(err)
	}
	state, ok := Load(root, "blue_reflection_quartet")
	if !ok || state.FormatVersion != 1 {
		t.Fatalf("v1 migration state not loaded: %#v", state)
	}
}
