//go:build windows

package wardrobe

import (
	"fmt"
	"strings"
	"syscall"
	"unsafe"
)

const (
	processVMOperation      = 0x0008
	processVMRead           = 0x0010
	processVMWrite          = 0x0020
	processQueryInformation = 0x0400
	threadSuspendResume     = 0x0002
	th32csSnapProcess       = 0x00000002
	th32csSnapThread        = 0x00000004
	th32csSnapModule        = 0x00000008
	th32csSnapModule32      = 0x00000010
	memCommit               = 0x00001000
	memReserve              = 0x00002000
	memRelease              = 0x00008000
	pageReadWrite           = 0x04
	pageExecuteRead         = 0x20
	pageExecuteReadWrite    = 0x40
	invalidHandleValue      = ^uintptr(0)
)

var (
	kernel32                     = syscall.NewLazyDLL("kernel32.dll")
	procOpenProcess              = kernel32.NewProc("OpenProcess")
	procReadProcessMemory        = kernel32.NewProc("ReadProcessMemory")
	procWriteProcessMemory       = kernel32.NewProc("WriteProcessMemory")
	procVirtualAllocEx           = kernel32.NewProc("VirtualAllocEx")
	procVirtualFreeEx            = kernel32.NewProc("VirtualFreeEx")
	procVirtualProtectEx         = kernel32.NewProc("VirtualProtectEx")
	procFlushInstructionCache    = kernel32.NewProc("FlushInstructionCache")
	procCreateToolhelp32Snapshot = kernel32.NewProc("CreateToolhelp32Snapshot")
	procModule32FirstW           = kernel32.NewProc("Module32FirstW")
	procModule32NextW            = kernel32.NewProc("Module32NextW")
	procProcess32FirstW          = kernel32.NewProc("Process32FirstW")
	procProcess32NextW           = kernel32.NewProc("Process32NextW")
	procThread32First            = kernel32.NewProc("Thread32First")
	procThread32Next             = kernel32.NewProc("Thread32Next")
	procOpenThread               = kernel32.NewProc("OpenThread")
	procSuspendThread            = kernel32.NewProc("SuspendThread")
	procResumeThread             = kernel32.NewProc("ResumeThread")
	procCloseHandle              = kernel32.NewProc("CloseHandle")
)

type moduleEntry32W struct {
	Size, ModuleID, ProcessID, GlobalUsage, ProcessUsage uint32
	BaseAddr                                             uintptr
	BaseSize                                             uint32
	Module                                               syscall.Handle
	ModuleName                                           [256]uint16
	ExePath                                              [260]uint16
}
type processEntry32W struct {
	Size, Usage, ProcessID             uint32
	DefaultHeapID                      uintptr
	ModuleID, Threads, ParentProcessID uint32
	PriClassBase                       int32
	Flags                              uint32
	ExeFile                            [260]uint16
}
type threadEntry32 struct {
	Size, Usage, ThreadID, OwnerProcessID uint32
	BasePri, DeltaPri                     int32
	Flags                                 uint32
}

func closeHandle(h syscall.Handle) {
	if h != 0 && uintptr(h) != invalidHandleValue {
		procCloseHandle.Call(uintptr(h))
	}
}
func winErr(name string, r1 uintptr, e error) error {
	if r1 != 0 {
		return nil
	}
	if e != nil && e != syscall.Errno(0) {
		return fmt.Errorf("%s: %w", name, e)
	}
	return fmt.Errorf("%s failed", name)
}
func FindProcessByName(name string) (uint32, error) {
	h, _, e := procCreateToolhelp32Snapshot.Call(th32csSnapProcess, 0)
	if h == invalidHandleValue {
		return 0, fmt.Errorf("CreateToolhelp32Snapshot(process): %w", e)
	}
	defer closeHandle(syscall.Handle(h))
	var pe processEntry32W
	pe.Size = uint32(unsafe.Sizeof(pe))
	r, _, e := procProcess32FirstW.Call(h, uintptr(unsafe.Pointer(&pe)))
	if err := winErr("Process32FirstW", r, e); err != nil {
		return 0, err
	}
	wanted := strings.ToLower(name)
	for {
		if strings.ToLower(syscall.UTF16ToString(pe.ExeFile[:])) == wanted {
			return pe.ProcessID, nil
		}
		r, _, _ = procProcess32NextW.Call(h, uintptr(unsafe.Pointer(&pe)))
		if r == 0 {
			break
		}
	}
	return 0, fmt.Errorf("process %q not found", name)
}
func findModuleBase(pid uint32, name string) (uint64, error) {
	h, _, e := procCreateToolhelp32Snapshot.Call(th32csSnapModule|th32csSnapModule32, uintptr(pid))
	if h == invalidHandleValue {
		return 0, fmt.Errorf("CreateToolhelp32Snapshot(module): %w", e)
	}
	defer closeHandle(syscall.Handle(h))
	var me moduleEntry32W
	me.Size = uint32(unsafe.Sizeof(me))
	r, _, e := procModule32FirstW.Call(h, uintptr(unsafe.Pointer(&me)))
	if err := winErr("Module32FirstW", r, e); err != nil {
		return 0, err
	}
	wanted := strings.ToLower(name)
	for {
		if strings.ToLower(syscall.UTF16ToString(me.ModuleName[:])) == wanted {
			return uint64(me.BaseAddr), nil
		}
		r, _, _ = procModule32NextW.Call(h, uintptr(unsafe.Pointer(&me)))
		if r == 0 {
			break
		}
	}
	return 0, fmt.Errorf("module %q not found in pid %d", name, pid)
}

