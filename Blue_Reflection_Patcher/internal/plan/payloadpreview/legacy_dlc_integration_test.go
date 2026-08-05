package payloadpreview

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func legacyDLCTestDigest(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func legacyDLCWriteFile(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
}

type legacyDLCFixtureData struct {
	Project   string
	Game      string
	Selection model.SelectionResult
	Manifest  legacyDLCManifest
	Policy    legacyDLCPolicy
}

func legacyDLCManifestFixture(t *testing.T, members []string, generation int) legacyDLCFixtureData {
	t.Helper()
	project := t.TempDir()
	game := filepath.Join(project, "game")
	legacyDLCWriteFile(t, filepath.Join(project, "workstreams/core/VERSION"), []byte("test\n"))
	legacyDLCWriteFile(t, filepath.Join(project, "Blue_Reflection_Patcher/go.mod"), []byte("module fixture\n"))
	report := map[string]any{"status": "ok", "archives": []any{}}
	reportData, err := json.Marshal(report)
	if err != nil {
		t.Fatal(err)
	}
	legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(repackReportRelative)), reportData)

	policy, err := loadLegacyDLCPolicy()
	if err != nil {
		t.Fatal(err)
	}
	family, ok := legacyDLCFamily(policy, "bkn_dry")
	if !ok {
		t.Fatal("missing bkn_dry policy")
	}
	evidenceRelative := ".local/reports/quartet_legacy_dlc/evidence/generation.json"
	evidenceData := []byte(`{"type":"fixture_evidence"}` + "\n")
	legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(evidenceRelative)), evidenceData)

	manifest := legacyDLCManifest{
		Type: legacyDLCManifestType, FormatVersion: legacyDLCManifestFormatVersion,
		FamilyID: "bkn_dry", Generation: generation, Members: append([]string{}, members...),
		SourceKind: legacyDLCSourceKind, TargetID: quartetTargetID,
		Transaction: legacyDLCManifestTransaction{Group: family.TransactionGroup, AllOrNone: true, CommitEnabled: false},
		Provenance: legacyDLCManifestProvenance{
			WorkstreamID: "quartet_legacy_dlc", WorkstreamVersion: "fixture",
			EvidenceRelativePath: evidenceRelative, EvidenceSHA256: legacyDLCTestDigest(evidenceData),
		},
		Authorization: legacyDLCManifestAuthorization{CoreHandoffReady: true},
		Artifacts:     []legacyDLCManifestArtifact{},
	}

	for index, policyArtifact := range family.Artifacts {
		candidate := []byte("candidate-generation-" + string(rune('0'+generation)) + "-artifact-" + string(rune('0'+index)))
		baseline := []byte("baseline-artifact-" + string(rune('0'+index)))
		candidateRelative := filepath.ToSlash(filepath.Join(policy.CandidateRoot, "fixture", filepath.Base(policyArtifact.TargetPath)))
		legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(candidateRelative)), candidate)
		legacyDLCWriteFile(t, filepath.Join(game, filepath.FromSlash(policyArtifact.TargetPath)), baseline)
		added, changed, removed, err := expectedLegacyDLCMemberDelta(family, policyArtifact, members)
		if err != nil {
			t.Fatal(err)
		}
		manifest.Artifacts = append(manifest.Artifacts, legacyDLCManifestArtifact{
			TargetPath: policyArtifact.TargetPath, Operation: policyArtifact.Operation,
			CandidateRelativePath: candidateRelative, CandidateSize: int64(len(candidate)), CandidateSHA256: legacyDLCTestDigest(candidate),
			BaselineSize: int64(len(baseline)), BaselineSHA256: legacyDLCTestDigest(baseline),
			MemberDelta: legacyDLCManifestMemberDelta{Added: added, Changed: changed, Removed: removed},
		})
	}
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(policy.ManifestRelativePath)), append(data, '\n'))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: quartetTargetID, DisplayName: "Quartet", Root: game, DetectionSource: "test", SelectedModuleIDs: []string{"quartet_legacy_dlc"}}}}
	return legacyDLCFixtureData{Project: project, Game: game, Selection: selection, Manifest: manifest, Policy: policy}
}

func rewriteLegacyDLCManifest(t *testing.T, fixture legacyDLCFixtureData, mutate func(*legacyDLCManifest)) {
	t.Helper()
	manifest := fixture.Manifest
	manifest.Members = append([]string{}, fixture.Manifest.Members...)
	manifest.Artifacts = append([]legacyDLCManifestArtifact{}, fixture.Manifest.Artifacts...)
	mutate(&manifest)
	data, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	legacyDLCWriteFile(t, filepath.Join(fixture.Project, filepath.FromSlash(fixture.Policy.ManifestRelativePath)), append(data, '\n'))
}

