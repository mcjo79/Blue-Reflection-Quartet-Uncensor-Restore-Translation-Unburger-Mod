//go:build windows

package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

const (
	enableProcessedInput        = 0x0001
	enableVirtualTerminalInput  = 0x0200
	enableProcessedOutput       = 0x0001
	enableVirtualTerminalOutput = 0x0004
)

var (
	kernel32       = syscall.NewLazyDLL("kernel32.dll")
	getConsoleMode = kernel32.NewProc("GetConsoleMode")
	setConsoleMode = kernel32.NewProc("SetConsoleMode")
)

func consoleMode(handle syscall.Handle) (uint32, error) {
	var mode uint32
	result, _, callErr := getConsoleMode.Call(uintptr(handle), uintptr(unsafePointer(&mode)))
	if result == 0 {
		return 0, callErr
	}
	return mode, nil
}

func setMode(handle syscall.Handle, mode uint32) error {
	result, _, callErr := setConsoleMode.Call(uintptr(handle), uintptr(mode))
	if result == 0 {
		return callErr
	}
	return nil
}

func terminalEnterRawMode(in *os.File, out *os.File) (func(), error) {
	inputHandle := syscall.Handle(in.Fd())
	outputHandle := syscall.Handle(out.Fd())
	oldInput, err := consoleMode(inputHandle)
	if err != nil {
		return nil, fmt.Errorf("read Windows input console mode: %w", err)
	}
	oldOutput, err := consoleMode(outputHandle)
	if err != nil {
		return nil, fmt.Errorf("read Windows output console mode: %w", err)
	}
	newInput := (oldInput | enableProcessedInput | enableVirtualTerminalInput) &^ uint32(0x0002|0x0004)
	newOutput := oldOutput | enableProcessedOutput | enableVirtualTerminalOutput
	if err := setMode(inputHandle, newInput); err != nil {
		return nil, fmt.Errorf("enable Windows virtual terminal input: %w", err)
	}
	if err := setMode(outputHandle, newOutput); err != nil {
		_ = setMode(inputHandle, oldInput)
		return nil, fmt.Errorf("enable Windows virtual terminal output: %w", err)
	}
	return func() {
		_ = setMode(inputHandle, oldInput)
		_ = setMode(outputHandle, oldOutput)
	}, nil
}

func unsafePointer(value *uint32) unsafe.Pointer {
	return unsafe.Pointer(value)
}
