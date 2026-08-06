//go:build linux

package main

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
)

const ficloneIOCTL = 0x40049409

func tryReflinkFile(source, destination string, mode os.FileMode) (bool, error) {
	src, err := os.Open(source)
	if err != nil {
		return false, err
	}
	defer src.Close()
	dst, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, mode)
	if err != nil {
		return false, err
	}
	success := false
	defer func() {
		_ = dst.Close()
		if !success {
			_ = os.Remove(destination)
		}
	}()
	_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, dst.Fd(), uintptr(ficloneIOCTL), src.Fd())
	if errno != 0 {
		if errors.Is(errno, syscall.EXDEV) || errors.Is(errno, syscall.EOPNOTSUPP) || errors.Is(errno, syscall.ENOTTY) || errors.Is(errno, syscall.EINVAL) || errors.Is(errno, syscall.ENOSYS) {
			return false, nil
		}
		return false, errno
	}
	if err := dst.Chmod(mode); err != nil {
		return false, err
	}
	if err := dst.Sync(); err != nil {
		return false, err
	}
	if err := dst.Close(); err != nil {
		return false, err
	}
	if err := fsyncDirectory(filepath.Dir(destination)); err != nil {
		return false, err
	}
	success = true
	return true, nil
}