func findLegacyDLCModule(t *testing.T, preview Preview) ModulePreview {
	t.Helper()
	if len(preview.Targets) != 1 || len(preview.Targets[0].Modules) != 1 {
		t.Fatalf("unexpected preview shape: %+v", preview)
	}
	return preview.Targets[0].Modules[0]
}

func TestLegacyDLCGenericManifestGenerationsUseOneAdapter(t *testing.T) {
	cases := []struct {
		name       string
		generation int
		members    []string
		added      int
	}{
		{name: "pc00_only_compatibility", generation: 1, members: []string{"costume_pc00_bkn"}, added: 2},
		{name: "pc00_pc01", generation: 2, members: []string{"costume_pc00_bkn", "costume_pc01_bkn"}, added: 4},
		{name: "synthetic_generation_three", generation: 3, members: []string{"costume_pc00_bkn", "costume_pc01_bkn", "costume_pc02_bkn"}, added: 6},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			fixture := legacyDLCManifestFixture(t, test.members, test.generation)
			preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
			if err != nil {
				t.Fatal(err)
			}
			module := findLegacyDLCModule(t, preview)
			if preview.CommitEnabled || preview.Status != "ready" || !module.Ready || len(module.Artifacts) != 2 {
				t.Fatalf("unexpected preview: %+v", preview)
			}
			contract, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game)
			if err != nil {
				t.Fatal(err)
			}
			if contract.Generation != test.generation || !sameStrings(contract.Members, test.members) || len(contract.Artifacts[0].AddedMembers) != test.added {
				t.Fatalf("generic generation was not preserved: %+v", contract)
			}
		})
	}
}

func TestLegacyDLCBuildRejectsMissingCandidateAllOrNone(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	if err := os.Remove(filepath.Join(fixture.Project, filepath.FromSlash(fixture.Manifest.Artifacts[1].CandidateRelativePath))); err != nil {
		t.Fatal(err)
	}
	preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	module := findLegacyDLCModule(t, preview)
	if module.Ready || preview.Status != "not_ready" {
		t.Fatalf("missing candidate was accepted: %+v", preview)
	}
	for _, artifact := range module.Artifacts {
		if artifact.TransactionReady {
			t.Fatalf("all-or-none gate failed: %+v", module.Artifacts)
		}
	}
}

func TestLegacyDLCBuildRejectsChangedBaseline(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	legacyDLCWriteFile(t, filepath.Join(fixture.Game, "Data/PACK10_02.PAK"), []byte("changed"))
	preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	if findLegacyDLCModule(t, preview).Ready {
		t.Fatal("changed baseline was accepted")
	}
}

func TestLegacyDLCBuildRejectsChangedCandidateSHA256(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	legacyDLCWriteFile(t, filepath.Join(fixture.Project, filepath.FromSlash(fixture.Manifest.Artifacts[0].CandidateRelativePath)), []byte("tampered"))
	preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	if findLegacyDLCModule(t, preview).Ready {
		t.Fatal("changed candidate was accepted")
	}
}

func TestLegacyDLCBuildRejectsSymlinkCandidate(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	path := filepath.Join(fixture.Project, filepath.FromSlash(fixture.Manifest.Artifacts[0].CandidateRelativePath))
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(fixture.Project, "real-candidate")
	legacyDLCWriteFile(t, target, []byte("candidate"))
	if err := os.Symlink(target, path); err != nil {
		t.Fatal(err)
	}
	preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	if findLegacyDLCModule(t, preview).Ready {
		t.Fatal("symlink candidate was accepted")
	}
}

func TestLegacyDLCBuildRejectsSymlinkManifest(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	path := filepath.Join(fixture.Project, filepath.FromSlash(fixture.Policy.ManifestRelativePath))
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(fixture.Project, "manifest-target.json")
	legacyDLCWriteFile(t, target, data)
	if err := os.Symlink(target, path); err != nil {
		t.Fatal(err)
	}
	preview, err := Build(fixture.Project, filepath.Join(fixture.Project, "state"), fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	if findLegacyDLCModule(t, preview).Ready {
		t.Fatal("symlink manifest was accepted")
	}
}

func TestLegacyDLCManifestRejectsAdditionalArtifact(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts = append(manifest.Artifacts, legacyDLCManifestArtifact{TargetPath: "Data/PACK11.PAK", Operation: "replace"})
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("additional artifact was accepted")
	}
}

func TestLegacyDLCManifestRejectsDuplicateTarget(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts[1].TargetPath = manifest.Artifacts[0].TargetPath
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("duplicate target was accepted")
	}
}

func TestLegacyDLCManifestRejectsNonCanonicalTarget(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts[0].TargetPath = "Data/../Data/PACK10_02.PAK"
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("non-canonical target was accepted")
	}
}

