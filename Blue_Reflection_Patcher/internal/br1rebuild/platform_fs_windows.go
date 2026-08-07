//go:build windows

package br1rebuild

import (
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"unsafe"
)

func freeBytes(path string) (uint64, error) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return 0, err
	}
	k := syscall.NewLazyDLL("kernel32.dll").NewProc("GetDiskFreeSpaceExW")
	var avail, total, free uint64
	r, _, e := k.Call(uintptr(unsafe.Pointer(p)), uintptr(unsafe.Pointer(&avail)), uintptr(unsafe.Pointer(&total)), uintptr(unsafe.Pointer(&free)))
	if r == 0 {
		return 0, e
	}
	return avail, nil
}
func gameRunning(root string) (bool, string) {
	p := filepath.Join(root, "B1.dll")
	f, err := os.OpenFile(p, os.O_RDWR, 0)
	if err != nil {
		return true, fmt.Sprintf("B1.dll cannot be opened writable (game may be running): %v", err)
	}
	f.Close()
	return false, "B1.dll writable; no exclusive lock detected"
}
