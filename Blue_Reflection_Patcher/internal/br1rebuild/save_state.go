package br1rebuild

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

var saveMagic = []byte{0x01, 0x33, 0x79, 0xc9}

const saveTreeStart = 0x20

type saveNode struct {
	Path                     string
	Size, HeaderOff, DataOff int
}

func validNodeName(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == ':') {
			return false
		}
	}
	return true
}
func saveHeader(b []byte, o, end int) (int, string, int, bool) {
	if o+8 > end {
		return 0, "", 0, false
	}
	size := int(binary.LittleEndian.Uint32(b[o : o+4]))
	if size < 8 || o+size > end {
		return 0, "", 0, false
	}
	z := bytes.IndexByte(b[o+4:minInt(end, o+45)], 0)
	if z < 0 {
		return 0, "", 0, false
	}
	z += o + 4
	name := string(b[o+4 : z])
	if !validNodeName(name) {
		return 0, "", 0, false
	}
	return size, name, z + 1, true
}
func walkSave(b []byte, start, end int, path string, out *[]saveNode) {
	for o := start; o+8 <= end; {
		size, name, ds, ok := saveHeader(b, o, end)
		if !ok {
			o += 2
			continue
		}
		p := path + "/" + name
		*out = append(*out, saveNode{p, size, o, ds})
		walkSave(b, ds, o+size, p, out)
		o += size
	}
}
func parseSaveTree(b []byte) ([]saveNode, error) {
	if len(b) < 4 || !bytes.Equal(b[:4], saveMagic) {
		return nil, fmt.Errorf("bad save magic")
	}
	var out []saveNode
	walkSave(b, saveTreeStart, len(b), "", &out)
	return out, nil
}
func saveEndian(b []byte, nodes []saveNode) (binary.ByteOrder, error) {
	for _, n := range nodes {
		if n.Path == "/event/eventFlag" && n.DataOff+4 <= len(b) {
			x := b[n.DataOff : n.DataOff+4]
			if binary.LittleEndian.Uint32(x) == 604 {
				return binary.LittleEndian, nil
			}
			if binary.BigEndian.Uint32(x) == 604 {
				return binary.BigEndian, nil
			}
		}
	}
	return nil, fmt.Errorf("could not determine save payload byte order")
}
func nodeIndex(nodes []saveNode) map[string][]saveNode {
	m := map[string][]saveNode{}
	for _, n := range nodes {
		m[n.Path] = append(m[n.Path], n)
	}
	return m
}

func LoadEventOrdering(path string) ([]string, error) {
	d, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	p, err := parsePE(d)
	if err != nil {
		return nil, err
	}
	vaOf := func(off int) (uint64, bool) {
		for _, s := range p.sections {
			if off >= int(s.Raw) && off < int(s.Raw+s.RawSize) {
				return p.ImageBase + uint64(s.VAddr) + uint64(off-int(s.Raw)), true
			}
		}
		return 0, false
	}
	vas := map[uint64]string{}
	for i := 0; i+7 < len(d); i++ {
		if string(d[i:i+6]) != "EVENT_" {
			continue
		}
		j := i
		for j < len(d) && j-i < 40 && d[j] != 0 {
			c := d[j]
			if !(c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_') {
				break
			}
			j++
		}
		if j > i+6 && j < len(d) && d[j] == 0 {
			if va, ok := vaOf(i); ok {
				vas[va] = string(d[i:j])
			}
			i = j
		}
	}
	type ref struct {
		off  int
		name string
	}
	var refs []ref
	for off := 0; off+8 <= len(d); off += 8 {
		v := binary.LittleEndian.Uint64(d[off : off+8])
		if n, ok := vas[v]; ok {
			refs = append(refs, ref{off, n})
		}
	}
	sort.Slice(refs, func(i, j int) bool { return refs[i].off < refs[j].off })
	const nEvents = 1758
	const first = "EVENT_AA01_010"
	const last = "EVENT_ZZ01_240"
	var found [][]string
	for i := 0; i < len(refs); {
		j := i
		for j+1 < len(refs) && refs[j+1].off-refs[j].off == 8 {
			j++
		}
		run := refs[i : j+1]
		for k, x := range run {
			if x.name == first && k+nEvents <= len(run) {
				names := make([]string, nEvents)
				seen := map[string]bool{}
				for z := 0; z < nEvents; z++ {
					names[z] = run[k+z].name
					seen[names[z]] = true
				}
				if names[nEvents-1] == last && len(seen) == nEvents {
					found = append(found, names)
				}
			}
		}
		i = j + 1
	}
	if len(found) == 0 {
		return nil, fmt.Errorf("no 1758-entry event table anchored at %s", first)
	}
	for _, x := range found[1:] {
		for i := range x {
			if x[i] != found[0][i] {
				return nil, fmt.Errorf("event tables disagree")
			}
		}
	}
	return found[0], nil
}

