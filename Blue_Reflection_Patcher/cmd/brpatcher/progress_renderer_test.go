package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
	"time"

	"local/blue-reflection-patcher/internal/br1rebuild"
	"local/blue-reflection-patcher/internal/plan/transaction"
)

func TestBuildProgressRendererShowsStructuredTerminalPanel(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	var out bytes.Buffer
	renderer := newBR1BuildProgressRenderer(&out)
	renderer.Callback(br1rebuild.BuildProgress{
		Phase:        "translation_verify",
		CurrentFile:  `Data/PACK11.PAK: \\script\\b1\\utility.nut`,
		CurrentDone:  64,
		CurrentTotal: 128,
		OverallDone:  512,
		OverallTotal: 1024,
	})
	renderer.Finish()
	text := out.String()
	for _, want := range []string{"UNBURGER · CONTENT BUILD", "Verify Translation", "Overall", "Current", "Activity", "elapsed"} {
		if !strings.Contains(text, want) {
			t.Fatalf("terminal build panel missing %q: %q", want, text)
		}
	}
}

func TestTransactionProgressRendererShowsBaselineActivity(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	var out bytes.Buffer
	renderer := newTransactionProgressRenderer(&out)
	renderer.Status("prepare", "baseline", "Preserving rollback baseline")
	renderer.Callback(transaction.ProgressEvent{
		Operation:         "prepare",
		Phase:             "verify_current",
		RelativePath:      "B1.dll",
		FileIndex:         1,
		FileCount:         5,
		FileBytesDone:     64,
		FileBytesTotal:    128,
		OverallBytesDone:  64,
		OverallBytesTotal: 640,
	})
	renderer.Finish()
	text := out.String()
	for _, want := range []string{"UNBURGER · SAFE INSTALLATION PREPARE", "Verify installed file", "B1.dll", "Activity", "elapsed"} {
		if !strings.Contains(text, want) {
			t.Fatalf("terminal transaction panel missing %q: %q", want, text)
		}
	}
}

func TestTransactionCompletionLabelsDoNotClaimWholeWorkflowFinished(t *testing.T) {
	if got := transactionActivityLabel("complete"); got == "Finished" || strings.Contains(strings.ToLower(got), "game is ready") {
		t.Fatalf("transaction sub-step claims the whole workflow is finished: %q", got)
	}
	if got := progressPhaseLabel("complete"); got != "Game-file transaction complete" {
		t.Fatalf("unexpected transaction completion label: %q", got)
	}
}

func TestTransactionProgressRendererShowsPostCommitFinalVerification(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	var out bytes.Buffer
	renderer := newTransactionProgressRenderer(&out)
	renderer.Callback(transaction.ProgressEvent{
		Operation:         "finalize",
		Phase:             "verify_installed_state",
		RelativePath:      "Data/PACK11.PAK",
		FileIndex:         1,
		FileCount:         5,
		FileBytesDone:     32,
		FileBytesTotal:    64,
		OverallBytesDone:  32,
		OverallBytesTotal: 320,
	})
	renderer.Finish()
	text := out.String()
	for _, want := range []string{"UNBURGER · FINAL CHECKS", "Final installed-file verification", "Data/PACK11.PAK", "final SHA-256 gate"} {
		if !strings.Contains(text, want) {
			t.Fatalf("finalization panel missing %q: %q", want, text)
		}
	}
}

func TestWindowsProgressLayoutUsesAnchoredCursorRedraw(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	t.Setenv("BRPATCHER_FORCE_WINDOWS_PROGRESS_LAYOUT", "1")
	var out bytes.Buffer
	renderer := newBR1BuildProgressRenderer(&out)
	renderer.Callback(br1rebuild.BuildProgress{Phase: "source_bundle_extract", CurrentFile: "source/DATA/PACK00_02.PAK"})
	renderer.Callback(br1rebuild.BuildProgress{Phase: "source_bundle_extract", CurrentFile: "source/DATA/PACK00_02.PAK", CurrentDone: 1, CurrentTotal: 2})
	renderer.Finish()
	text := out.String()
	if !strings.Contains(text, ansiSaveCursor) {
		t.Fatalf("Windows progress renderer did not anchor its initial cursor: %q", text)
	}
	if !strings.Contains(text, ansiRestoreCursor) {
		t.Fatalf("Windows progress renderer did not restore its anchored cursor: %q", text)
	}
	if strings.Contains(text, "\x1b[7A") {
		t.Fatalf("Windows progress renderer still uses fixed-row cursor movement: %q", text)
	}
}

func TestWindowsProgressActivityIsCompactEnoughForPanel(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_WINDOWS_PROGRESS_LAYOUT", "1")
	got := progressActivityText("Extracting and SHA-256 checking source images while writing them", 8*time.Second, 9*time.Second)
	if strings.Contains(got, "phase elapsed") || strings.Contains(got, "total elapsed") {
		t.Fatalf("Windows compact activity unexpectedly uses verbose timer labels: %q", got)
	}
	if len([]rune(got)) > 70 {
		t.Fatalf("Windows compact activity is still too wide: %d runes: %q", len([]rune(got)), got)
	}
	if !strings.Contains(got, "phase 00:08") || !strings.Contains(got, "total 00:09") {
		t.Fatalf("Windows compact activity lost timers: %q", got)
	}
}

func TestWindowsBuildProgressThrottlesRapidFullPanelRedraws(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	t.Setenv("BRPATCHER_FORCE_WINDOWS_PROGRESS_LAYOUT", "1")
	var out bytes.Buffer
	renderer := newBR1BuildProgressRenderer(&out)
	for i := int64(0); i < 20; i++ {
		renderer.Callback(br1rebuild.BuildProgress{
			Phase:        "source_bundle_extract",
			CurrentFile:  "source/DATA/PACK00_02.PAK",
			CurrentDone:  i,
			CurrentTotal: 20,
		})
	}
	renderer.Finish()
	frames := strings.Count(out.String(), "UNBURGER · CONTENT BUILD")
	if frames > 3 {
		t.Fatalf("rapid Windows callbacks repainted too many full frames: %d", frames)
	}
}

func TestWindowsTransactionProgressThrottlesRapidFileChanges(t *testing.T) {
	t.Setenv("BRPATCHER_FORCE_PROGRESS_TTY", "1")
	t.Setenv("BRPATCHER_FORCE_WINDOWS_PROGRESS_LAYOUT", "1")
	var out bytes.Buffer
	renderer := newTransactionProgressRenderer(&out)
	for i := 0; i < 20; i++ {
		renderer.Callback(transaction.ProgressEvent{
			Operation:         "prepare",
			Phase:             "stage_candidate",
			RelativePath:      fmt.Sprintf("Data/PACK%02d.PAK", i),
			FileIndex:         i + 1,
			FileCount:         20,
			FileBytesDone:     1,
			FileBytesTotal:    2,
			OverallBytesDone:  int64(i + 1),
			OverallBytesTotal: 40,
		})
	}
	renderer.Finish()
	frames := strings.Count(out.String(), "UNBURGER · SAFE INSTALLATION PREPARE")
	if frames > 3 {
		t.Fatalf("rapid Windows file changes repainted too many full transaction frames: %d", frames)
	}
}
