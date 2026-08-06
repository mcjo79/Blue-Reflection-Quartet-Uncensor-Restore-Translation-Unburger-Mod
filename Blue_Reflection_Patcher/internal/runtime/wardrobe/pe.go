package wardrobe

import (
	"debug/pe"
	"fmt"
	"io"
	"os"
)

type PEImage struct {
	File      *os.File
	PE        *pe.File
	Size      int64
	ImageBase uint64
}

func OpenPE(path string) (*PEImage, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	info, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}
	pf, err := pe.NewFile(f)
	if err != nil {
		f.Close()
		return nil, err
	}
	oh, ok := pf.OptionalHeader.(*pe.OptionalHeader64)
	if !ok {
		pf.Close()
		f.Close()
		return nil, fmt.Errorf("module is not PE32+ x64")
	}
	return &PEImage{File: f, PE: pf, Size: info.Size(), ImageBase: oh.ImageBase}, nil
}

func (p *PEImage) Close() { p.PE.Close(); p.File.Close() }

func (p *PEImage) RVABytes(rva uint32, n int) ([]byte, bool, error) {
	for _, s := range p.PE.Sections {
		start := s.VirtualAddress
		raw := s.Size
		if rva < start || uint64(rva)+uint64(n) > uint64(start)+uint64(raw) {
			continue
		}
		off := int64(s.Offset) + int64(rva-start)
		b := make([]byte, n)
		if _, err := p.File.ReadAt(b, off); err != nil && err != io.EOF {
			return nil, false, err
		}
		return b, true, nil
	}
	return nil, false, nil
}
