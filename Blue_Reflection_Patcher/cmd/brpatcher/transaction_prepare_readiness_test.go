package main

import (
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

func TestDescribePayloadPreviewReadinessIncludesModuleAndArtifactReason(t *testing.T) {
	preview := payloadpreview.Preview{
		Status: "partial",
		Targets: []payloadpreview.TargetPreview{
			{
				TargetID:           "blue_reflection_original",
				Status:             "partial",
				PendingModuleCount: 1,
				Modules: []payloadpreview.ModulePreview{
					{
						ModuleID: "blue_reflection_translation",
						Ready:    false,
						Reason:   "missing verified title marker",
						Artifacts: []payloadpreview.ArtifactPreview{
							{
								RelativePath:     "DATA/PACK00_04_1.PAK",
								Status:           "missing",
								Error:            "archive is absent from the repack report",
								TransactionReady: false,
							},
						},
					},
				},
			},
		},
	}
	got := describePayloadPreviewReadiness(preview)
	for _, expected := range []string{
		"status=partial",
		"target=blue_reflection_original",
		"module=blue_reflection_translation reason=missing verified title marker",
		"artifact=DATA/PACK00_04_1.PAK detail=archive is absent from the repack report",
	} {
		if !strings.Contains(got, expected) {
			t.Fatalf("readiness description %q does not contain %q", got, expected)
		}
	}
}
