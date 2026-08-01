package bundle

import (
	"testing"

	"local/blue-reflection-patcher/internal/model"
)

func TestRejectWholeArchiveHashDependency(t *testing.T) {
	manifest := model.BundleManifest{
		Type: model.BundleType, FormatVersion: 1, BundleID: "x", BundleVersion: "1",
		Compatibility: model.Compatibility{
			Mode: "content_aware_rebuild", RequireWholeArchiveHash: true,
			PreserveUnknownEntries: true,
		},
	}
	if err := Validate(manifest); err == nil {
		t.Fatal("expected validation error")
	}
}
