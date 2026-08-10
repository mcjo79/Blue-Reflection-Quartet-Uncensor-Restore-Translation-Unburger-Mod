//go:build windows

package main

import (
	"io"
	"os"
	"syscall"
	"unsafe"
)

type progressCoord struct {
	X int16
	Y int16
}

type progressSmallRect struct {
	Left   int16
	Top    int16
	Right  int16
	Bottom int16
}

type progressConsoleScreenBufferInfo struct {
	Size              progressCoord
	CursorPosition    progressCoord
	Attributes        uint16
	Window            progressSmallRect
	MaximumWindowSize progressCoord
}

var (
	getConsoleScreenBufferInfoProgress = kernel32.NewProc("GetConsoleScreenBufferInfo")
	setConsoleCursorPositionProgress   = kernel32.NewProc("SetConsoleCursorPosition")
)

func captureNativeProgressCursor(out io.Writer) (int16, int16, bool) {
	file, ok := out.(*os.File)
	if !ok {
		return 0, 0, false
	}
	handle := syscall.Handle(file.Fd())
	var info progressConsoleScreenBufferInfo
	result, _, _ := getConsoleScreenBufferInfoProgress.Call(uintptr(handle), uintptr(unsafe.Pointer(&info)))
	if result == 0 {
		return 0, 0, false
	}
	return info.CursorPosition.X, info.CursorPosition.Y, true
}

func restoreNativeProgressCursor(out io.Writer, x, y int16) bool {
	file, ok := out.(*os.File)
	if !ok {
		return false
	}
	handle := syscall.Handle(file.Fd())
	packed := uintptr(uint32(uint16(x)) | uint32(uint16(y))<<16)
	result, _, _ := setConsoleCursorPositionProgress.Call(uintptr(handle), packed)
	return result != 0
}