type suspendedThread struct{ h syscall.Handle }

func suspendProcessThreads(pid uint32) ([]suspendedThread, error) {
	snap, _, e := procCreateToolhelp32Snapshot.Call(th32csSnapThread, 0)
	if snap == invalidHandleValue {
		return nil, fmt.Errorf("CreateToolhelp32Snapshot(thread): %w", e)
	}
	defer closeHandle(syscall.Handle(snap))
	var te threadEntry32
	te.Size = uint32(unsafe.Sizeof(te))
	r, _, e := procThread32First.Call(snap, uintptr(unsafe.Pointer(&te)))
	if err := winErr("Thread32First", r, e); err != nil {
		return nil, err
	}
	var out []suspendedThread
	target := 0
	for {
		if te.OwnerProcessID == pid {
			target++
			h, _, oe := procOpenThread.Call(threadSuspendResume, 0, uintptr(te.ThreadID))
			if h == 0 {
				resumeThreads(out)
				return nil, fmt.Errorf("OpenThread(%d): %w", te.ThreadID, oe)
			}
			prev, _, se := procSuspendThread.Call(h)
			if prev == ^uintptr(0) {
				closeHandle(syscall.Handle(h))
				resumeThreads(out)
				return nil, fmt.Errorf("SuspendThread(%d): %w", te.ThreadID, se)
			}
			out = append(out, suspendedThread{syscall.Handle(h)})
		}
		r, _, _ = procThread32Next.Call(snap, uintptr(unsafe.Pointer(&te)))
		if r == 0 {
			break
		}
	}
	if target == 0 || len(out) != target {
		resumeThreads(out)
		return nil, fmt.Errorf("failed to suspend complete target thread set: %d/%d", len(out), target)
	}
	return out, nil
}
func resumeThreads(t []suspendedThread) {
	for i := len(t) - 1; i >= 0; i-- {
		procResumeThread.Call(uintptr(t[i].h))
		closeHandle(t[i].h)
	}
}

type windowsMemory struct{ process syscall.Handle }

