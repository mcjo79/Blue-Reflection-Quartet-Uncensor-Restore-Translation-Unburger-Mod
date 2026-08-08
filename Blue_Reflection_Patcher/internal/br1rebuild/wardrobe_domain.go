package br1rebuild

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

const (
	sourceRosterOffset          = 0x17dc5a0
	targetRosterOffset          = 0x130b9e0
	rosterRecordSize            = 48
	rosterStrLo                 = 393217
	rosterStrHi                 = 393400
	targetCharacterCatalogEntry = `\saves\b1\chara\charabase.xml`
)

const (
	slotTextID    = 0
	slotCharacter = 1
	slotBase      = 2
	slotWet       = 3
	slotWetAlt    = 4
	slotGroup     = 5
	slotDLCFlag   = 6
	slotProduct   = 7
	slotConstant  = 8
	slotOrder     = 11
)

var attrRE = regexp.MustCompile(`([A-Za-z0-9_]+)="([^"]*)"`)
var baseTagRE = regexp.MustCompile(`BaseTag="([^"]+)"`)
var g1tModelRE = regexp.MustCompile(`(?i)([^\\]+)\.g1t$`)

type WardrobeRecord [12]int32

type CharacterRow struct {
	Tag  string
	Attr map[string]string
	Raw  []byte
}
type CharacterCatalog struct {
	Order []string
	Rows  map[string]CharacterRow
	Index map[string]int
}

type WardrobeEntryPlan struct {
	Record     WardrobeRecord `json:"record"`
	StrID      int32          `json:"str_id"`
	Chara      int32          `json:"chara"`
	Tags       [3]string      `json:"tags"`
	Models     [3]string      `json:"models"`
	Importable bool           `json:"backed"`
	Exclusion  string         `json:"reason,omitempty"`
}

type WardrobePlan struct {
	SourceRoster           []WardrobeRecord    `json:"-"`
	TargetRoster           []WardrobeRecord    `json:"-"`
	SourceCharacterCatalog CharacterCatalog    `json:"-"`
	TargetCharacterCatalog CharacterCatalog    `json:"-"`
	SourceModels           map[string]bool     `json:"-"`
	Missing                []WardrobeEntryPlan `json:"deleted"`
	Importable             []WardrobeEntryPlan `json:"backed"`
	Unavailable            []WardrobeEntryPlan `json:"unbacked"`
}

func parseCharacterCatalogBytes(blob []byte) CharacterCatalog {
	cb := CharacterCatalog{Rows: map[string]CharacterRow{}, Index: map[string]int{}}
	lines := splitLinesAny(blob)
	for _, raw := range lines {
		m := baseTagRE.FindSubmatch(raw)
		if m == nil {
			continue
		}
		tag := string(m[1])
		attrs := map[string]string{}
		for _, a := range attrRE.FindAllSubmatch(raw, -1) {
			attrs[string(a[1])] = string(a[2])
		}
		cb.Index[tag] = len(cb.Order)
		cb.Order = append(cb.Order, tag)
		cb.Rows[tag] = CharacterRow{Tag: tag, Attr: attrs, Raw: append([]byte(nil), raw...)}
	}
	return cb
}

func splitLinesAny(blob []byte) [][]byte {
	out := [][]byte{}
	start := 0
	for i := 0; i < len(blob); i++ {
		if blob[i] == '\n' {
			end := i
			if end > start && blob[end-1] == '\r' {
				end--
			}
			out = append(out, append([]byte(nil), blob[start:end]...))
			start = i + 1
		}
	}
	if start <= len(blob) {
		out = append(out, append([]byte(nil), blob[start:]...))
	}
	return out
}