func TestLegacyDLCManifestRejectsCandidateOutsideAllowedRoot(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts[0].CandidateRelativePath = ".local/reports/quartet_legacy_dlc/not-a-candidate.pak"
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("candidate outside the allowed build root was accepted")
	}
}

func TestLegacyDLCManifestRejectsWrongOperation(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts[0].Operation = "add"
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("unsupported operation was accepted")
	}
}

func TestLegacyDLCManifestRejectsWrongSourceKind(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) { manifest.SourceKind = "translation_report" })
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("wrong source kind was accepted")
	}
}

func TestLegacyDLCManifestRejectsCommitEnabled(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) { manifest.Transaction.CommitEnabled = true })
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("commit-enabled manifest was accepted")
	}
}

func TestLegacyDLCManifestRejectsEmptyArtifacts(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn"}, 1)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) { manifest.Artifacts = nil })
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("empty artifact list was accepted")
	}
}

func TestLegacyDLCManifestRejectsUndeclaredMemberDelta(t *testing.T) {
	fixture := legacyDLCManifestFixture(t, []string{"costume_pc00_bkn", "costume_pc01_bkn"}, 2)
	rewriteLegacyDLCManifest(t, fixture, func(manifest *legacyDLCManifest) {
		manifest.Artifacts[0].MemberDelta.Added = append(manifest.Artifacts[0].MemberDelta.Added, "data/b1/x64/character/pc09/unrelated.g1t")
	})
	if _, err := LoadLegacyDLCCompositionContract(fixture.Project, fixture.Game); err == nil {
		t.Fatal("undeclared member delta was accepted")
	}
}

func TestLegacyDLCOldSpecificHandoffIsNotAProductionBinding(t *testing.T) {
	project := t.TempDir()
	game := filepath.Join(project, "game")
	legacyDLCWriteFile(t, filepath.Join(project, "workstreams/core/VERSION"), []byte("test\n"))
	legacyDLCWriteFile(t, filepath.Join(project, "Blue_Reflection_Patcher/go.mod"), []byte("module fixture\n"))
	legacyDLCWriteFile(t, filepath.Join(project, filepath.FromSlash(repackReportRelative)), []byte(`{"status":"ok","archives":[]}`))
	legacyDLCWriteFile(t, filepath.Join(project, ".local/reports/quartet_legacy_dlc/bkn_dry_core_integration_handoff_evidence/DLC_BKN_DRY_CORE_INTEGRATION_HANDOFF.json"), []byte(`{"type":"br_quartet_legacy_dlc_dry_bkn_core_integration_handoff"}`))
	selection := model.SelectionResult{Targets: []model.TargetSelection{{TargetID: quartetTargetID, Root: game, SelectedModuleIDs: []string{"quartet_legacy_dlc"}}}}
	preview, err := Build(project, filepath.Join(project, "state"), selection)
	if err != nil {
		t.Fatal(err)
	}
	if findLegacyDLCModule(t, preview).Ready {
		t.Fatal("old PC-specific handoff remained an active production binding")
	}
}

func TestLegacyDLCCatalogDeclaresBoundedProductionArtifacts(t *testing.T) {
	specs, err := LoadCatalog()
	if err != nil {
		t.Fatal(err)
	}
	for _, spec := range specs {
		if spec.ModuleID == "quartet_legacy_dlc" && spec.TargetID == quartetTargetID {
			if spec.SourceKind != legacyDLCSourceKind || spec.ConnectionStatus != "connected_preview_only" || len(spec.Artifacts) != 2 || spec.Artifacts[0].RelativePath != "Data/PACK10_02.PAK" || spec.Artifacts[1].RelativePath != "Data/PACK12.PAK" {
				t.Fatalf("unexpected catalog declaration: %+v", spec)
			}
			return
		}
	}
	t.Fatal("legacy DLC catalog mapping is missing")
}

func TestLegacyDLCAdapterHasNoConcreteGenerationBindings(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate test source")
	}
	root := filepath.Dir(file)
	for _, name := range []string{"legacy_dlc.go", "legacy_dlc_policy.json"} {
		data, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			t.Fatal(err)
		}
		text := strings.ToLower(string(data))
		for _, forbidden := range []string{"pc00", "pc01", "bcce30ec2e7b5c4253b8626578569a568d0579ad03075cff29ba03cdd03f7798", "145882cbe4c6d13ef03e7c92ece3082b2d4d0d000e1d2298e4a9c543cc2b9b9b"} {
			if strings.Contains(text, forbidden) {
				t.Fatalf("production adapter contains a concrete generation binding %q in %s", forbidden, name)
			}
		}
	}
}