type SaveAccessReport struct {
	Path                 string `json:"path"`
	Backup               string `json:"backup,omitempty"`
	RosterCount          int    `json:"roster_count"`
	WardrobeBytesChanged int    `json:"wardrobe_bytes_changed"`
	IslandEventID        int    `json:"island_event_id"`
	IslandChanged        bool   `json:"island_changed"`
	DressRoomEventID     int    `json:"dressroom_event_id,omitempty"`
	DressRoomChanged     bool   `json:"dressroom_changed,omitempty"`
	Verified             bool   `json:"verified"`
}

func UpdateSaveAccessState(path, dllPath string, includeDressRoom bool, apply bool) (SaveAccessReport, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return SaveAccessReport{}, err
	}
	orig := append([]byte(nil), b...)
	nodes, err := parseSaveTree(b)
	if err != nil {
		return SaveAccessReport{}, err
	}
	order, err := saveEndian(b, nodes)
	if err != nil {
		return SaveAccessReport{}, err
	}
	idx := nodeIndex(nodes)
	roster, err := readWardrobeTable(dllPath, targetRosterOffset)
	if err != nil {
		return SaveAccessReport{}, err
	}
	count := len(roster)
	flagNodes := idx["/costume/costumeFlag"]
	if len(flagNodes) == 0 {
		return SaveAccessReport{}, fmt.Errorf("save missing /costume/costumeFlag")
	}
	fn := flagNodes[0]
	if fn.DataOff+4 > len(b) {
		return SaveAccessReport{}, fmt.Errorf("costumeFlag truncated")
	}
	capN := int(order.Uint32(b[fn.DataOff : fn.DataOff+4]))
	base := fn.DataOff + 4
	if count > capN || base+capN > len(b) {
		return SaveAccessReport{}, fmt.Errorf("roster %d exceeds costumeFlag capacity %d", count, capN)
	}
	changedCost := 0
	for i := 0; i < count; i++ {
		if b[base+i] != 1 {
			b[base+i] = 1
			changedCost++
		}
	}
	events, err := LoadEventOrdering(dllPath)
	if err != nil {
		return SaveAccessReport{}, err
	}
	eventID := func(name string) (int, error) {
		for i, n := range events {
			if n == name {
				return i, nil
			}
		}
		return -1, fmt.Errorf("event %s absent", name)
	}
	isl, err := eventID("EVENT_YY04_020")
	if err != nil {
		return SaveAccessReport{}, err
	}
	execNodes := idx["/event/execFlag"]
	if len(execNodes) == 0 {
		return SaveAccessReport{}, fmt.Errorf("save missing /event/execFlag")
	}
	en := execNodes[0]
	nExec := int(order.Uint32(b[en.DataOff : en.DataOff+4]))
	execBase := en.DataOff + 4
	if isl >= nExec {
		return SaveAccessReport{}, fmt.Errorf("island event id %d outside execFlag %d", isl, nExec)
	}
	islandChanged := b[execBase+isl] != 1
	b[execBase+isl] = 1
	rep := SaveAccessReport{Path: path, RosterCount: count, WardrobeBytesChanged: changedCost, IslandEventID: isl, IslandChanged: islandChanged}
	if includeDressRoom {
		dr, er := eventID("EVENT_XF02_090")
		if er != nil {
			return rep, er
		}
		rep.DressRoomEventID = dr
		sh := idx["/event/short"]
		dt := idx["/event/date"]
		if len(sh) == 0 || len(dt) == 0 {
			return rep, fmt.Errorf("save missing dressroom event fields")
		}
		ef := execBase + dr
		sb := sh[0].DataOff + 4 + dr*8
		db := dt[0].DataOff + 4 + dr*8
		if db+8 > len(b) || sb+8 > len(b) {
			return rep, fmt.Errorf("dressroom event record truncated")
		}
		before := append([]byte(nil), b[ef:ef+1]...)
		before = append(before, b[sb:sb+8]...)
		before = append(before, b[db:db+8]...)
		b[ef] = 1
		putI16 := func(off int, v int16) { var x [2]byte; order.PutUint16(x[:], uint16(v)); copy(b[off:off+2], x[:]) }
		putI32 := func(off int, v int32) { var x [4]byte; order.PutUint32(x[:], uint32(v)); copy(b[off:off+4], x[:]) }
		for i, v := range []int16{1, 5, 0, 0} {
			putI16(sb+i*2, v)
		}
		putI32(db, 0)
		putI32(db+4, 0)
		after := append([]byte(nil), b[ef:ef+1]...)
		after = append(after, b[sb:sb+8]...)
		after = append(after, b[db:db+8]...)
		rep.DressRoomChanged = !bytes.Equal(before, after)
	}
	// prove every changed byte is within allowlisted slices.
	allowed := func(i int) bool {
		if i >= base && i < base+count {
			return true
		}
		if i == execBase+isl {
			return true
		}
		if includeDressRoom {
			dr := rep.DressRoomEventID
			sh := idx["/event/short"][0].DataOff + 4 + dr*8
			dt := idx["/event/date"][0].DataOff + 4 + dr*8
			if i == execBase+dr || i >= sh && i < sh+8 || i >= dt && i < dt+8 {
				return true
			}
		}
		return false
	}
	for i := range orig {
		if orig[i] != b[i] && !allowed(i) {
			return rep, fmt.Errorf("save patch would modify unexpected byte 0x%x", i)
		}
	}
	if len(orig) != len(b) {
		return rep, fmt.Errorf("save length changed")
	}
	if !apply {
		rep.Verified = true
		return rep, nil
	}
	stamp := time.Now().UTC().Format("20060102T150405Z")
	bak := path + ".unburger-before-br1-content-" + stamp
	if err := copyFile(path, bak); err != nil {
		return rep, err
	}
	if err := atomicWrite(path, b, 0o600); err != nil {
		return rep, err
	}
	chk, err := os.ReadFile(path)
	if err != nil {
		return rep, err
	}
	if !bytes.Equal(chk, b) {
		return rep, fmt.Errorf("save re-read mismatch")
	}
	rep.Backup = bak
	rep.Verified = true
	return rep, nil
}