func (m *windowsMemory) Read(addr uint64, size int) ([]byte, error) {
	if size == 0 {
		return []byte{}, nil
	}
	b := make([]byte, size)
	var n uintptr
	r, _, e := procReadProcessMemory.Call(uintptr(m.process), uintptr(addr), uintptr(unsafe.Pointer(&b[0])), uintptr(size), uintptr(unsafe.Pointer(&n)))
	if r == 0 || n != uintptr(size) {
		if e != nil && e != syscall.Errno(0) {
			return nil, fmt.Errorf("ReadProcessMemory 0x%x: %w", addr, e)
		}
		return nil, fmt.Errorf("ReadProcessMemory 0x%x: short read %d/%d", addr, n, size)
	}
	return b, nil
}
func (m *windowsMemory) Write(addr uint64, data []byte) error {
	if len(data) == 0 {
		return nil
	}
	var n uintptr
	r, _, e := procWriteProcessMemory.Call(uintptr(m.process), uintptr(addr), uintptr(unsafe.Pointer(&data[0])), uintptr(len(data)), uintptr(unsafe.Pointer(&n)))
	if r == 0 || n != uintptr(len(data)) {
		if e != nil && e != syscall.Errno(0) {
			return fmt.Errorf("WriteProcessMemory 0x%x: %w", addr, e)
		}
		return fmt.Errorf("WriteProcessMemory 0x%x: short write %d/%d", addr, n, len(data))
	}
	return nil
}
func (m *windowsMemory) AllocateNear(moduleBase uint64, size int) (uint64, error) {
	const step = uint64(0x04000000)
	const maxDelta = uint64(0x70000000)
	for delta := step; delta <= maxDelta; delta += step {
		c := []uint64{moduleBase + delta}
		if moduleBase > delta {
			c = append(c, moduleBase-delta)
		}
		for _, hint := range c {
			hint &= ^uint64(0xffff)
			r, _, _ := procVirtualAllocEx.Call(uintptr(m.process), uintptr(hint), uintptr(size), memCommit|memReserve, pageReadWrite)
			if r != 0 {
				return uint64(r), nil
			}
		}
	}
	return 0, fmt.Errorf("VirtualAllocEx could not allocate rel32-reachable storage")
}
func (m *windowsMemory) Free(addr uint64) error {
	r, _, e := procVirtualFreeEx.Call(uintptr(m.process), uintptr(addr), 0, memRelease)
	if r == 0 && e != nil && e != syscall.Errno(0) {
		return fmt.Errorf("VirtualFreeEx 0x%x: %w", addr, e)
	}
	return nil
}
func (m *windowsMemory) ProtectRWX(addr uint64, size int) (func() error, error) {
	var old uint32
	r, _, e := procVirtualProtectEx.Call(uintptr(m.process), uintptr(addr), uintptr(size), pageExecuteReadWrite, uintptr(unsafe.Pointer(&old)))
	if r == 0 {
		return nil, fmt.Errorf("VirtualProtectEx RWX 0x%x: %w", addr, e)
	}
	return func() error {
		var ignored uint32
		rr, _, ee := procVirtualProtectEx.Call(uintptr(m.process), uintptr(addr), uintptr(size), uintptr(old), uintptr(unsafe.Pointer(&ignored)))
		if rr == 0 {
			return fmt.Errorf("VirtualProtectEx restore 0x%x: %w", addr, ee)
		}
		return nil
	}, nil
}
func (m *windowsMemory) SetExecutable(addr uint64, size int) error {
	var old uint32
	r, _, e := procVirtualProtectEx.Call(uintptr(m.process), uintptr(addr), uintptr(size), pageExecuteRead, uintptr(unsafe.Pointer(&old)))
	if r == 0 {
		return fmt.Errorf("VirtualProtectEx RX 0x%x: %w", addr, e)
	}
	return nil
}
func (m *windowsMemory) Flush(addr uint64, size int) error {
	r, _, e := procFlushInstructionCache.Call(uintptr(m.process), uintptr(addr), uintptr(size))
	if r == 0 && e != nil && e != syscall.Errno(0) {
		return fmt.Errorf("FlushInstructionCache 0x%x: %w", addr, e)
	}
	return nil
}
func ApplyToProcess(pid uint32, profile TargetProfile, records RecordSet) (ApplyReport, error) {
	report := ApplyReport{Type: "br_runtime_wardrobe_apply", FormatVersion: 2, Capability: CapabilityID, ProcessID: pid, SaveMutationPerformed: false, OnDiskModuleModified: false}
	if err := profile.Validate(); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	if err := records.Validate(profile); err != nil {
		report.Status = "failed"
		report.Errors = append(report.Errors, err.Error())
		return report, nil
	}
	access := uintptr(processVMOperation | processVMRead | processVMWrite | processQueryInformation)
	h, _, e := procOpenProcess.Call(access, 0, uintptr(pid))
	if h == 0 {
		return report, fmt.Errorf("OpenProcess(%d): %w", pid, e)
	}
	defer closeHandle(syscall.Handle(h))
	base, err := findModuleBase(pid, profile.ModuleName)
	if err != nil {
		return report, err
	}
	threads, err := suspendProcessThreads(pid)
	if err != nil {
		return report, err
	}
	defer resumeThreads(threads)
	mem := &windowsMemory{process: syscall.Handle(h)}
	applied, err := ApplyWithMemory(mem, base, profile, records)
	applied.ProcessID = pid
	return applied, err
}
