package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type shaderProfileFixture struct {
	ctx      profileCommandContext
	target   string
	sourceA  string
	sourceB  string
	baseline []byte
	profileA []byte
	profileB []byte
	config   quartetShaderProfileConfig
	project  string
	game     string
}

func newShaderProfileFixture(t *testing.T) shaderProfileFixture {
	t.Helper()
	root := t.TempDir()
	project := filepath.Join(root, "project")
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(filepath.Join(project, ".local", "build", "shader_profiles", "a"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(project, ".local", "build", "shader_profiles", "b"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	baseline := []byte("baseline PACK10_01 payload\n")
	profileA := []byte("height fog shader profile payload\n")
	profileB := []byte("swater shader profile payload\n")
	target := filepath.Join(game, "Data", "PACK10_01.PAK")
	sourceA := filepath.Join(project, ".local", "build", "shader_profiles", "a", "PACK10_01.PAK")
	sourceB := filepath.Join(project, ".local", "build", "shader_profiles", "b", "PACK10_01.PAK")
	for path, data := range map[string][]byte{target: baseline, sourceA: profileA, sourceB: profileB} {
		if err := os.WriteFile(path, data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	baseHash := digestBytes(baseline)
	profileAHash := digestBytes(profileA)
	profileBHash := digestBytes(profileB)
	config := quartetShaderProfileConfig{
		Type: shaderProfileConfigType, FormatVersion: 1, RequestToolVersion: "test",
		TransactionOwner: "core_unified_patcher", Status: "runtime_unvalidated",
		TargetRelativePath: "Data/PACK10_01.PAK", BaselineSHA256: baseHash,
		BaselineSize: int64(len(baseline)),
		Profiles: []quartetShaderProfile{
			{
				ProfileID: "height_fog_shader_original_code", RuleID: "height_fog_shader",
				Domain: "steam_or_vapor_occlusion", Priority: "high", TestOrder: 1,
				SourceRelativePath: ".local/build/shader_profiles/a/PACK10_01.PAK",
				SourceSHA256:       profileAHash, SourceSize: int64(len(profileA)),
				ExpectedTargetSHA256BeforeActivation: baseHash,
				ExpectedTargetSHA256AfterActivation:  profileAHash,
				ExpectedTargetSHA256BeforeRollback:   profileAHash,
				SelectedMembers:                      1, RuntimeValidated: false,
			},
			{
				ProfileID: "water_shader_swater_original_code", RuleID: "water_shader_swater",
				Domain: "water_visibility", Priority: "critical", TestOrder: 2,
				SourceRelativePath: ".local/build/shader_profiles/b/PACK10_01.PAK",
				SourceSHA256:       profileBHash, SourceSize: int64(len(profileB)),
				ExpectedTargetSHA256BeforeActivation: baseHash,
				ExpectedTargetSHA256AfterActivation:  profileBHash,
				ExpectedTargetSHA256BeforeRollback:   profileBHash,
				SelectedMembers:                      1, RuntimeValidated: false,
			},
		},
	}
	configPath := filepath.Join(project, "shader_profiles.json")
	data, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return shaderProfileFixture{
		ctx:    profileCommandContext{ProjectRoot: project, GameRoot: game, ConfigPath: configPath},
		target: target, sourceA: sourceA, sourceB: sourceB, baseline: baseline,
		profileA: profileA, profileB: profileB, config: config, project: project, game: game,
	}
}

func TestQuartetShaderProfileActivationAndRollback(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	if err := activateQuartetShaderProfile(fixture.ctx, "height_fog_shader_original_code"); err != nil {
		t.Fatalf("activate: %v", err)
	}
	installed, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(installed) != string(fixture.profileA) {
		t.Fatalf("shader profile payload was not installed")
	}
	state, exists, err := readShaderProfileState(shaderProfileStatePath(fixture.project))
	if err != nil || !exists {
		t.Fatalf("state: exists=%v err=%v", exists, err)
	}
	if state.Status != "active" || state.ProfileID != "height_fog_shader_original_code" || state.RuntimeValidated {
		t.Fatalf("unexpected active shader state: %+v", state)
	}
	backup, err := secureJoin(fixture.project, state.BackupRelativePath)
	if err != nil {
		t.Fatal(err)
	}
	backupData, err := os.ReadFile(backup)
	if err != nil {
		t.Fatal(err)
	}
	if string(backupData) != string(fixture.baseline) {
		t.Fatalf("shader backup does not equal baseline")
	}
	if err := statusQuartetShaderProfile(fixture.ctx); err != nil {
		t.Fatalf("status: %v", err)
	}
	if err := rollbackQuartetShaderProfile(fixture.ctx); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	restored, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(restored) != string(fixture.baseline) {
		t.Fatalf("shader rollback did not restore exact baseline")
	}
}

func TestQuartetShaderProfileOnlyOneActive(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	if err := activateQuartetShaderProfile(fixture.ctx, "height_fog_shader_original_code"); err != nil {
		t.Fatal(err)
	}
	if err := activateQuartetShaderProfile(fixture.ctx, "water_shader_swater_original_code"); err == nil {
		t.Fatalf("second shader profile activation should be refused")
	}
	installed, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(installed) != string(fixture.profileA) {
		t.Fatalf("refused second activation changed the installed shader profile")
	}
}

func TestQuartetShaderProfileRollbackRefusesTargetDrift(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	if err := activateQuartetShaderProfile(fixture.ctx, "height_fog_shader_original_code"); err != nil {
		t.Fatal(err)
	}
	external := []byte("changed by another operation\n")
	if err := os.WriteFile(fixture.target, external, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := rollbackQuartetShaderProfile(fixture.ctx); err == nil {
		t.Fatalf("shader rollback should reject target drift")
	}
	current, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(current) != string(external) {
		t.Fatalf("refused shader rollback modified the drifted target")
	}
}

func TestQuartetShaderProfileActivationRejectsBaselineDrift(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	if err := os.WriteFile(fixture.target, []byte("not stage-27 baseline\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := activateQuartetShaderProfile(fixture.ctx, "height_fog_shader_original_code"); err == nil {
		t.Fatalf("shader activation should reject a non-baseline target")
	}
	if _, exists, err := readShaderProfileState(shaderProfileStatePath(fixture.project)); err != nil || exists {
		t.Fatalf("failed shader precondition should not create transaction state: exists=%v err=%v", exists, err)
	}
}

func TestQuartetShaderProfileActivationRejectsCorruptSource(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	if err := os.WriteFile(fixture.sourceA, []byte("corrupt shader source\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := activateQuartetShaderProfile(fixture.ctx, "height_fog_shader_original_code"); err == nil {
		t.Fatalf("shader activation should reject a corrupt source")
	}
	current, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(current) != string(fixture.baseline) {
		t.Fatalf("failed shader source validation modified target")
	}
}

func TestQuartetShaderProfileConfigRejectsRuntimeValidated(t *testing.T) {
	fixture := newShaderProfileFixture(t)
	fixture.config.Profiles[0].RuntimeValidated = true
	data, err := json.Marshal(fixture.config)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(fixture.ctx.ConfigPath, data, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadQuartetShaderProfileConfig(fixture.ctx.ConfigPath); err == nil {
		t.Fatalf("runtime-validated shader metadata should be rejected before an in-game validation update")
	}
}
