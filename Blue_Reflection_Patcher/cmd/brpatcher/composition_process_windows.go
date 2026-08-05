//go:build windows

package main

import "syscall"

const (
	compositionProcessQueryLimitedInformation               = 0x1000
	compositionErrorInvalidParameter          syscall.Errno = 87
)

func compositionProcessAlive(pid int) (bool, error) {
	if pid <= 0 {
		return false, nil
	}
	handle, err := syscall.OpenProcess(compositionProcessQueryLimitedInformation, false, uint32(pid))
	if err == nil {
		_ = syscall.CloseHandle(handle)
		return true, nil
	}
	if err == compositionErrorInvalidParameter {
		return false, nil
	}
	if err == syscall.ERROR_ACCESS_DENIED {
		return true, nil
	}
	return false, err
}
