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
	out       io.Writer
	terminal  bool
	started   bool
	lastDraw  time.Time
	lastKey   string
	lastEvent transaction.ProgressEvent
	mu        sync.Mutex
}

func newTransactionProgressRenderer(out io.Writer) *transactionProgressRenderer {
	terminal := false
	if file, ok := out.(*os.File); ok {
		if info, err := file.Stat(); err == nil {
			terminal = info.Mode()&os.ModeCharDevice != 0
		}
	}
	if os.Getenv("BRPATCHER_FORCE_PROGRESS_TTY") == "1" {
		terminal = true
	}
	return &transactionProgressRenderer{out: out, terminal: terminal}
}

func (r *transactionProgressRenderer) Callback(event transaction.ProgressEvent) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lastEvent = event
	now := time.Now()
	key := event.Operation + "|" + event.Phase + "|" + event.RelativePath
	complete := event.OverallBytesTotal == 0 || event.OverallBytesDone >= event.OverallBytesTotal || event.Phase == "complete"
	interval := 250 * time.Millisecond
	if !r.terminal {
		interval = 5 * time.Second
	}
	if key == r.lastKey && !complete && !r.lastDraw.IsZero() && now.Sub(r.lastDraw) < interval {
		return
	}
	r.lastKey = key
	r.lastDraw = now
	if r.terminal {
		r.drawTerminal(event)
	} else {
		r.drawPlain(event)
	}
}

func (r *transactionProgressRenderer) drawTerminal(event transaction.ProgressEvent) {
	if !r.started {
		fmt.Fprint(r.out, "\n\n")
		r.started = true
	}
	overall := progressPercent(event.OverallBytesDone, event.OverallBytesTotal)
	file := progressPercent(event.FileBytesDone, event.FileBytesTotal)
	fmt.Fprint(r.out, "\033[2A\r\033[2K")
	fmt.Fprintf(r.out, "Overall %s %6.2f%%  %s / %s  (%d/%d files)\n",
		progressBar(overall, 30), overall,
		formatProgressBytes(event.OverallBytesDone), formatProgressBytes(event.OverallBytesTotal),
		event.FileIndex, event.FileCount)
	fmt.Fprint(r.out, "\r\033[2K")
	fmt.Fprintf(r.out, "Current %s %6.2f%%  %s / %s  [%s] %s\n",
		progressBar(file, 30), file,
		formatProgressBytes(event.FileBytesDone), formatProgressBytes(event.FileBytesTotal),
		progressPhaseLabel(event.Phase), event.RelativePath)
}

func (r *transactionProgressRenderer) drawPlain(event transaction.ProgressEvent) {
	fmt.Fprintf(r.out, "[%s] overall %.2f%% (%s/%s), file %d/%d %.2f%% (%s/%s), phase=%s, path=%s\n",
		event.Operation,
		progressPercent(event.OverallBytesDone, event.OverallBytesTotal),
		formatProgressBytes(event.OverallBytesDone), formatProgressBytes(event.OverallBytesTotal),
		event.FileIndex, event.FileCount,
		progressPercent(event.FileBytesDone, event.FileBytesTotal),
		formatProgressBytes(event.FileBytesDone), formatProgressBytes(event.FileBytesTotal),
		progressPhaseLabel(event.Phase), event.RelativePath)
}

func (r *transactionProgressRenderer) Finish() {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.terminal && r.started {
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
	case "verify_current":
		return "verify installed"
	case "verify_backup":
		return "verify backup"
	case "install":
		return "install"
	case "restore":
		return "restore"
	case "complete":
		return "complete"
	default:
		return phase
	}
}