func readWardrobeTable(path string, offset int) ([]WardrobeRecord, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	o := offset
	// Prefer the reconstructed wardrobe section whenever the PE contains it.
	// Candidate files are intentionally stored under neutral workspace names,
	// so section discovery must depend on file content rather than the filename.
	if raw, ok := peSectionRaw(data, ".b1cos"); ok {
		o = raw
	}
	if o < 0 || o+rosterRecordSize > len(data) {
		return nil, fmt.Errorf("roster offset 0x%x outside %s", o, path)
	}
	var out []WardrobeRecord
	for o+rosterRecordSize <= len(data) {
		sid := int32(binary.LittleEndian.Uint32(data[o : o+4]))
		if sid < rosterStrLo || sid > rosterStrHi {
			break
		}
		var r WardrobeRecord
		for i := 0; i < 12; i++ {
			r[i] = int32(binary.LittleEndian.Uint32(data[o+i*4 : o+i*4+4]))
		}
		out = append(out, r)
		o += rosterRecordSize
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("no roster records found in %s", path)
	}
	return out, nil
}

func peSectionRaw(data []byte, name string) (int, bool) {
	if len(data) < 0x40 {
		return 0, false
	}
	pe := int(binary.LittleEndian.Uint32(data[0x3c:0x40]))
	if pe < 0 || pe+24 > len(data) {
		return 0, false
	}
	n := int(binary.LittleEndian.Uint16(data[pe+6 : pe+8]))
	opt := int(binary.LittleEndian.Uint16(data[pe+20 : pe+22]))
	base := pe + 24 + opt
	for i := 0; i < n; i++ {
		o := base + i*40
		if o+40 > len(data) {
			return 0, false
		}
		nm := strings.TrimRight(string(data[o:o+8]), "\x00")
		if nm == name {
			return int(binary.LittleEndian.Uint32(data[o+20 : o+24])), true
		}
	}
	return 0, false
}

type sourceCatalogLocation struct {
	Kind   string
	Path   string
	Member string
}

func resolveCaseInsensitivePath(root string, parts ...string) (string, bool) {
	current := root
	for _, want := range parts {
		entries, err := os.ReadDir(current)
		if err != nil {
			return "", false
		}
		matched := ""
		for _, entry := range entries {
			if strings.EqualFold(entry.Name(), want) {
				matched = entry.Name()
				break
			}
		}
		if matched == "" {
			return "", false
		}
		current = filepath.Join(current, matched)
	}
	return current, true
}

