package managedstate

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const FileName = "UNBURGER_MOD_STATE.json"

const (
	StateType          = "unburger_managed_game_state"
	StateFormatVersion = 2
)

type TranslationMember struct {
	ArchiveRelativePath    string `json:"archive_relative_path"`
	InternalPath           string `json:"internal_path"`
	Kind                   string `json:"kind"`
	InstalledContentSHA256 string `json:"installed_content_sha256"`
	BindingSHA256          string `json:"binding_sha256"`
	StructuralSHA256       string `json:"structural_sha256,omitempty"`
}

type TranslationState struct {
	Version string              `json:"version"`
	Members []TranslationMember `json:"members"`
}

type State struct {
	Type          string            `json:"type"`
	FormatVersion int               `json:"format_version"`
	TargetID      string            `json:"target_id"`
	Translation   *TranslationState `json:"translation,omitempty"`
}

func memberKey(archive, internal, kind string) string {
	archive = strings.ToLower(filepath.ToSlash(strings.TrimSpace(archive)))
	internal = strings.ToLower(strings.ReplaceAll(strings.TrimSpace(internal), "/", `\`))
	if !strings.HasPrefix(internal, `\`) {
		internal = `\` + internal
	}
	return archive + "\x00" + internal + "\x00" + strings.ToLower(strings.TrimSpace(kind))
}

func (s State) TranslationMembers() map[string]TranslationMember {
	out := map[string]TranslationMember{}
	if s.Translation == nil {
		return out
	}
	for _, m := range s.Translation.Members {
		out[memberKey(m.ArchiveRelativePath, m.InternalPath, m.Kind)] = m
	}
	return out
}

func LookupTranslationMember(s State, archive, internal, kind string) (TranslationMember, bool) {
	if s.Translation == nil {
		return TranslationMember{}, false
	}
	want := memberKey(archive, internal, kind)
	for _, m := range s.Translation.Members {
		if memberKey(m.ArchiveRelativePath, m.InternalPath, m.Kind) == want {
			return m, true
		}
	}
	return TranslationMember{}, false
}

// Load is deliberately best-effort. This file is durable provenance, not an
// availability dependency: missing, stale, malformed, or manually removed state
// must never prevent the patcher from resolving the game from its own contents.
func Load(gameRoot, targetID string) (State, bool) {
	path := filepath.Join(gameRoot, FileName)
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
		return State{}, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return State{}, false
	}
	var state State
	if json.Unmarshal(data, &state) != nil || state.Type != StateType || (state.FormatVersion != 1 && state.FormatVersion != StateFormatVersion) || state.TargetID != targetID {
		return State{}, false
	}
	return state, true
}

func Write(path, targetID, translationVersion string, members []TranslationMember) error {
	ordered := append([]TranslationMember(nil), members...)
	sort.Slice(ordered, func(i, j int) bool {
		a := memberKey(ordered[i].ArchiveRelativePath, ordered[i].InternalPath, ordered[i].Kind)
		b := memberKey(ordered[j].ArchiveRelativePath, ordered[j].InternalPath, ordered[j].Kind)
		return a < b
	})
	state := State{
		Type: StateType, FormatVersion: StateFormatVersion, TargetID: targetID,
		Translation: &TranslationState{Version: translationVersion, Members: ordered},
	}
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}
