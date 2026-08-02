package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type localProfileFixture struct {
	project        string
	game           string
	eventBaseline  []byte
	shaderBaseline []byte
	manifests      map[string]localProfileManifest
	sources        map[string]string
}

func newLocalProfileFixture(t *testing.T) localProfileFixture {
	t.Helper()
	root := t.TempDir()
	project := filepath.Join(root, "project")
	game := filepath.Join(root, "game")
	manifestDir := filepath.Join(project, filepath.FromSlash(localProfileManifestRoot))
	payloadDir := filepath.Join(project, filepath.FromSlash(localProfilePayloadRoot), "synthetic")
	if err := os.MkdirAll(manifestDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(payloadDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	eventBaseline := []byte("synthetic PACK11 baseline\n")
	shaderBaseline := []byte("synthetic PACK10_01 baseline\n")
	if err := os.WriteFile(filepath.Join(game, "Data", "PACK11.PAK"), eventBaseline, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(game, "Data", "PACK10_01.PAK"), shaderBaseline, 0o644); err != nil {
		t.Fatal(err)
	}

	definitions := []struct {
		id      string
		target  string
		payload []byte
		members []string
	}{
		{"repeated_context_69adef108a_c90700a5a2", "Data/PACK11.PAK", []byte("event repeated profile\n"), []string{"event/a", "event/b"}},
		{"route_sequence_te02_a570203aa6", "Data/PACK11.PAK", []byte("event route profile\n"), []string{"event/c"}},
		{"single_scene_event_te02_230_0143f9822b", "Data/PACK11.PAK", []byte("event single scene profile\n"), []string{"event/d"}},
		{"height_fog_shader_original_code", "Data/PACK10_01.PAK", []byte("shader height fog profile\n"), []string{"shader/heightfog"}},
		{"water_shader_swater_original_code", "Data/PACK10_01.PAK", []byte("shader swater profile\n"), []string{"shader/swater"}},
	}
	manifests := map[string]localProfileManifest{}
	sources := map[string]string{}
	for _, definition := range definitions {
		sourceRel := filepath.ToSlash(filepath.Join(localProfilePayloadRoot, "synthetic", definition.id+".PAK"))
		sourceAbs := filepath.Join(project, filepath.FromSlash(sourceRel))
		if err := os.WriteFile(sourceAbs, definition.payload, 0o644); err != nil {
			t.Fatal(err)
		}
		baseline := eventBaseline
		if definition.target == "Data/PACK10_01.PAK" {
			baseline = shaderBaseline
		}
		manifest := localProfileManifest{
			SchemaVersion: localProfileSchemaVersion, ProfileID: definition.id,
			TargetRelativePath: definition.target,
			BaselineSHA256:     digestBytesForLocalProfiles(baseline), BaselineSize: int64(len(baseline)),
			ProfileSHA256: digestBytesForLocalProfiles(definition.payload), ProfileSize: int64(len(definition.payload)),
			LocalProfilePath: sourceRel, ChangedMemberCount: len(definition.members), ChangedMembers: definition.members,
			RuntimeValidated: false, WorkstreamID: localProfileWorkstreamID, WorkstreamVersion: "0.0.34-test",
		}
		writeLocalProfileManifestFixture(t, project, definition.id, manifest)
		manifests[definition.id] = manifest
		sources[definition.id] = sourceAbs
	}
	return localProfileFixture{project: project, game: game, eventBaseline: eventBaseline, shaderBaseline: shaderBaseline, manifests: manifests, sources: sources}
}

func writeLocalProfileManifestFixture(t *testing.T, projectRoot, filename string, manifest localProfileManifest) string {
	t.Helper()
	path := filepath.Join(projectRoot, filepath.FromSlash(localProfileManifestRoot), filename+".json")
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	data = append(data, '\n')
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func digestBytesForLocalProfiles(data []byte) string {
	path, err := os.CreateTemp("", "br-local-profile-digest-*")
	if err != nil {
		panic(err)
	}
	name := path.Name()
	defer os.Remove(name)
	if _, err := path.Write(data); err != nil {
		panic(err)
	}
	if err := path.Close(); err != nil {
		panic(err)
	}
	hash, _, err := checkedFile(name)
	if err != nil {
		panic(err)
	}
	return hash
}

func TestLocalProfileRegistryDiscoversAllFiveProfiles(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	registry, err := discoverLocalProfiles(fixture.project)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Profiles) != 5 || len(registry.Issues) != 0 {
		t.Fatalf("profiles=%d issues=%+v", len(registry.Profiles), registry.Issues)
	}
	for id := range fixture.manifests {
		if _, ok := registry.Profiles[id]; !ok {
			t.Fatalf("missing profile %s", id)
		}
	}
}

func TestLocalProfileRegistryRejectsChangedSHAWithoutBlockingOthers(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	if err := os.WriteFile(fixture.sources["route_sequence_te02_a570203aa6"], []byte("corrupted\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	registry, err := discoverLocalProfiles(fixture.project)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Profiles) != 4 {
		t.Fatalf("expected four valid profiles, got %d", len(registry.Profiles))
	}
	if _, ok := registry.Profiles["repeated_context_69adef108a_c90700a5a2"]; !ok {
		t.Fatalf("a corrupt profile blocked a valid profile")
	}
	found := false
	for _, issue := range registry.Issues {
		if issue.ProfileID == "route_sequence_te02_a570203aa6" && (issue.Status == "size_mismatch" || issue.Status == "sha256_mismatch") {
			found = true
		}
	}
	if !found {
		t.Fatalf("missing checksum rejection: %+v", registry.Issues)
	}
}

func TestLocalProfileRegistryRejectsPathTraversal(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	manifest := fixture.manifests["single_scene_event_te02_230_0143f9822b"]
	manifest.ProfileID = "traversal_profile"
	manifest.LocalProfilePath = "../outside.PAK"
	writeLocalProfileManifestFixture(t, fixture.project, "traversal", manifest)
	registry, err := discoverLocalProfiles(fixture.project)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := registry.Profiles["traversal_profile"]; ok {
		t.Fatalf("path traversal profile was accepted")
	}
	assertRegistryIssue(t, registry, "traversal_profile", "invalid_local_path")
}

func TestLocalProfileRegistryRejectsUnsupportedTarget(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	manifest := fixture.manifests["single_scene_event_te02_230_0143f9822b"]
	manifest.ProfileID = "unsupported_target_profile"
	manifest.TargetRelativePath = "Data/PACK99.PAK"
	writeLocalProfileManifestFixture(t, fixture.project, "unsupported", manifest)
	registry, err := discoverLocalProfiles(fixture.project)
	if err != nil {
		t.Fatal(err)
	}
	assertRegistryIssue(t, registry, "unsupported_target_profile", "unsupported_target")
}

func TestLocalProfileRegistryRejectsDuplicateProfileID(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	duplicate := fixture.manifests["repeated_context_69adef108a_c90700a5a2"]
	writeLocalProfileManifestFixture(t, fixture.project, "duplicate-copy", duplicate)
	registry, err := discoverLocalProfiles(fixture.project)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := registry.Profiles[duplicate.ProfileID]; ok {
		t.Fatalf("duplicate profile ID remained activatable")
	}
	count := 0
	for _, issue := range registry.Issues {
		if issue.ProfileID == duplicate.ProfileID && issue.Status == "duplicate_profile_id" {
			count++
		}
	}
	if count != 2 {
		t.Fatalf("expected both duplicate manifests to be rejected, got %d issues: %+v", count, registry.Issues)
	}
	if len(registry.Profiles) != 4 {
		t.Fatalf("duplicate blocked unrelated profiles: %d valid", len(registry.Profiles))
	}
}

func TestLocalProfileActivationAndRollbackForBothTargets(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	ctx := profileCommandContext{ProjectRoot: fixture.project, GameRoot: fixture.game}
	cases := []struct {
		id       string
		target   string
		baseline []byte
	}{
		{"single_scene_event_te02_230_0143f9822b", "Data/PACK11.PAK", fixture.eventBaseline},
		{"height_fog_shader_original_code", "Data/PACK10_01.PAK", fixture.shaderBaseline},
	}
	for _, item := range cases {
		if err := activateDiscoveredProfile(ctx, item.target, item.id); err != nil {
			t.Fatalf("activate %s: %v", item.id, err)
		}
		target := filepath.Join(fixture.game, filepath.FromSlash(item.target))
		installed, err := os.ReadFile(target)
		if err != nil {
			t.Fatal(err)
		}
		source, err := os.ReadFile(fixture.sources[item.id])
		if err != nil {
			t.Fatal(err)
		}
		if string(installed) != string(source) {
			t.Fatalf("profile %s was not installed", item.id)
		}
		if err := rollbackDiscoveredProfile(ctx, item.target); err != nil {
			t.Fatalf("rollback %s: %v", item.id, err)
		}
		restored, err := os.ReadFile(target)
		if err != nil {
			t.Fatal(err)
		}
		if string(restored) != string(item.baseline) {
			t.Fatalf("target %s was not restored", item.target)
		}
	}
}

func TestLocalProfileListPreservesLegacyTransactionState(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	statePath := filepath.Join(fixture.project, filepath.FromSlash(localProfileTargets["Data/PACK11.PAK"].StatePath))
	if err := os.MkdirAll(filepath.Dir(statePath), 0o755); err != nil {
		t.Fatal(err)
	}
	legacy := map[string]any{
		"type": profileStateType, "format_version": 1, "status": "rolled_back",
		"transaction_id": "legacy-transaction", "profile_id": "repeated_context_69adef108a_c90700a5a2",
		"target_relative_path": "Data/PACK11.PAK", "source_relative_path": fixture.manifests["repeated_context_69adef108a_c90700a5a2"].LocalProfilePath,
		"backup_relative_path":   ".local/backups/legacy/PACK11.PAK",
		"baseline_sha256":        digestBytesForLocalProfiles(fixture.eventBaseline),
		"active_profile_sha256":  fixture.manifests["repeated_context_69adef108a_c90700a5a2"].ProfileSHA256,
		"observed_before_sha256": digestBytesForLocalProfiles(fixture.eventBaseline),
		"observed_before_size":   len(fixture.eventBaseline), "created_utc": "2026-08-03T00:00:00Z", "updated_utc": "2026-08-03T00:00:00Z",
	}
	before, err := json.MarshalIndent(legacy, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	before = append(before, '\n')
	if err := os.WriteFile(statePath, before, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := listDiscoveredProfiles(profileCommandContext{ProjectRoot: fixture.project, GameRoot: fixture.game}); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if string(after) != string(before) {
		t.Fatalf("read-only discovery changed an existing transaction state")
	}
	state, exists, err := readLocalProfileState(statePath, localProfileTargets["Data/PACK11.PAK"])
	if err != nil || !exists || state.TransactionID != "legacy-transaction" {
		t.Fatalf("legacy state not preserved/read: exists=%v state=%+v err=%v", exists, state, err)
	}
}

func TestExistingEventAndShaderCommandRoutesRemainCompatible(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	baseArgs := []string{"--project-root", fixture.project, "--game-root", fixture.game}
	eventArgs := append(append([]string{}, baseArgs...), "repeated_context_69adef108a_c90700a5a2")
	if err := commandDiscoveredProfileActivate(eventArgs, "Data/PACK11.PAK"); err != nil {
		t.Fatalf("legacy event activate route: %v", err)
	}
	if err := commandDiscoveredProfileStatus(baseArgs, "Data/PACK11.PAK"); err != nil {
		t.Fatalf("legacy event status route: %v", err)
	}
	if err := commandDiscoveredProfileRollback(baseArgs, "Data/PACK11.PAK"); err != nil {
		t.Fatalf("legacy event rollback route: %v", err)
	}
	shaderArgs := append(append([]string{}, baseArgs...), "water_shader_swater_original_code")
	if err := commandDiscoveredProfileActivate(shaderArgs, "Data/PACK10_01.PAK"); err != nil {
		t.Fatalf("legacy shader activate route: %v", err)
	}
	if err := commandDiscoveredProfileStatus(baseArgs, "Data/PACK10_01.PAK"); err != nil {
		t.Fatalf("legacy shader status route: %v", err)
	}
	if err := commandDiscoveredProfileRollback(baseArgs, "Data/PACK10_01.PAK"); err != nil {
		t.Fatalf("legacy shader rollback route: %v", err)
	}
}

func TestCrossTargetActivationIsBlockedDuringInitialValidation(t *testing.T) {
	fixture := newLocalProfileFixture(t)
	ctx := profileCommandContext{ProjectRoot: fixture.project, GameRoot: fixture.game}
	if err := activateDiscoveredProfile(ctx, "Data/PACK11.PAK", "route_sequence_te02_a570203aa6"); err != nil {
		t.Fatal(err)
	}
	err := activateDiscoveredProfile(ctx, "Data/PACK10_01.PAK", "height_fog_shader_original_code")
	if err == nil || !strings.Contains(err.Error(), "transaction is already open") {
		t.Fatalf("cross-target activation was not blocked: %v", err)
	}
}

func assertRegistryIssue(t *testing.T, registry localProfileRegistry, profileID, status string) {
	t.Helper()
	for _, issue := range registry.Issues {
		if issue.ProfileID == profileID && issue.Status == status {
			return
		}
	}
	t.Fatalf("missing issue profile=%s status=%s: %+v", profileID, status, registry.Issues)
}
