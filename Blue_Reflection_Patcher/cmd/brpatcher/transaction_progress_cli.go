package main

import (
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"

	"local/blue-reflection-patcher/internal/plan/transaction"
)

type transactionProgressRenderer struct {
	out               io.Writer
	terminal          bool
	active            bool
	started           bool
	startedAt         time.Time
	workflowStartedAt time.Time
	lastDraw          time.Time
	lastKey           string
	lastEvent         transaction.ProgressEvent
	spinner           int
	stop              chan struct{}
	done              chan struct{}
	mu                sync.Mutex
}

func newTransactionProgressRenderer(out io.Writer) *transactionProgressRenderer {
	return newTransactionProgressRendererWithWorkflowStart(out, time.Now())
}

func newTransactionProgressRendererWithWorkflowStart(out io.Writer, workflowStartedAt time.Time) *transactionProgressRenderer {
	terminal := false
	if file, ok := out.(*os.File); ok {
		if info, err := file.Stat(); err == nil {
			terminal = info.Mode()&os.ModeCharDevice != 0
		}
	}
	if os.Getenv("BRPATCHER_FORCE_PROGRESS_TTY") == "1" {
		terminal = true
	}
	if workflowStartedAt.IsZero() {
		workflowStartedAt = time.Now()
	}
	return &transactionProgressRenderer{out: out, terminal: terminal, workflowStartedAt: workflowStartedAt}
}

func (r *transactionProgressRenderer) Status(operation, phase, detail string) {
	r.Callback(transaction.ProgressEvent{Operation: operation, Phase: phase, RelativePath: detail})
}

func (r *transactionProgressRenderer) Callback(event transaction.ProgressEvent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ensureActiveLocked()
	r.lastEvent = event
	now := time.Now()
	key := event.Operation + "|" + event.Phase + "|" + event.RelativePath
	complete := event.OverallBytesTotal > 0 && event.OverallBytesDone >= event.OverallBytesTotal || event.Phase == "complete"
	interval := 200 * time.Millisecond
	if !r.terminal {
		interval = 4 * time.Second
	}
	if key == r.lastKey && !complete && !r.lastDraw.IsZero() && now.Sub(r.lastDraw) < interval {
		return
	}
	r.lastKey = key
	r.renderLocked(false)
}

func (r *transactionProgressRenderer) ensureActiveLocked() {
	if r.active {
		return
	}
	r.active = true
	r.started = false
	r.startedAt = time.Now()
	r.lastDraw = time.Time{}
	r.spinner = 0
	r.stop = make(chan struct{})
	r.done = make(chan struct{})
	stop := r.stop
	done := r.done
	go func() {
		ticker := time.NewTicker(800 * time.Millisecond)
		defer ticker.Stop()
		defer close(done)
		for {
			select {
			case <-ticker.C:
				r.mu.Lock()
				if r.active && r.stop == stop {
					r.spinner++
					r.renderLocked(true)
				}
				r.mu.Unlock()
			case <-stop:
				return
			}
		}
	}()
}

