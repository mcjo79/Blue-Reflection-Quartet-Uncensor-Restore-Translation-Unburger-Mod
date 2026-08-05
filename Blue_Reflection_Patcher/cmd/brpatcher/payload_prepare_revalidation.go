package main

import (
	"fmt"
	"time"

	"local/blue-reflection-patcher/internal/model"
	"local/blue-reflection-patcher/internal/plan/payloadpreview"
)

// rebuildPayloadPreviewForPreparation is replaceable only by focused unit tests.
// Production callers always rebuild through the canonical payloadpreview.Build path.
var rebuildPayloadPreviewForPreparation = buildPayloadPreview

type payloadPreviewRevalidation struct {
	Performed                  bool
	ConfirmedPreviewPlanSHA256 string
	RebuiltPreviewPlanSHA256   string
}

func payloadPreviewPlanSHA256(preview payloadpreview.Preview) (string, error) {
	normalized := preview
	normalized.GeneratedUTC = time.Time{}
	return hashJSON(normalized)
}

func payloadPreviewSelection(preview payloadpreview.Preview) (model.SelectionResult, error) {
	if preview.Type != payloadpreview.PreviewType || preview.FormatVersion != payloadpreview.PreviewFormatVersion {
		return model.SelectionResult{}, fmt.Errorf("unsupported payload preview type/version")
	}
	if len(preview.Targets) != 1 {
		return model.SelectionResult{}, fmt.Errorf("preparation revalidation requires exactly one preview target; found %d", len(preview.Targets))
	}
	target := preview.Targets[0]
	return model.SelectionResult{
		Type:          model.SelectionType,
		FormatVersion: model.SelectionFormatVersion,
		Mode:          "transaction_prepare_revalidation",
		Targets: []model.TargetSelection{{
			TargetID:          target.TargetID,
			DisplayName:       target.DisplayName,
			Root:              target.GameRoot,
			DetectionSource:   target.DetectionSource,
			SelectedModuleIDs: append([]string(nil), target.SelectedModules...),
		}},
		Warnings: []string{},
	}, nil
}

func revalidatePayloadPreviewForPreparation(preview payloadpreview.Preview) (payloadpreview.Preview, payloadPreviewRevalidation, error) {
	selection, err := payloadPreviewSelection(preview)
	if err != nil {
		return payloadpreview.Preview{}, payloadPreviewRevalidation{}, err
	}
	confirmedPlan, err := payloadPreviewPlanSHA256(preview)
	if err != nil {
		return payloadpreview.Preview{}, payloadPreviewRevalidation{}, fmt.Errorf("fingerprint confirmed payload preview: %w", err)
	}
	rebuilt, err := rebuildPayloadPreviewForPreparation(preview.ProjectRoot, selection)
	if err != nil {
		return payloadpreview.Preview{}, payloadPreviewRevalidation{}, fmt.Errorf("rebuild canonical payload preview immediately before preparation: %w", err)
	}
	rebuiltPlan, err := payloadPreviewPlanSHA256(rebuilt)
	if err != nil {
		return payloadpreview.Preview{}, payloadPreviewRevalidation{}, fmt.Errorf("fingerprint rebuilt payload preview: %w", err)
	}
	context := payloadPreviewRevalidation{
		Performed:                  true,
		ConfirmedPreviewPlanSHA256: confirmedPlan,
		RebuiltPreviewPlanSHA256:   rebuiltPlan,
	}
	if confirmedPlan != rebuiltPlan {
		return payloadpreview.Preview{}, context, fmt.Errorf("payload plan changed after confirmation; no transaction was prepared (confirmed=%s rebuilt=%s); run payload-preview again", confirmedPlan, rebuiltPlan)
	}
	return rebuilt, context, nil
}

func prepareRevalidatedPayloadTransaction(preview payloadpreview.Preview) (transactionPrepareReport, error) {
	rebuilt, context, err := revalidatePayloadPreviewForPreparation(preview)
	if err != nil {
		return transactionPrepareReport{}, err
	}
	return preparePayloadTransactionWithRevalidation(rebuilt, context)
}
