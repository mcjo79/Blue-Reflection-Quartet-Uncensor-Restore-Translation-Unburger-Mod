package br1rebuild

import (
	"bufio"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const (
	pakHeaderSize = 16
	a18NameSize   = 128
	a18KeySize    = 20
	a18EntrySize  = 168
	a22NameSize   = 128
	a22KeySize    = 32
	a22EntrySize  = 184
	ioChunk       = 8 << 20
)

var a22MasterKeys = []struct {
	name string
	key  []byte
}{
	{"", nil},
	{"A23", []byte("dGGKXLHLuCJwv8aBc3YQX6X6sREVPchs")},
	{"A24", []byte("fyrixtT9AhA4v0cFahgMcgVwxFrry42A")},
	{"A25", []byte("vh0WESTtbeBuTwWusr4EVusMi4TbLmjQ")},
	{"A26", []byte("xpFLmgBWJSFFgMFg3XUgs7B7AgYJhyFJ")},
	{"A27", []byte("EGkUyYzPidcRx5yTecqk5AYJeSzzc5BR")},
	{"A28", []byte("ivZBFzn82RVuYnmgXfeFEgk33ALZcZDP")},
}

var printablePath = regexp.MustCompile(`^[\x20-\x7e]+$`)

type ArchiveEntry struct {
	Index     int
	Name      string
	Size      uint32
	Key       []byte
	Offset    uint64
	Flags     uint64
	Extra     uint32
	Encoded   bool
	rawHeader []byte
}

type ArchiveReader struct {
	Path        string
	File        *os.File
	Flags       uint32
	Entries     []ArchiveEntry
	DataBase    int64
	KeySize     int
	EntrySize   int
	Master      []byte
	MasterLabel string
	format      string
}

func OpenA18(path string) (*ArchiveReader, error) { return openPak(path, "a18") }
func OpenA22(path string) (*ArchiveReader, error) { return openPak(path, "a22") }

func openPak(path, format string) (*ArchiveReader, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	fail := func(e error) (*ArchiveReader, error) { f.Close(); return nil, e }
	hdr := make([]byte, pakHeaderSize)
	if _, err := io.ReadFull(f, hdr); err != nil {
		return fail(err)
	}
	ver := binary.LittleEndian.Uint32(hdr[0:4])
	n := binary.LittleEndian.Uint32(hdr[4:8])
	hs := binary.LittleEndian.Uint32(hdr[8:12])
	flags := binary.LittleEndian.Uint32(hdr[12:16])
	if ver != 0x20000 || hs != pakHeaderSize {
		return fail(fmt.Errorf("%s: unsupported PAK header version=0x%x header=%d", path, ver, hs))
	}
	p := &ArchiveReader{Path: path, File: f, Flags: flags, format: format}
	switch format {
	case "a18":
		p.KeySize = a18KeySize
		p.EntrySize = a18EntrySize
	case "a22":
		p.KeySize = a22KeySize
		p.EntrySize = a22EntrySize
	default:
		return fail(fmt.Errorf("unknown PAK format"))
	}
	if n > 2_000_000 {
		return fail(fmt.Errorf("implausible PAK entry count %d", n))
	}
	table := make([]byte, int(n)*p.EntrySize)
	if _, err := io.ReadFull(f, table); err != nil {
		return fail(err)
	}
	p.DataBase = int64(pakHeaderSize) + int64(len(table))
	if format == "a22" {
		p.Master, p.MasterLabel = detectA22Master(table, int(n), flags)
	}
	p.Entries = make([]ArchiveEntry, 0, n)
	zeroKey := make([]byte, p.KeySize)
	for i := 0; i < int(n); i++ {
		raw := append([]byte(nil), table[i*p.EntrySize:(i+1)*p.EntrySize]...)
		e := ArchiveEntry{Index: i, rawHeader: raw}
		nameRaw := raw[:128]
		e.Size = binary.LittleEndian.Uint32(raw[128:132])
		e.Key = append([]byte(nil), raw[132:132+p.KeySize]...)
		if format == "a18" {
			e.Offset = binary.LittleEndian.Uint64(raw[152:160])
			e.Flags = binary.LittleEndian.Uint64(raw[160:168])
		} else {
			e.Extra = binary.LittleEndian.Uint32(raw[164:168])
			e.Offset = binary.LittleEndian.Uint64(raw[168:176])
			e.Flags = binary.LittleEndian.Uint64(raw[176:184])
		}
		e.Encoded = (flags&0x10) != 0 || !bytesEqual(e.Key, zeroKey)
		dec := append([]byte(nil), nameRaw...)
		if e.Encoded {
			xorInPlace(dec, effectiveKey(e.Key, p.Master), 0)
		}
		if z := indexByte(dec, 0); z >= 0 {
			dec = dec[:z]
		}
		e.Name = string(dec)
		if !strings.HasPrefix(e.Name, `\`) || !printablePath.MatchString(e.Name) {
			return fail(fmt.Errorf("%s: entry %d filename failed decode (%q); wrong format/master", path, i, e.Name))
		}
		p.Entries = append(p.Entries, e)
	}
	st, err := f.Stat()
	if err != nil {
		return fail(err)
	}
	var end int64 = p.DataBase
	for _, e := range p.Entries {
		x := p.DataBase + int64(e.Offset) + int64(e.Size)
		if x > end {
			end = x
		}
	}
	if end > st.Size() {
		return fail(fmt.Errorf("%s: entry data runs past EOF (%d > %d)", path, end, st.Size()))
	}
	return p, nil
}

func detectA22Master(table []byte, n int, flags uint32) ([]byte, string) {
	bestScore := -1
	var best []byte
	label := ""
	limit := n
	if limit > 256 {
		limit = 256
	}
	for _, mk := range a22MasterKeys {
		score := 0
		for i := 0; i < limit; i++ {
			raw := table[i*a22EntrySize : (i+1)*a22EntrySize]
			key := raw[132:164]
			name := append([]byte(nil), raw[:128]...)
			if (flags&0x10) != 0 || !allZero(key) {
				xorInPlace(name, effectiveKey(key, mk.key), 0)
			}
			if z := indexByte(name, 0); z >= 0 {
				name = name[:z]
			}
			s := string(name)
			if strings.HasPrefix(s, `\`) && printablePath.MatchString(s) {
				score++
			}
		}
		if score > bestScore {
			bestScore = score
			best = append([]byte(nil), mk.key...)
			label = mk.name
		}
	}
	return best, label
}

func (p *ArchiveReader) Close() error {
	if p == nil || p.File == nil {
		return nil
	}
	return p.File.Close()
}
func (p *ArchiveReader) Find(name string) (ArchiveEntry, bool) {
	for _, e := range p.Entries {
		if strings.EqualFold(e.Name, name) {
			return e, true
		}
	}
	return ArchiveEntry{}, false
}
func (p *ArchiveReader) Read(e ArchiveEntry) ([]byte, error) {
	b := make([]byte, e.Size)
	if _, err := p.File.ReadAt(b, p.DataBase+int64(e.Offset)); err != nil {
		return nil, err
	}
	if e.Encoded {
		xorInPlace(b, effectiveKey(e.Key, p.Master), 0)
	}
	return b, nil
}
func (p *ArchiveReader) PlainDigest(e ArchiveEntry) (string, error) { return p.digest(e, true, nil) }
func (p *ArchiveReader) RawDigest(e ArchiveEntry) (string, error)   { return p.digest(e, false, nil) }
func (p *ArchiveReader) plainDigestWithProgress(e ArchiveEntry, onProgress func(int64, int64)) (string, error) {
	return p.digest(e, true, onProgress)
}
func (p *ArchiveReader) rawDigestWithProgress(e ArchiveEntry, onProgress func(int64, int64)) (string, error) {
	return p.digest(e, false, onProgress)
}
func (p *ArchiveReader) digest(e ArchiveEntry, plain bool, onProgress func(int64, int64)) (string, error) {
	h := sha256.New()
	remaining := int64(e.Size)
	off := p.DataBase + int64(e.Offset)
	phase := 0
	buf := make([]byte, ioChunk)
	key := effectiveKey(e.Key, p.Master)
	var processed int64
	for remaining > 0 {
		n := int64(len(buf))
		if n > remaining {
			n = remaining
		}
		got, err := p.File.ReadAt(buf[:n], off)
		if err != nil && !(errors.Is(err, io.EOF) && got > 0) {
			return "", err
		}
		chunk := buf[:got]
		if plain && e.Encoded {
			xorInPlace(chunk, key, phase)
			phase = (phase + got) % len(key)
		}
		h.Write(chunk)
		remaining -= int64(got)
		off += int64(got)
		processed += int64(got)
		if onProgress != nil {
			onProgress(processed, int64(e.Size))
		}
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func effectiveKey(key, master []byte) []byte {
	out := append([]byte(nil), key...)
	if len(master) > 0 {
		for i := range out {
			out[i] ^= master[i%len(master)]
		}
	}
	return out
}
func xorInPlace(b, key []byte, phase int) {
	if len(key) == 0 {
		return
	}
	for i := range b {
		b[i] ^= key[(phase+i)%len(key)]
	}
}
func allZero(b []byte) bool {
	for _, x := range b {
		if x != 0 {
			return false
		}
	}
	return true
}
func bytesEqual(a, b []byte) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
func indexByte(b []byte, v byte) int {
	for i, x := range b {
		if x == v {
			return i
		}
	}
	return -1
}

type ArchiveInput interface {
	Size() int64
	WriteEncrypted(w io.Writer, dstKey []byte) error
	PlainSHA256() (string, error)
}

type FileEntry struct {
	Path      string
	SizeBytes int64
}

func NewFileEntry(path string) (FileEntry, error) {
	info, err := os.Stat(path)
	if err != nil {
		return FileEntry{}, err
	}
	if !info.Mode().IsRegular() {
		return FileEntry{}, fmt.Errorf("archive input is not a regular file: %s", path)
	}
	return FileEntry{Path: path, SizeBytes: info.Size()}, nil
}

func (s FileEntry) Size() int64 { return s.SizeBytes }
func (s FileEntry) WriteEncrypted(w io.Writer, key []byte) error {
	f, err := os.Open(s.Path)
	if err != nil {
		return err
	}
	defer f.Close()
	buf := make([]byte, ioChunk)
	phase := 0
	for {
		n, readErr := f.Read(buf)
		if n > 0 {
			chunk := append([]byte(nil), buf[:n]...)
			xorInPlace(chunk, key, phase)
			if len(key) > 0 {
				phase = (phase + n) % len(key)
			}
			if _, err := w.Write(chunk); err != nil {
				return err
			}
		}
		if errors.Is(readErr, io.EOF) {
			return nil
		}
		if readErr != nil {
			return readErr
		}
	}
}
func (s FileEntry) PlainSHA256() (string, error) {
	f, err := os.Open(s.Path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.CopyBuffer(h, f, make([]byte, ioChunk)); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

type MemoryEntry struct{ Data []byte }

func (s MemoryEntry) Size() int64 { return int64(len(s.Data)) }
func (s MemoryEntry) WriteEncrypted(w io.Writer, key []byte) error {
	b := append([]byte(nil), s.Data...)
	xorInPlace(b, key, 0)
	_, e := w.Write(b)
	return e
}
func (s MemoryEntry) PlainSHA256() (string, error) {
	h := sha256.Sum256(s.Data)
	return hex.EncodeToString(h[:]), nil
}

type CrossFormatEntry struct {
	Pak   *ArchiveReader
	Entry ArchiveEntry
}

func (s CrossFormatEntry) Size() int64 { return int64(s.Entry.Size) }
func (s CrossFormatEntry) WriteEncrypted(w io.Writer, dstKey []byte) error {
	return transcodeEntry(s.Pak, s.Entry, w, dstKey)
}
func (s CrossFormatEntry) PlainSHA256() (string, error) { return s.Pak.PlainDigest(s.Entry) }

func transcodeEntry(src *ArchiveReader, e ArchiveEntry, w io.Writer, dstKey []byte) error {
	remaining := int64(e.Size)
	off := src.DataBase + int64(e.Offset)
	sphase, dphase := 0, 0
	buf := make([]byte, ioChunk)
	srcKey := effectiveKey(e.Key, src.Master)
	for remaining > 0 {
		n := int64(len(buf))
		if n > remaining {
			n = remaining
		}
		got, err := src.File.ReadAt(buf[:n], off)
		if err != nil && !(errors.Is(err, io.EOF) && got > 0) {
			return err
		}
		chunk := buf[:got]
		if e.Encoded {
			xorInPlace(chunk, srcKey, sphase)
			sphase = (sphase + got) % len(srcKey)
		}
		xorInPlace(chunk, dstKey, dphase)
		dphase = (dphase + got) % len(dstKey)
		if _, err := w.Write(chunk); err != nil {
			return err
		}
		remaining -= int64(got)
		off += int64(got)
	}
	return nil
}

type ArchiveEdits struct {
	Replacements map[string]ArchiveInput
	Additions    map[string]ArchiveInput
}
type ArchiveRewriteStats struct {
	EntriesBefore, EntriesAfter, Replaced, Added int
	SizeBefore, SizeAfter                        int64
	OutputSHA256                                 string
}
type ArchiveAuditResult struct {
	Checked, Changed, Unchanged int
	Problems                    []string
}

type ByteProgressFunc func(phase, name string, done, total int64)
type byteProgress = ByteProgressFunc

func RewriteA22(srcPath, dstPath string, patch ArchiveEdits, progress byteProgress) (ArchiveRewriteStats, error) {
	p, err := OpenA22(srcPath)
	if err != nil {
		return ArchiveRewriteStats{}, err
	}
	defer p.Close()
	if patch.Replacements == nil {
		patch.Replacements = map[string]ArchiveInput{}
	}
	if patch.Additions == nil {
		patch.Additions = map[string]ArchiveInput{}
	}
	by := map[string]ArchiveEntry{}
	for _, e := range p.Entries {
		by[strings.ToLower(e.Name)] = e
	}
	repl := map[string]ArchiveInput{}
	for n, s := range patch.Replacements {
		k := strings.ToLower(n)
		e, ok := by[k]
		if !ok {
			return ArchiveRewriteStats{}, fmt.Errorf("no such entry to replace: %s", n)
		}
		repl[e.Name] = s
	}
	adds := map[string]ArchiveInput{}
	for n, s := range patch.Additions {
		if _, ok := by[strings.ToLower(n)]; ok {
			return ArchiveRewriteStats{}, fmt.Errorf("entry already exists: %s", n)
		}
		adds[n] = s
	}
	if len(p.Entries) == 0 {
		return ArchiveRewriteStats{}, fmt.Errorf("empty A22 archive")
	}
	template := p.Entries[0]
	newRawTemplate := append([]byte(nil), template.rawHeader...)
	newKey := effectiveKey(template.Key, p.Master)
	type item struct {
		src    *ArchiveEntry
		name   string
		source ArchiveInput
		size   int64
		key    []byte
		off    uint64
		raw    []byte
	}
	plan := make([]item, 0, len(p.Entries)+len(adds))
	var dataOff uint64
	for i := range p.Entries {
		e := p.Entries[i]
		it := item{src: &e, name: e.Name, size: int64(e.Size), raw: append([]byte(nil), e.rawHeader...)}
		if s, ok := repl[e.Name]; ok {
			it.source = s
			it.size = s.Size()
			if e.Encoded {
				it.key = effectiveKey(e.Key, p.Master)
			} else {
				it.key = make([]byte, 32)
			}
		}
		it.off = dataOff
		dataOff += uint64(it.size)
		plan = append(plan, it)
	}
	names := make([]string, 0, len(adds))
	for n := range adds {
		names = append(names, n)
	}
	sort.Slice(names, func(i, j int) bool { return strings.ToLower(names[i]) < strings.ToLower(names[j]) })
	for _, n := range names {
		s := adds[n]
		raw := append([]byte(nil), newRawTemplate...)
		encodedName := make([]byte, 128)
		copy(encodedName, []byte(n))
		xorInPlace(encodedName, newKey, 0)
		copy(raw[:128], encodedName)
		binary.LittleEndian.PutUint32(raw[128:132], uint32(s.Size()))
		binary.LittleEndian.PutUint64(raw[168:176], dataOff)
		plan = append(plan, item{name: n, source: s, size: s.Size(), key: newKey, off: dataOff, raw: raw})
		dataOff += uint64(s.Size())
	}
	for i := range plan {
		binary.LittleEndian.PutUint32(plan[i].raw[128:132], uint32(plan[i].size))
		binary.LittleEndian.PutUint64(plan[i].raw[168:176], plan[i].off)
	}
	out, err := os.Create(dstPath)
	if err != nil {
		return ArchiveRewriteStats{}, err
	}
	ok := false
	defer func() {
		out.Close()
		if !ok {
			os.Remove(dstPath)
		}
	}()
	outputHash := sha256.New()
	bw := bufio.NewWriterSize(io.MultiWriter(out, outputHash), 8<<20)
	hdr := make([]byte, 16)
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(plan)))
	binary.LittleEndian.PutUint32(hdr[8:12], 16)
	binary.LittleEndian.PutUint32(hdr[12:16], p.Flags)
	if _, err := bw.Write(hdr); err != nil {
		return ArchiveRewriteStats{}, err
	}
	for _, it := range plan {
		if _, err := bw.Write(it.raw); err != nil {
			return ArchiveRewriteStats{}, err
		}
	}
	var total int64
	for _, it := range plan {
		total += it.size
	}
	var done int64
	for _, it := range plan {
		if it.source == nil {
			if err := copyRaw(p, it.src, bw, func(n int) {
				done += int64(n)
				if progress != nil {
					progress("build", it.name, done, total)
				}
			}); err != nil {
				return ArchiveRewriteStats{}, err
			}
		} else {
			cw := &countWriter{w: bw, onWrite: func(n int) {
				done += int64(n)
				if progress != nil {
					progress("build", it.name, done, total)
				}
			}}
			if err := it.source.WriteEncrypted(cw, it.key); err != nil {
				return ArchiveRewriteStats{}, err
			}
		}
	}
	if err := bw.Flush(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	if err := out.Sync(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	if err := out.Close(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	ok = true
	st1, _ := os.Stat(srcPath)
	st2, _ := os.Stat(dstPath)
	return ArchiveRewriteStats{
		EntriesBefore: len(p.Entries), EntriesAfter: len(plan), Replaced: len(repl), Added: len(adds),
		SizeBefore: st1.Size(), SizeAfter: st2.Size(), OutputSHA256: hex.EncodeToString(outputHash.Sum(nil)),
	}, nil
}

type countWriter struct {
	w       io.Writer
	onWrite func(int)
}

func (c *countWriter) Write(b []byte) (int, error) {
	n, e := c.w.Write(b)
	if n > 0 && c.onWrite != nil {
		c.onWrite(n)
	}
	return n, e
}
func copyRaw(p *ArchiveReader, e *ArchiveEntry, w io.Writer, on func(int)) error {
	remaining := int64(e.Size)
	off := p.DataBase + int64(e.Offset)
	buf := make([]byte, ioChunk)
	for remaining > 0 {
		n := int64(len(buf))
		if n > remaining {
			n = remaining
		}
		got, err := p.File.ReadAt(buf[:n], off)
		if err != nil && !(errors.Is(err, io.EOF) && got > 0) {
			return err
		}
		if _, err := w.Write(buf[:got]); err != nil {
			return err
		}
		if on != nil {
			on(got)
		}
		remaining -= int64(got)
		off += int64(got)
	}
	return nil
}

func AuditA22Rewrite(srcPath, dstPath string, expectedAdded map[string]string, replacements map[string]ArchiveInput, progress byteProgress) (ArchiveAuditResult, error) {
	a, err := OpenA22(srcPath)
	if err != nil {
		return ArchiveAuditResult{}, err
	}
	defer a.Close()
	b, err := OpenA22(dstPath)
	if err != nil {
		return ArchiveAuditResult{}, err
	}
	defer b.Close()
	am, bm := map[string]ArchiveEntry{}, map[string]ArchiveEntry{}
	for _, e := range a.Entries {
		am[strings.ToLower(e.Name)] = e
	}
	for _, e := range b.Entries {
		bm[strings.ToLower(e.Name)] = e
	}
	res := ArchiveAuditResult{}
	for n := range expectedAdded {
		if _, ok := bm[strings.ToLower(n)]; !ok {
			res.Problems = append(res.Problems, "missing added entry: "+n)
		}
	}
	for k, e := range bm {
		if _, ok := am[k]; !ok {
			found := false
			for n := range expectedAdded {
				if strings.EqualFold(n, e.Name) {
					found = true
					break
				}
			}
			if !found {
				res.Problems = append(res.Problems, "unexpected added entry: "+e.Name)
			}
		}
	}
	for k, e := range am {
		if _, ok := bm[k]; !ok {
			res.Problems = append(res.Problems, "entry lost: "+e.Name)
		}
	}
	names := make([]string, 0, len(bm))
	for k := range bm {
		names = append(names, k)
	}
	sort.Strings(names)
	var done int64
	var total int64
	for _, k := range names {
		total += int64(bm[k].Size)
	}
	digestRange := func(reader *ArchiveReader, entry ArchiveEntry, plain bool, displayName string, base, span int64) (string, error) {
		onProgress := func(processed, entryTotal int64) {
			if progress == nil {
				return
			}
			scaled := base
			if entryTotal > 0 && span > 0 {
				scaled += processed * span / entryTotal
			}
			progress("verify", displayName, min64(scaled, total), total)
		}
		if plain {
			return reader.plainDigestWithProgress(entry, onProgress)
		}
		return reader.rawDigestWithProgress(entry, onProgress)
	}
	for _, k := range names {
		be := bm[k]
		var isAdded bool
		var wantAdd string
		for n, d := range expectedAdded {
			if strings.EqualFold(n, be.Name) {
				isAdded = true
				wantAdd = d
				break
			}
		}
		isRepl := false
		var repl ArchiveInput
		for n, s := range replacements {
			if strings.EqualFold(n, be.Name) {
				isRepl = true
				repl = s
				break
			}
		}
		if isAdded {
			got, e := digestRange(b, be, true, be.Name, done, int64(be.Size))
			if e != nil {
				return res, e
			}
			if got != wantAdd {
				res.Problems = append(res.Problems, "added entry digest mismatch: "+be.Name)
			}
			res.Changed++
		} else if isRepl {
			want, e := repl.PlainSHA256()
			if e != nil {
				return res, e
			}
			got, e := digestRange(b, be, true, be.Name, done, int64(be.Size))
			if e != nil {
				return res, e
			}
			if got != want {
				res.Problems = append(res.Problems, "replaced entry digest mismatch: "+be.Name)
			}
			res.Changed++
		} else {
			ae, ok := am[k]
			if !ok {
				continue
			}
			if ae.Size != be.Size {
				res.Problems = append(res.Problems, "unintended size change: "+be.Name)
			} else if bytesEqual(ae.Key, be.Key) && ae.Encoded == be.Encoded {
				half := int64(be.Size) / 2
				ha, e := digestRange(a, ae, false, be.Name, done, half)
				if e != nil {
					return res, e
				}
				hb, e := digestRange(b, be, false, be.Name, done+half, int64(be.Size)-half)
				if e != nil {
					return res, e
				}
				if ha != hb {
					res.Problems = append(res.Problems, "unintended raw change: "+be.Name)
				} else {
					res.Unchanged++
				}
			} else {
				half := int64(be.Size) / 2
				ha, e := digestRange(a, ae, true, be.Name, done, half)
				if e != nil {
					return res, e
				}
				hb, e := digestRange(b, be, true, be.Name, done+half, int64(be.Size)-half)
				if e != nil {
					return res, e
				}
				if ha != hb {
					res.Problems = append(res.Problems, "unintended plaintext change: "+be.Name)
				} else {
					res.Unchanged++
				}
			}
		}
		done += int64(be.Size)
		if progress != nil {
			progress("verify", be.Name, done, total)
		}
		res.Checked++
	}
	return res, nil
}

// RewriteA18 performs the same member-preserving surgical rewrite as RewriteA22
// while retaining the A18 entry-table layout used by the first BLUE REFLECTION.
func RewriteA18(srcPath, dstPath string, patch ArchiveEdits, progress byteProgress) (ArchiveRewriteStats, error) {
	p, err := OpenA18(srcPath)
	if err != nil {
		return ArchiveRewriteStats{}, err
	}
	defer p.Close()
	if patch.Replacements == nil {
		patch.Replacements = map[string]ArchiveInput{}
	}
	if patch.Additions == nil {
		patch.Additions = map[string]ArchiveInput{}
	}
	by := map[string]ArchiveEntry{}
	for _, e := range p.Entries {
		by[strings.ToLower(e.Name)] = e
	}
	repl := map[string]ArchiveInput{}
	for n, s := range patch.Replacements {
		k := strings.ToLower(n)
		e, ok := by[k]
		if !ok {
			return ArchiveRewriteStats{}, fmt.Errorf("no such entry to replace: %s", n)
		}
		repl[e.Name] = s
	}
	adds := map[string]ArchiveInput{}
	for n, s := range patch.Additions {
		if _, ok := by[strings.ToLower(n)]; ok {
			return ArchiveRewriteStats{}, fmt.Errorf("entry already exists: %s", n)
		}
		adds[n] = s
	}
	if len(p.Entries) == 0 {
		return ArchiveRewriteStats{}, fmt.Errorf("empty A18 archive")
	}
	template := p.Entries[0]
	newRawTemplate := append([]byte(nil), template.rawHeader...)
	newKey := effectiveKey(template.Key, nil)
	type item struct {
		src    *ArchiveEntry
		name   string
		source ArchiveInput
		size   int64
		key    []byte
		off    uint64
		raw    []byte
	}
	plan := make([]item, 0, len(p.Entries)+len(adds))
	var dataOff uint64
	for i := range p.Entries {
		e := p.Entries[i]
		it := item{src: &e, name: e.Name, size: int64(e.Size), raw: append([]byte(nil), e.rawHeader...)}
		if s, ok := repl[e.Name]; ok {
			it.source = s
			it.size = s.Size()
			if e.Encoded {
				it.key = effectiveKey(e.Key, nil)
			} else {
				it.key = make([]byte, a18KeySize)
			}
		}
		it.off = dataOff
		dataOff += uint64(it.size)
		plan = append(plan, it)
	}
	names := make([]string, 0, len(adds))
	for n := range adds {
		names = append(names, n)
	}
	sort.Slice(names, func(i, j int) bool { return strings.ToLower(names[i]) < strings.ToLower(names[j]) })
	for _, n := range names {
		s := adds[n]
		raw := append([]byte(nil), newRawTemplate...)
		encodedName := make([]byte, a18NameSize)
		copy(encodedName, []byte(n))
		if template.Encoded {
			xorInPlace(encodedName, newKey, 0)
		}
		copy(raw[:a18NameSize], encodedName)
		binary.LittleEndian.PutUint32(raw[128:132], uint32(s.Size()))
		binary.LittleEndian.PutUint64(raw[152:160], dataOff)
		plan = append(plan, item{name: n, source: s, size: s.Size(), key: newKey, off: dataOff, raw: raw})
		dataOff += uint64(s.Size())
	}
	for i := range plan {
		binary.LittleEndian.PutUint32(plan[i].raw[128:132], uint32(plan[i].size))
		binary.LittleEndian.PutUint64(plan[i].raw[152:160], plan[i].off)
	}
	out, err := os.Create(dstPath)
	if err != nil {
		return ArchiveRewriteStats{}, err
	}
	ok := false
	defer func() {
		out.Close()
		if !ok {
			os.Remove(dstPath)
		}
	}()
	outputHash := sha256.New()
	bw := bufio.NewWriterSize(io.MultiWriter(out, outputHash), 8<<20)
	hdr := make([]byte, pakHeaderSize)
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(plan)))
	binary.LittleEndian.PutUint32(hdr[8:12], pakHeaderSize)
	binary.LittleEndian.PutUint32(hdr[12:16], p.Flags)
	if _, err := bw.Write(hdr); err != nil {
		return ArchiveRewriteStats{}, err
	}
	for _, it := range plan {
		if _, err := bw.Write(it.raw); err != nil {
			return ArchiveRewriteStats{}, err
		}
	}
	var total int64
	for _, it := range plan {
		total += it.size
	}
	var done int64
	for _, it := range plan {
		if it.source == nil {
			if err := copyRaw(p, it.src, bw, func(n int) {
				done += int64(n)
				if progress != nil {
					progress("build", it.name, done, total)
				}
			}); err != nil {
				return ArchiveRewriteStats{}, err
			}
		} else {
			cw := &countWriter{w: bw, onWrite: func(n int) {
				done += int64(n)
				if progress != nil {
					progress("build", it.name, done, total)
				}
			}}
			if err := it.source.WriteEncrypted(cw, it.key); err != nil {
				return ArchiveRewriteStats{}, err
			}
		}
	}
	if err := bw.Flush(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	if err := out.Sync(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	if err := out.Close(); err != nil {
		return ArchiveRewriteStats{}, err
	}
	ok = true
	st1, _ := os.Stat(srcPath)
	st2, _ := os.Stat(dstPath)
	return ArchiveRewriteStats{
		EntriesBefore: len(p.Entries), EntriesAfter: len(plan), Replaced: len(repl), Added: len(adds),
		SizeBefore: st1.Size(), SizeAfter: st2.Size(), OutputSHA256: hex.EncodeToString(outputHash.Sum(nil)),
	}, nil
}

func AuditA18Rewrite(srcPath, dstPath string, expectedAdded map[string]string, replacements map[string]ArchiveInput, progress byteProgress) (ArchiveAuditResult, error) {
	return auditArchiveRewrite(srcPath, dstPath, expectedAdded, replacements, progress, OpenA18)
}

func auditArchiveRewrite(srcPath, dstPath string, expectedAdded map[string]string, replacements map[string]ArchiveInput, progress byteProgress, opener func(string) (*ArchiveReader, error)) (ArchiveAuditResult, error) {
	a, err := opener(srcPath)
	if err != nil {
		return ArchiveAuditResult{}, err
	}
	defer a.Close()
	b, err := opener(dstPath)
	if err != nil {
		return ArchiveAuditResult{}, err
	}
	defer b.Close()
	am, bm := map[string]ArchiveEntry{}, map[string]ArchiveEntry{}
	for _, e := range a.Entries {
		am[strings.ToLower(e.Name)] = e
	}
	for _, e := range b.Entries {
		bm[strings.ToLower(e.Name)] = e
	}
	res := ArchiveAuditResult{}
	for n := range expectedAdded {
		if _, ok := bm[strings.ToLower(n)]; !ok {
			res.Problems = append(res.Problems, "missing added entry: "+n)
		}
	}
	for k, e := range bm {
		if _, ok := am[k]; !ok {
			found := false
			for n := range expectedAdded {
				if strings.EqualFold(n, e.Name) {
					found = true
					break
				}
			}
			if !found {
				res.Problems = append(res.Problems, "unexpected added entry: "+e.Name)
			}
		}
	}
	for k, e := range am {
		if _, ok := bm[k]; !ok {
			res.Problems = append(res.Problems, "entry lost: "+e.Name)
		}
	}
	names := make([]string, 0, len(bm))
	for k := range bm {
		names = append(names, k)
	}
	sort.Strings(names)
	var done, total int64
	for _, k := range names {
		total += int64(bm[k].Size)
	}
	digestRange := func(reader *ArchiveReader, entry ArchiveEntry, plain bool, displayName string, base, span int64) (string, error) {
		onProgress := func(processed, entryTotal int64) {
			if progress == nil {
				return
			}
			scaled := base
			if entryTotal > 0 && span > 0 {
				scaled += processed * span / entryTotal
			}
			progress("verify", displayName, min64(scaled, total), total)
		}
		if plain {
			return reader.plainDigestWithProgress(entry, onProgress)
		}
		return reader.rawDigestWithProgress(entry, onProgress)
	}
	for _, k := range names {
		be := bm[k]
		isAdded := false
		wantAdd := ""
		for n, d := range expectedAdded {
			if strings.EqualFold(n, be.Name) {
				isAdded = true
				wantAdd = d
				break
			}
		}
		isRepl := false
		var repl ArchiveInput
		for n, s := range replacements {
			if strings.EqualFold(n, be.Name) {
				isRepl = true
				repl = s
				break
			}
		}
		if isAdded {
			got, e := digestRange(b, be, true, be.Name, done, int64(be.Size))
			if e != nil {
				return res, e
			}
			if got != wantAdd {
				res.Problems = append(res.Problems, "added entry digest mismatch: "+be.Name)
			}
			res.Changed++
		} else if isRepl {
			want, e := repl.PlainSHA256()
			if e != nil {
				return res, e
			}
			got, e := digestRange(b, be, true, be.Name, done, int64(be.Size))
			if e != nil {
				return res, e
			}
			if got != want {
				res.Problems = append(res.Problems, "replaced entry digest mismatch: "+be.Name)
			}
			res.Changed++
		} else if ae, ok := am[k]; ok {
			if ae.Size != be.Size {
				res.Problems = append(res.Problems, "unintended size change: "+be.Name)
			} else if bytesEqual(ae.Key, be.Key) && ae.Encoded == be.Encoded {
				half := int64(be.Size) / 2
				ha, e := digestRange(a, ae, false, be.Name, done, half)
				if e != nil {
					return res, e
				}
				hb, e := digestRange(b, be, false, be.Name, done+half, int64(be.Size)-half)
				if e != nil {
					return res, e
				}
				if ha != hb {
					res.Problems = append(res.Problems, "unintended raw change: "+be.Name)
				} else {
					res.Unchanged++
				}
			} else {
				half := int64(be.Size) / 2
				ha, e := digestRange(a, ae, true, be.Name, done, half)
				if e != nil {
					return res, e
				}
				hb, e := digestRange(b, be, true, be.Name, done+half, int64(be.Size)-half)
				if e != nil {
					return res, e
				}
				if ha != hb {
					res.Problems = append(res.Problems, "unintended plaintext change: "+be.Name)
				} else {
					res.Unchanged++
				}
			}
		}
		done += int64(be.Size)
		if progress != nil {
			progress("verify", be.Name, done, total)
		}
		res.Checked++
	}
	return res, nil
}

// WriteReducedA22SourceImage creates a structurally valid A22 image containing
// only the selected source members. It preserves each selected member's raw
// encrypted bytes and header metadata; only table-relative offsets and the
// archive entry count are rewritten. This is intended for local source bundles,
// not for modifying a live game archive.
func WriteReducedA22SourceImage(srcPath, dstPath string, keep func(string) bool) ([]ArchiveEntry, error) {
	p, err := OpenA22(srcPath)
	if err != nil {
		return nil, err
	}
	defer p.Close()
	selected := make([]ArchiveEntry, 0)
	for _, e := range p.Entries {
		if keep == nil || keep(e.Name) {
			selected = append(selected, e)
		}
	}
	if len(selected) == 0 {
		return nil, fmt.Errorf("cannot write empty reduced A22 source image: %s", srcPath)
	}
	if err := os.MkdirAll(filepath.Dir(dstPath), 0o755); err != nil {
		return nil, err
	}
	out, err := os.Create(dstPath)
	if err != nil {
		return nil, err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(dstPath)
		}
	}()
	outputHash := sha256.New()
	bw := bufio.NewWriterSize(io.MultiWriter(out, outputHash), 8<<20)
	hdr := make([]byte, pakHeaderSize)
	binary.LittleEndian.PutUint32(hdr[0:4], 0x20000)
	binary.LittleEndian.PutUint32(hdr[4:8], uint32(len(selected)))
	binary.LittleEndian.PutUint32(hdr[8:12], pakHeaderSize)
	binary.LittleEndian.PutUint32(hdr[12:16], p.Flags)
	if _, err := bw.Write(hdr); err != nil {
		return nil, err
	}
	var offset uint64
	for _, e := range selected {
		raw := append([]byte(nil), e.rawHeader...)
		binary.LittleEndian.PutUint64(raw[168:176], offset)
		if _, err := bw.Write(raw); err != nil {
			return nil, err
		}
		offset += uint64(e.Size)
	}
	for i := range selected {
		e := selected[i]
		if err := copyRaw(p, &e, bw, nil); err != nil {
			return nil, err
		}
	}
	if err := bw.Flush(); err != nil {
		return nil, err
	}
	if err := out.Sync(); err != nil {
		return nil, err
	}
	if err := out.Close(); err != nil {
		return nil, err
	}
	ok = true
	verify, err := OpenA22(dstPath)
	if err != nil {
		return nil, fmt.Errorf("verify reduced A22 source image: %w", err)
	}
	defer verify.Close()
	if len(verify.Entries) != len(selected) {
		return nil, fmt.Errorf("reduced A22 entry count drift: got %d expected %d", len(verify.Entries), len(selected))
	}
	for i := range selected {
		if !strings.EqualFold(verify.Entries[i].Name, selected[i].Name) || verify.Entries[i].Size != selected[i].Size {
			return nil, fmt.Errorf("reduced A22 member drift at %d", i)
		}
	}
	return selected, nil
}