func (r *transactionProgressRenderer) renderLocked(heartbeat bool) {
	now := time.Now()
	if !r.terminal {
		if heartbeat && !r.lastDraw.IsZero() && now.Sub(r.lastDraw) < 10*time.Second {
			return
		}
		event := r.lastEvent
		fmt.Fprintf(r.out, "[%s/%s] overall %s, file %d/%d %s, path=%s, phase=%s, total=%s\n",
			strings.ToUpper(event.Operation), progressPhaseLabel(event.Phase),
			transactionPercentText(event.OverallBytesDone, event.OverallBytesTotal),
			event.FileIndex, event.FileCount,
			transactionPercentText(event.FileBytesDone, event.FileBytesTotal), event.RelativePath,
			formatElapsed(now.Sub(r.startedAt)), formatElapsed(now.Sub(r.workflowStartedAt)))
		r.lastDraw = now
		return
	}

	event := r.lastEvent
	if !r.started {
		fmt.Fprint(r.out, "\n\n\n\n\n\n\n")
		r.started = true
	}
	fmt.Fprint(r.out, "\033[7A")
	line := strings.Repeat("─", 92)
	title := transactionOperationLabel(event.Operation)
	fmt.Fprintf(r.out, "\r\033[2K%s╭─ UNBURGER · %s %s%s\n", ansiCyan+ansiBold, title, strings.Repeat("─", maxInt(1, 72-len(title))), ansiReset)
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s%-76s%s\n", ansiCyan, ansiReset, "Stage", ansiBold, compactLegacyProgress(progressPhaseLabel(event.Phase), 76), ansiReset)
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s %6s  %s\n", ansiCyan, ansiReset, "Overall", transactionProgressBar(event.OverallBytesDone, event.OverallBytesTotal, 32), transactionPercentText(event.OverallBytesDone, event.OverallBytesTotal), transactionProgressBytes(event.OverallBytesDone, event.OverallBytesTotal))
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s %6s  %s\n", ansiCyan, ansiReset, "Current", transactionProgressBar(event.FileBytesDone, event.FileBytesTotal, 32), transactionPercentText(event.FileBytesDone, event.FileBytesTotal), transactionProgressBytes(event.FileBytesDone, event.FileBytesTotal))
	fileLabel := strings.TrimSpace(event.RelativePath)
	if fileLabel == "" {
		fileLabel = fmt.Sprintf("file %d/%d", event.FileIndex, event.FileCount)
	}
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s\n", ansiCyan, ansiReset, "File", compactLegacyProgress(fileLabel, 78))
	spin := []string{"◐", "◓", "◑", "◒"}[r.spinner%4]
	fmt.Fprintf(r.out, "\r\033[2K%s│%s %-10s %s%s%s  %s  %s·%s phase elapsed %s · total elapsed %s\n", ansiCyan, ansiReset, "Activity", ansiYellow, spin, ansiReset, transactionActivityLabel(event.Phase), ansiGray, ansiReset, formatElapsed(now.Sub(r.startedAt)), formatElapsed(now.Sub(r.workflowStartedAt)))
	fmt.Fprintf(r.out, "\r\033[2K%s╰%s╯%s\n", ansiCyan, line, ansiReset)
	r.lastDraw = now
}

func (r *transactionProgressRenderer) Finish() {
	r.mu.Lock()
	if !r.active {
		r.mu.Unlock()
		return
	}
	stop, done := r.stop, r.done
	if r.terminal && r.started {
		r.spinner++
		r.renderLocked(false)
	}
	r.active = false
	r.stop = nil
	r.done = nil
	r.mu.Unlock()
	close(stop)
	<-done
	if r.terminal {
		fmt.Fprintln(r.out)
	}
}

func progressPercent(done, total int64) float64 {
	if total <= 0 {
		if done > 0 {
			return 100
		}
		return 0
	}
	value := float64(done) * 100 / float64(total)
	if value < 0 {
		return 0
	}
	if value > 100 {
		return 100
	}
	return value
}

func progressBar(percent float64, width int) string {
	if width < 1 {
		width = 1
	}
	filled := int(percent * float64(width) / 100)
	if filled < 0 {
		filled = 0
	}
	if filled > width {
		filled = width
	}
	return "[" + strings.Repeat("#", filled) + strings.Repeat("-", width-filled) + "]"
}

func transactionProgressBar(done, total int64, width int) string {
	if total <= 0 {
		return "[" + strings.Repeat("·", width) + "]"
	}
	return progressBar(progressPercent(done, total), width)
}

func transactionPercentText(done, total int64) string {
	if total <= 0 {
		return "  --  "
	}
	return fmt.Sprintf("%5.1f%%", progressPercent(done, total))
}

func transactionProgressBytes(done, total int64) string {
	if total <= 0 {
		return "waiting for measurable file work"
	}
	return fmt.Sprintf("%s / %s", formatProgressBytes(done), formatProgressBytes(total))
}