func readSourceCharacterCatalog(sourceRoot string) (CharacterCatalog, sourceCatalogLocation, error) {
	dataRoot, err := sourceDataDirectory(sourceRoot)
	if err != nil {
		return CharacterCatalog{}, sourceCatalogLocation{}, err
	}
	if loose, ok := resolveCaseInsensitivePath(dataRoot, "saves_en", "chara", "charabase.xml"); ok {
		blob, readErr := os.ReadFile(loose)
		if readErr != nil {
			return CharacterCatalog{}, sourceCatalogLocation{}, readErr
		}
		cat := parseCharacterCatalogBytes(blob)
		if len(cat.Order) == 0 {
			return CharacterCatalog{}, sourceCatalogLocation{}, fmt.Errorf("source character catalog is empty: %s", loose)
		}
		return cat, sourceCatalogLocation{Kind: "loose", Path: loose}, nil
	}

	entries, err := os.ReadDir(dataRoot)
	if err != nil {
		return CharacterCatalog{}, sourceCatalogLocation{}, err
	}
	var archives []string
	for _, entry := range entries {
		if entry.IsDir() || !strings.EqualFold(filepath.Ext(entry.Name()), ".pak") {
			continue
		}
		archives = append(archives, filepath.Join(dataRoot, entry.Name()))
	}
	sort.SliceStable(archives, func(i, j int) bool {
		bi, bj := strings.ToLower(filepath.Base(archives[i])), strings.ToLower(filepath.Base(archives[j]))
		pi, pj := 1, 1
		if bi == "pack02_1.pak" {
			pi = 0
		}
		if bj == "pack02_1.pak" {
			pj = 0
		}
		if pi != pj {
			return pi < pj
		}
		return bi < bj
	})
	const wanted = `\saves_en\chara\charabase.xml`
	var found CharacterCatalog
	var where sourceCatalogLocation
	var foundBlob []byte
	for _, archivePath := range archives {
		pak, openErr := OpenA18(archivePath)
		if openErr != nil {
			continue
		}
		var candidate *ArchiveEntry
		for i := range pak.Entries {
			name := strings.ReplaceAll(pak.Entries[i].Name, "/", `\`)
			lo := strings.ToLower(name)
			if strings.EqualFold(name, wanted) || strings.HasSuffix(lo, strings.ToLower(wanted)) {
				e := pak.Entries[i]
				candidate = &e
				break
			}
		}
		if candidate == nil {
			pak.Close()
			continue
		}
		blob, readErr := pak.Read(*candidate)
		pak.Close()
		if readErr != nil {
			return CharacterCatalog{}, sourceCatalogLocation{}, readErr
		}
		cat := parseCharacterCatalogBytes(blob)
		if len(cat.Order) == 0 {
			return CharacterCatalog{}, sourceCatalogLocation{}, fmt.Errorf("source character catalog member is empty: %s#%s", archivePath, candidate.Name)
		}
		if foundBlob != nil && !bytes.Equal(foundBlob, blob) {
			return CharacterCatalog{}, sourceCatalogLocation{}, fmt.Errorf("multiple different source character catalogs found in A18 archives")
		}
		if foundBlob == nil {
			foundBlob = append([]byte(nil), blob...)
			found = cat
			where = sourceCatalogLocation{Kind: "a18_member", Path: archivePath, Member: candidate.Name}
		}
	}
	if foundBlob != nil {
		return found, where, nil
	}
	return CharacterCatalog{}, sourceCatalogLocation{}, fmt.Errorf("source character catalog not found as a loose file or A18 archive member")
}

func describeSourceCatalogLocation(loc sourceCatalogLocation) string {
	if loc.Kind == "a18_member" {
		return loc.Path + "#" + loc.Member
	}
	return loc.Path
}

func readTargetCharacterCatalog(pack12 string) (CharacterCatalog, error) {
	p, err := OpenA22(pack12)
	if err != nil {
		return CharacterCatalog{}, err
	}
	defer p.Close()
	e, ok := p.Find(targetCharacterCatalogEntry)
	if !ok {
		return CharacterCatalog{}, fmt.Errorf("%s missing %s", pack12, targetCharacterCatalogEntry)
	}
	b, err := p.Read(e)
	if err != nil {
		return CharacterCatalog{}, err
	}
	return parseCharacterCatalogBytes(b), nil
}

func catalogSourceModels(pack00 string) (map[string]bool, error) {
	p, err := OpenA18(pack00)
	if err != nil {
		return nil, err
	}
	defer p.Close()
	out := map[string]bool{}
	for _, e := range p.Entries {
		if m := g1tModelRE.FindStringSubmatch(strings.ToLower(e.Name)); m != nil {
			out[m[1]] = true
		}
	}
	return out, nil
}

func DeriveWardrobePlan(sourceRoot, targetRoot, pack12Override string) (*WardrobePlan, error) {
	vexe := casePath(sourceRoot, "BLUE_REFLECTION.exe")
	vd, err := sourceDataDirectory(sourceRoot)
	if err != nil {
		return nil, err
	}
	qd := filepath.Join(targetRoot, "Data")
	qdll := filepath.Join(targetRoot, "B1.dll")
	if pack12Override == "" {
		pack12Override = casePath(qd, "PACK12.PAK")
	}
	vr, err := readWardrobeTable(vexe, sourceRosterOffset)
	if err != nil {
		return nil, err
	}
	qr, err := readWardrobeTable(qdll, targetRosterOffset)
	if err != nil {
		return nil, err
	}
	vcb, _, err := readSourceCharacterCatalog(sourceRoot)
	if err != nil {
		return nil, err
	}
	qcb, err := readTargetCharacterCatalog(pack12Override)
	if err != nil {
		return nil, err
	}
	shipped, err := catalogSourceModels(casePath(vd, "PACK00_02.PAK"))
	if err != nil {
		return nil, err
	}
	cs := &WardrobePlan{SourceRoster: vr, TargetRoster: qr, SourceCharacterCatalog: vcb, TargetCharacterCatalog: qcb, SourceModels: shipped}
	if err := cs.classify(); err != nil {
		return nil, err
	}
	return cs, nil
}

func (cs *WardrobePlan) classify() error {
	have := map[string]bool{}
	for _, r := range cs.TargetRoster {
		have[fmt.Sprintf("%d/%d", r[slotTextID], r[slotCharacter])] = true
	}
	def := map[int32]string{}
	for _, r := range cs.TargetRoster {
		ch := r[slotCharacter]
		if _, ok := def[ch]; ok {
			continue
		}
		idx := int(r[slotBase])
		if idx < 0 || idx >= len(cs.TargetCharacterCatalog.Order) {
			return fmt.Errorf("target base row %d outside charabase", idx)
		}
		tag := cs.TargetCharacterCatalog.Order[idx]
		model := cs.TargetCharacterCatalog.Rows[tag].Attr["Model"]
		def[ch] = modelLeaf(model)
	}
	for _, r := range cs.SourceRoster {
		if have[fmt.Sprintf("%d/%d", r[slotTextID], r[slotCharacter])] {
			continue
		}
		c := WardrobeEntryPlan{Record: r, StrID: r[slotTextID], Chara: r[slotCharacter], Importable: true}
		fields := []int{slotBase, slotWet, slotWetAlt}
		for j, f := range fields {
			idx := int(r[f])
			if idx < 0 || idx >= len(cs.SourceCharacterCatalog.Order) {
				return fmt.Errorf("source charabase row %d outside range", idx)
			}
			tag := cs.SourceCharacterCatalog.Order[idx]
			m := modelLeaf(cs.SourceCharacterCatalog.Rows[tag].Attr["Model"])
			c.Tags[j] = tag
			c.Models[j] = m
			if !cs.SourceModels[m] || cs.TargetCharacterCatalog.Index[tag] < 0 {
				c.Importable = false
				c.Exclusion = "model never shipped on PC or BaseTag absent in Quartet"
			}
		}
		if c.Importable && c.Models[0] != "" && c.Models[0] == def[c.Chara] {
			c.Importable = false
			c.Exclusion = "reuses the default uniform model"
		}
		cs.Missing = append(cs.Missing, c)
		if c.Importable {
			cs.Importable = append(cs.Importable, c)
		} else {
			cs.Unavailable = append(cs.Unavailable, c)
		}
	}
	return nil
}

func modelLeaf(s string) string {
	s = strings.ReplaceAll(s, "\\", "/")
	parts := strings.Split(s, "/")
	return strings.ToLower(parts[len(parts)-1])
}
func (cs *WardrobePlan) ImportableStringIDs() map[int]bool {
	m := map[int]bool{}
	for _, c := range cs.Importable {
		m[int(c.StrID)] = true
	}
	return m
}
func (cs *WardrobePlan) ImportableBaseTags() map[string]bool {
	m := map[string]bool{}
	for _, c := range cs.Importable {
		for _, t := range c.Tags {
			m[t] = true
		}
	}
	return m
}
func (cs *WardrobePlan) UnavailableStringIDs() []int {
	b := cs.ImportableStringIDs()
	m := map[int]bool{}
	for _, c := range cs.Unavailable {
		if !b[int(c.StrID)] {
			m[int(c.StrID)] = true
		}
	}
	out := make([]int, 0, len(m))
	for x := range m {
		out = append(out, x)
	}
	sort.Ints(out)
	return out
}

func casePath(dir, name string) string {
	ents, err := os.ReadDir(dir)
	if err == nil {
		for _, e := range ents {
			if strings.EqualFold(e.Name(), name) {
				return filepath.Join(dir, e.Name())
			}
		}
	}
	return filepath.Join(dir, name)
}

func parseIntAttr(raw []byte, name string) (int, bool) {
	re := regexp.MustCompile(regexp.QuoteMeta(name) + `="([0-9]+)"`)
	m := re.FindSubmatch(raw)
	if m == nil {
		return 0, false
	}
	v, e := strconv.Atoi(string(m[1]))
	return v, e == nil
}