func copyFile(src, dst string) error {
	in, e := os.Open(src)
	if e != nil {
		return e
	}
	defer in.Close()
	st, e := in.Stat()
	if e != nil {
		return e
	}
	out, e := os.OpenFile(dst, os.O_CREATE|os.O_EXCL|os.O_WRONLY, st.Mode().Perm())
	if e != nil {
		return e
	}
	ok := false
	defer func() {
		out.Close()
		if !ok {
			os.Remove(dst)
		}
	}()
	buf := make([]byte, 4<<20)
	for {
		n, er := in.Read(buf)
		if n > 0 {
			if _, ew := out.Write(buf[:n]); ew != nil {
				return ew
			}
		}
		if er != nil {
			if errors.Is(er, io.EOF) {
				break
			}
			return er
		}
	}
	if e := out.Sync(); e != nil {
		return e
	}
	ok = true
	return out.Close()
}
func atomicWrite(path string, b []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	f, e := os.CreateTemp(dir, ".brsave-")
	if e != nil {
		return e
	}
	tmp := f.Name()
	ok := false
	defer func() {
		f.Close()
		if !ok {
			os.Remove(tmp)
		}
	}()
	if e := f.Chmod(mode); e != nil {
		return e
	}
	if _, e = f.Write(b); e != nil {
		return e
	}
	if e = f.Sync(); e != nil {
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	if e = os.Rename(tmp, path); e != nil {
		return e
	}
	ok = true
	return nil
}

func DiscoverSaveFiles(saveDir string) ([]string, error) {
	ents, err := os.ReadDir(saveDir)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range ents {
		if e.IsDir() {
			continue
		}
		lo := strings.ToLower(e.Name())
		if strings.HasSuffix(lo, ".pcsave") && !strings.Contains(lo, ".pre") {
			out = append(out, filepath.Join(saveDir, e.Name()))
		}
	}
	sort.Strings(out)
	return out, nil
}
