package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type profileFixture struct {
	ctx      profileCommandContext
	target   string
	sourceA  string
	sourceB  string
	baseline []byte
	profileA []byte
	profileB []byte
	config   quartetProfileConfig
	project  string
	game     string
}

func digestBytes(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func newProfileFixture(t *testing.T) profileFixture {
	t.Helper()
	root := t.TempDir()
	project := filepath.Join(root, "project")
	game := filepath.Join(root, "game")
	if err := os.MkdirAll(filepath.Join(project, ".local", "build", "profiles", "a"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(project, ".local", "build", "profiles", "b"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(game, "Data"), 0o755); err != nil {
		t.Fatal(err)
	}
	baseline := []byte("baseline PACK11 payload\n")
	profileA := []byte("high-confidence profile payload\n")
	profileB := []byte("experimental profile payload\n")
	target := filepath.Join(game, "Data", "PACK11.PAK")
	sourceA := filepath.Join(project, ".local", "build", "profiles", "a", "PACK11.PAK")
	sourceB := filepath.Join(project, ".local", "build", "profiles", "b", "PACK11.PAK")
	for path, data := range map[string][]byte{target: baseline, sourceA: profileA, sourceB: profileB} {
		if err := os.WriteFile(path, data, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	baseHash := digestBytes(baseline)
	profileAHash := digestBytes(profileA)
	profileBHash := digestBytes(profileB)
	config := quartetProfileConfig{
		Type: profileConfigType, FormatVersion: 1, RequestToolVersion: "test",
		TransactionOwner: "core_unified_patcher", TargetRelativePath: "Data/PACK11.PAK",
		BaselineSHA256: baseHash, BaselineSize: int64(len(baseline)),
		Profiles: []quartetProfile{
			{ProfileID: "profile_a", Classification: "high", Confidence: "high", SourceRelativePath: ".local/build/profiles/a/PACK11.PAK", SourceSHA256: profileAHash, SourceSize: int64(len(profileA)), ExpectedTargetSHA256BeforeActivation: baseHash, ExpectedTargetSHA256AfterActivation: profileAHash, ExpectedTargetSHA256BeforeRollback: profileAHash, SelectedMembers: 8},
			{ProfileID: "profile_b", Classification: "experimental", Confidence: "experimental", SourceRelativePath: ".local/build/profiles/b/PACK11.PAK", SourceSHA256: profileBHash, SourceSize: int64(len(profileB)), ExpectedTargetSHA256BeforeActivation: baseHash, ExpectedTargetSHA256AfterActivation: profileBHash, ExpectedTargetSHA256BeforeRollback: profileBHash, SelectedMembers: 8},
		},
	}
	configPath := filepath.Join(project, "profiles.json")
	data, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return profileFixture{
		ctx:    profileCommandContext{ProjectRoot: project, GameRoot: game, ConfigPath: configPath},
		target: target, sourceA: sourceA, sourceB: sourceB, baseline: baseline,
		profileA: profileA, profileB: profileB, config: config, project: project, game: game,
	}
}

func TestQuartetProfileActivationAndRollback(t *testing.T) {
	fixture := newProfileFixture(t)
	if err := activateQuartetProfile(fixture.ctx, "profile_a"); err != nil {
		t.Fatalf("activate: %v", err)
	}
	installed, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(installed) != string(fixture.profileA) {
		t.Fatalf("profile payload was not installed")
	}
	state, exists, err := readProfileState(profileStatePath(fixture.project))
	if err != nil || !exists {
		t.Fatalf("state: exists=%v err=%v", exists, err)
	}
	if state.Status != "active" || state.ProfileID != "profile_a" {
		t.Fatalf("unexpected active state: %+v", state)
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
		t.Fatalf("backup does not equal baseline")
	}
	if err := statusQuartetProfile(fixture.ctx); err != nil {
		t.Fatalf("status: %v", err)
	}
	if err := activateQuartetProfile(fixture.ctx, "profile_b"); err == nil {
		t.Fatalf("second profile activation should be refused")
	}
	if err := rollbackQuartetProfile(fixture.ctx); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	restored, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(restored) != string(fixture.baseline) {
		t.Fatalf("rollback did not restore exact baseline")
	}
	state, exists, err = readProfileState(profileStatePath(fixture.project))
	if err != nil || !exists || state.Status != "rolled_back" {
		t.Fatalf("unexpected rolled-back state: exists=%v state=%+v err=%v", exists, state, err)
	}
}

func TestQuartetProfileRollbackRefusesTargetDrift(t *testing.T) {
	fixture := newProfileFixture(t)
	if err := activateQuartetProfile(fixture.ctx, "profile_a"); err != nil {
		t.Fatal(err)
	}
	external := []byte("changed by another operation\n")
	if err := os.WriteFile(fixture.target, external, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := rollbackQuartetProfile(fixture.ctx); err == nil {
		t.Fatalf("rollback should reject target drift")
	}
	current, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(current) != string(external) {
		t.Fatalf("refused rollback modified the drifted target")
	}
}

func TestQuartetProfileActivationRejectsBaselineDrift(t *testing.T) {
	fixture := newProfileFixture(t)
	if err := os.WriteFile(fixture.target, []byte("not baseline\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := activateQuartetProfile(fixture.ctx, "profile_a"); err == nil {
		t.Fatalf("activation should reject a non-baseline target")
	}
	if _, exists, err := readProfileState(profileStatePath(fixture.project)); err != nil || exists {
		t.Fatalf("failed precondition should not create transaction state: exists=%v err=%v", exists, err)
	}
}

func TestQuartetProfileActivationRejectsCorruptSource(t *testing.T) {
	fixture := newProfileFixture(t)
	if err := os.WriteFile(fixture.sourceA, []byte("corrupt source\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := activateQuartetProfile(fixture.ctx, "profile_a"); err == nil {
		t.Fatalf("activation should reject a corrupt source")
	}
	current, err := os.ReadFile(fixture.target)
	if err != nil {
		t.Fatal(err)
	}
	if string(current) != string(fixture.baseline) {
		t.Fatalf("failed source validation modified target")
	}
}
