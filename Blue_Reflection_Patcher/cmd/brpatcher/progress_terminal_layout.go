package main

import (
	"fmt"
	"io"
	"os"
	"runtime"
	"time"
)

const (
	ansiSaveCursor    = "\x1b[s"
	ansiRestoreCursor = "\x1b[u"
	ansiClearBelow    = "\x1b[J"
)

type progressTerminalDrawState struct {
	started      bool
	nativeAnchor bool
	anchorX      int16
	anchorY      int16
}

func windowsProgressLayout() bool {
	return runtime.GOOS == "windows" || os.Getenv("BRPATCHER_FORCE_WINDOWS_PROGRESS_LAYOUT") == "1"
}

// beginProgressTerminalDraw returns true when the caller should use the legacy
// fixed-row cursor movement. On real Windows consoles we anchor the panel with
// SetConsoleCursorPosition rather than ANSI save/restore: Windows Terminal and
// conhost can differ in how ESC[s / ESC[u interacts with scrolling. A native
// cursor coordinate keeps repeated multi-line redraws in one stable region.
// Non-Windows forced-layout tests retain the ANSI fallback.
func beginProgressTerminalDraw(out io.Writer, state *progressTerminalDrawState, alreadyDrawn bool) (legacyFixedRows bool) {
	if windowsProgressLayout() {
		if !state.started {
			if x, y, ok := captureNativeProgressCursor(out); ok {
				state.nativeAnchor = true
				state.anchorX = x
				state.anchorY = y
			} else {
				fmt.Fprint(out, ansiSaveCursor)
			}
			state.started = true
		} else if alreadyDrawn {
			if state.nativeAnchor {
				if !restoreNativeProgressCursor(out, state.anchorX, state.anchorY) {
					// A console can be detached/reconfigured while a long build is
					// active. Fall back without ever emitting both restore modes.
					state.nativeAnchor = false
					fmt.Fprint(out, ansiSaveCursor)
				}
			} else {
				fmt.Fprint(out, ansiRestoreCursor)
			}
		}
		// Clear rows left by the previous frame before repainting. Each panel
		// row is also individually erased by the caller.
		fmt.Fprint(out, ansiClearBelow)
		return false
	}

	if !state.started {
		fmt.Fprint(out, "\n\n\n\n\n\n\n")
		state.started = true
	}
	return true
}

func progressActivityText(activity string, phaseElapsed, totalElapsed time.Duration) string {
	if windowsProgressLayout() {
		// Keep this complete logical row comfortably below the fixed panel
		// width. The old long label wrapped in Windows Terminal/cmd and broke
		// the fixed-row redraw accounting.
		activity = compactLegacyProgress(activity, 40)
		return fmt.Sprintf("%s  · phase %s · total %s", activity, formatElapsed(phaseElapsed), formatElapsed(totalElapsed))
	}
	return fmt.Sprintf("%s  · phase elapsed %s · total elapsed %s", activity, formatElapsed(phaseElapsed), formatElapsed(totalElapsed))
}
