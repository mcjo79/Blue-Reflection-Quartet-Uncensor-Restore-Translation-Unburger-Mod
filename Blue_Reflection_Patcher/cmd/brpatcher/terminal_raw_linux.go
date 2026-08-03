//go:build linux

package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

func terminalEnterRawMode(in *os.File, out *os.File) (func(), error) {
	fd := int(in.Fd())
	var oldState syscall.Termios
	if _, _, errno := syscall.Syscall6(
		syscall.SYS_IOCTL,
		uintptr(fd),
		uintptr(syscall.TCGETS),
		uintptr(unsafe.Pointer(&oldState)),
		0, 0, 0,
	); errno != 0 {
		return nil, fmt.Errorf("read terminal settings: %w", errno)
	}
	raw := oldState
	raw.Lflag &^= syscall.ECHO | syscall.ICANON
	raw.Iflag &^= syscall.IXON | syscall.ICRNL
	raw.Cc[syscall.VMIN] = 1
	raw.Cc[syscall.VTIME] = 0
	if _, _, errno := syscall.Syscall6(
		syscall.SYS_IOCTL,
		uintptr(fd),
		uintptr(syscall.TCSETS),
		uintptr(unsafe.Pointer(&raw)),
		0, 0, 0,
	); errno != 0 {
		return nil, fmt.Errorf("enable raw terminal mode: %w", errno)
	}
	return func() {
		_, _, _ = syscall.Syscall6(
			syscall.SYS_IOCTL,
			uintptr(fd),
			uintptr(syscall.TCSETS),
			uintptr(unsafe.Pointer(&oldState)),
			0, 0, 0,
		)
	}, nil
}
