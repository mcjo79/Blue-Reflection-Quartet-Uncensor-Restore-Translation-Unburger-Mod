package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"local/blue-reflection-patcher/internal/plan/installstate"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func useSyntheticGuidedPrepare(t *testing.T) {
	t.Helper()
	original := prepareGuidedPayloadTransaction
	prepareGuidedPayloadTransaction = preparePayloadTransaction
	t.Cleanup(func() { prepareGuidedPayloadTransaction = original })
}

func TestExecuteGuidedInstallPreparesCommitsAndPublishesActiveState(t *testing.T) {
	useSyntheticGuidedPrepare(t)
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	var output bytes.Buffer
	result, err := executeGuidedPayloadAction(preview, guidedActionInstall, &output)
	if err != nil {
		t.Fatal(err)
	}
	if result.PrepareReport.Status != "prepared" || result.CommitReport.Status != "installed" {
		t.Fatalf("unexpected guided result: %+v", result)
	}
	if got, _ := os.ReadFile(target); string(got) != "translated" {
		t.Fatalf("guided install did not install payload: %q", got)
	}
	inspection, err := installstate.Inspect(state, "blue_reflection_original", game)
	if err != nil {
		t.Fatal(err)
	}
	if inspection.Status != installstate.InspectionMatchesInstalled {
		t.Fatalf("guided install did not publish active state: %+v", inspection)
	}
	journal, err := transaction.Load(result.PrepareReport.JournalPath)
	if err != nil {
		t.Fatal(err)
	}
	if journal.Status != transaction.StatusCommitted {
		t.Fatalf("unexpected journal status: %s", journal.Status)
	}
	if !strings.Contains(output.String(), "Transaction installed") {
		t.Fatalf("human output did not report installation: %s", output.String())
	}
}

func TestExecuteGuidedPrepareLeavesGameUnchanged(t *testing.T) {
	useSyntheticGuidedPrepare(t)
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	result, err := executeGuidedPayloadAction(preview, guidedActionPrepare, &bytes.Buffer{})
	if err != nil {
		t.Fatal(err)
	}
	if result.PrepareReport.Status != "prepared" || result.CommitReport.Status != "" {
		t.Fatalf("unexpected guided prepare result: %+v", result)
	}
	if got, _ := os.ReadFile(target); string(got) != "original" {
		t.Fatalf("guided prepare modified game: %q", got)
	}
	if _, exists, err := installstate.Load(state, "blue_reflection_original", game); err != nil || exists {
		t.Fatalf("guided prepare unexpectedly published active state: exists=%v err=%v", exists, err)
	}
}

func TestGuidedLineActionSelection(t *testing.T) {
	root := t.TempDir()
	game := filepath.Join(root, "game")
	state := filepath.Join(root, "state")
	payload := filepath.Join(root, "payload", "PACK01.PAK")
	target := filepath.Join(game, "DATA", "PACK01.PAK")
	mustWriteTestFile(t, payload, []byte("translated"))
	mustWriteTestFile(t, target, []byte("original"))
	sourceHash, _ := hashRegularFile(payload)
	targetHash, _ := hashRegularFile(target)
	preview := syntheticPreparePreview(game, state, payload, target, sourceHash, targetHash)

	for input, expected := range map[string]guidedPayloadAction{
		"1\n": guidedActionInstall,
		"2\n": guidedActionPrepare,
		"3\n": guidedActionCancel,
		"\n":  guidedActionCancel,
	} {
		var output bytes.Buffer
		action, err := chooseGuidedPayloadActionLine(preview, strings.NewReader(input), &output)
		if err != nil {
			t.Fatalf("input %q: %v", input, err)
		}
		if action != expected {
			t.Fatalf("input %q: got %s want %s", input, action, expected)
		}
	}
}