func formatProgressBytes(value int64) string {
	const (
		kiB = 1024
		miB = 1024 * kiB
		giB = 1024 * miB
	)
	switch {
	case value >= giB:
		return fmt.Sprintf("%.2f GiB", float64(value)/giB)
	case value >= miB:
		return fmt.Sprintf("%.1f MiB", float64(value)/miB)
	case value >= kiB:
		return fmt.Sprintf("%.1f KiB", float64(value)/kiB)
	default:
		return fmt.Sprintf("%d B", value)
	}
}

func progressPhaseLabel(phase string) string {
	switch phase {
	case "baseline":
		return "Preserve rollback baseline"
	case "verify_candidate":
		return "Verify final candidate"
	case "stage":
		return "Stage verified file"
	case "verify_staged":
		return "Verify staged file"
	case "verify_current":
		return "Verify installed file"
	case "verify_backup_source":
		return "Verify baseline source"
	case "backup":
		return "Create rollback backup"
	case "verify_backup":
		return "Verify rollback backup"
	case "load_state":
		return "Load managed rollback state"
	case "verify_rollback_target":
		return "Verify rollback target"
	case "reconcile_state":
		return "Publish restored managed state"
	case "verify_previous_state":
		return "Verify untouched previous-state file"
	case "verify_baseline_state":
		return "Verify untouched baseline file"
	case "baseline_restored":
		return "Rollback complete"
	case "install":
		return "Install verified file"
	case "restore":
		return "Restore original file"
	case "complete":
		return "Game-file transaction complete"
	case "publish_state":
		return "Publish installation state"
	case "verify_installed_state":
		return "Final installed-file verification"
	case "cleanup":
		return "Clean temporary transaction data"
	case "storage_cleanup":
		return "Prune obsolete patcher storage"
	case "game_files_ready":
		return "Game files installed and verified"
	default:
		if strings.TrimSpace(phase) == "" {
			return "Working"
		}
		return strings.ReplaceAll(phase, "_", " ")
	}
}

func transactionActivityLabel(phase string) string {
	switch phase {
	case "baseline":
		return "Reading current game files and preserving rollback state"
	case "verify_candidate", "verify_staged", "verify_current", "verify_backup_source", "verify_backup", "verify_previous_state", "verify_baseline_state":
		return "Reading and hashing only the data required by this safety gate"
	case "load_state":
		return "Reading rollback journal and managed-state metadata"
	case "verify_rollback_target":
		return "Starting hash-guarded rollback; unchanged files will never be overwritten blindly"
	case "reconcile_state":
		return "Recording the restored previous installation state without redundant full-file rereads"
	case "baseline_restored":
		return "Persistent baseline restored; no patcher-managed modules remain installed"
	case "stage", "backup":
		return "Writing protected transaction data"
	case "install":
		return "Replacing game file atomically"
	case "restore":
		return "Restoring preserved game file atomically"
	case "complete":
		return "File replacement phase complete"
	case "publish_state":
		return "Recording installed module and rollback state"
	case "verify_installed_state":
		return "Reading installed files for the final SHA-256 gate"
	case "cleanup":
		return "Removing temporary staged payloads"
	case "storage_cleanup":
		return "Keeping only rollback data that is still reachable from the active installation"
	case "game_files_ready":
		return "Game-file installation verified; continuing workflow"
	default:
		return "Transaction work in progress"
	}
}

func transactionOperationLabel(operation string) string {
	switch strings.ToLower(strings.TrimSpace(operation)) {
	case "prepare":
		return "SAFE INSTALLATION PREPARE"
	case "commit":
		return "INSTALL"
	case "rollback":
		return "ROLLBACK"
	case "finalize":
		return "FINAL CHECKS"
	default:
		if strings.TrimSpace(operation) == "" {
			return "TRANSACTION"
		}
		return strings.ToUpper(operation)
	}
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
