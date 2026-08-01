package plan

import (
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func TestDefaultsAndExplicitOptionalModule(t *testing.T) {
	manifest := model.BundleManifest{
		BundleID: "bundle", BundleVersion: "1",
		Modules: []model.BundleModule{
			{ModuleID: "translation", SupportedTargets: []string{"quartet"}, DefaultTargets: []string{"quartet"}},
			{ModuleID: "restoration", SupportedTargets: []string{"quartet"}},
		},
		Operations: []model.PatchOperation{
			{OperationID: "a", ModuleID: "translation", TargetID: "quartet", ArchivePath: "A", EntryPath: "x"},
			{OperationID: "b", ModuleID: "restoration", TargetID: "quartet", ArchivePath: "B", EntryPath: "y"},
		},
	}
	detections := []model.Detection{{TargetID: "quartet", DisplayName: "Quartet", Root: "/game"}}
	defaultPlan, err := Build(manifest, detections, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(defaultPlan.Targets) != 1 || len(defaultPlan.Targets[0].Modules) != 1 || defaultPlan.Targets[0].Modules[0] != "translation" {
		t.Fatalf("unexpected default plan: %+v", defaultPlan)
	}
	explicitPlan, err := Build(manifest, detections, []string{"restoration"})
	if err != nil {
		t.Fatal(err)
	}
	if len(explicitPlan.Targets[0].Modules) != 1 || explicitPlan.Targets[0].Modules[0] != "restoration" {
		t.Fatalf("unexpected explicit plan: %+v", explicitPlan)
	}
}
