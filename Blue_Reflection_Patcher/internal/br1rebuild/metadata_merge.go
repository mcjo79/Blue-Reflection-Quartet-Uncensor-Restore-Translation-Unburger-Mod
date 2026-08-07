package br1rebuild

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

var stringNoRE = regexp.MustCompile(`String_No="([0-9]+)"`)
var textAttrRE = regexp.MustCompile(`Text="([^"]*)"`)

func replaceAttrASCII(line []byte, attr, value string) []byte {
	re := regexp.MustCompile(regexp.QuoteMeta(attr) + `="[^"]*"`)
	repl := []byte(attr + `="` + value + `"`)
	if re.Match(line) {
		return re.ReplaceAll(line, repl)
	}
	if i := bytes.LastIndex(line, []byte("/>")); i >= 0 {
		out := make([]byte, 0, len(line)+len(repl)+1)
		out = append(out, line[:i]...)
		out = append(out, ' ')
		out = append(out, repl...)
		out = append(out, line[i:]...)
		return out
	}
	return line
}
func deleteAttrASCII(line []byte, attr string) []byte {
	re := regexp.MustCompile(`\s` + regexp.QuoteMeta(attr) + `="[^"]*"`)
	return re.ReplaceAll(line, nil)
}

func patchCharacterCatalog(blob []byte, cs *WardrobePlan) ([]byte, int, error) {
	want := cs.ImportableBaseTags()
	parts := bytes.Split(blob, []byte("\r\n"))
	changed := 0
	for i, raw := range parts {
		m := baseTagRE.FindSubmatch(raw)
		if m == nil || !want[string(m[1])] {
			continue
		}
		tag := string(m[1])
		v, ok := cs.SourceCharacterCatalog.Rows[tag]
		if !ok {
			return nil, 0, fmt.Errorf("source charabase missing %s", tag)
		}
		line := append([]byte(nil), raw...)
		for _, a := range []string{"Model", "defaultTexture"} {
			if x, ok := v.Attr[a]; ok {
				line = replaceAttrASCII(line, a, x)
			}
		}
		if x, ok := v.Attr["ActionCharaBaseTag"]; ok {
			line = replaceAttrASCII(line, "ActionCharaBaseTag", x)
		}
		for _, a := range []string{"Motion1", "Facial"} {
			if _, ok := v.Attr[a]; !ok {
				line = deleteAttrASCII(line, a)
			}
		}
		if !bytes.Equal(line, raw) {
			changed++
		}
		parts[i] = line
	}
	return bytes.Join(parts, []byte("\r\n")), changed, nil
}

func loadStringRows(blob []byte) map[int][]byte {
	out := map[int][]byte{}
	for _, raw := range bytes.Split(blob, []byte("\r\n")) {
		if !bytes.Contains(raw, []byte("<str ")) {
			continue
		}
		n := stringNoRE.FindSubmatch(raw)
		t := textAttrRE.FindSubmatch(raw)
		if n == nil || t == nil {
			continue
		}
		var id int
		fmt.Sscanf(string(n[1]), "%d", &id)
		out[id] = append([]byte(nil), t[1]...)
	}
	return out
}
func patchStrings(blob []byte, src map[int][]byte, ids map[int]bool) ([]byte, int) {
	parts := bytes.Split(blob, []byte("\r\n"))
	changed := 0
	for i, raw := range parts {
		n := stringNoRE.FindSubmatch(raw)
		if n == nil {
			continue
		}
		var id int
		fmt.Sscanf(string(n[1]), "%d", &id)
		if !ids[id] {
			continue
		}
		text, ok := src[id]
		if !ok {
			continue
		}
		t := textAttrRE.FindSubmatchIndex(raw)
		if t == nil || string(raw[t[2]:t[3]]) != "-" {
			continue
		}
		out := make([]byte, 0, len(raw)+len(text))
		out = append(out, raw[:t[2]]...)
		out = append(out, text...)
		out = append(out, raw[t[3]:]...)
		parts[i] = out
		changed++
	}
	return bytes.Join(parts, []byte("\r\n")), changed
}

func readArchiveEntry(p interface {
	Find(string) (ArchiveEntry, bool)
	Read(ArchiveEntry) ([]byte, error)
}, name string) ([]byte, error) {
	e, ok := p.Find(name)
	if !ok {
		return nil, fmt.Errorf("PAK entry missing: %s", name)
	}
	return p.Read(e)
}

type MetadataBuildReport struct {
	ImportableRecords           int                       `json:"importable_records"`
	ImportableStringIDs         int                       `json:"backed_string_ids"`
	CharacterCatalogRowsChanged int                       `json:"charabase_rows_changed"`
	LocaleStringChanges         map[string]map[string]int `json:"locale_string_changes"`
	ReplacementEntries          []string                  `json:"replacement_entries"`
	Verify                      ArchiveAuditResult        `json:"verify"`
}

func BuildMetadataArchive(sourceRoot, targetPack12, dst string, cs *WardrobePlan, enc EncryptedTextTool, useHantForHans bool, progress byteProgress) (MetadataBuildReport, error) {
	q, err := OpenA22(targetPack12)
	if err != nil {
		return MetadataBuildReport{}, err
	}
	repl := map[string]ArchiveInput{}
	cb, err := readArchiveEntry(q, targetCharacterCatalogEntry)
	if err != nil {
		q.Close()
		return MetadataBuildReport{}, err
	}
	cbNew, ncb, err := patchCharacterCatalog(cb, cs)
	if err != nil {
		q.Close()
		return MetadataBuildReport{}, err
	}
	repl[targetCharacterCatalogEntry] = MemoryEntry{cbNew}
	ids := cs.ImportableStringIDs()
	report := MetadataBuildReport{ImportableRecords: len(cs.Importable), ImportableStringIDs: len(ids), CharacterCatalogRowsChanged: ncb, LocaleStringChanges: map[string]map[string]int{}}
	type loc struct {
		q       string
		archive string
		folder  string
	}
	locs := []loc{{"en", "PACK02_1.PAK", "saves_en"}, {"jp", "PACK02_3.PAK", "saves_jp"}, {"tc", "PACK02_2.PAK", "saves_ch"}, {"sc", "", ""}}
	sourceData, sourceDataErr := sourceDataDirectory(sourceRoot)
	if sourceDataErr != nil {
		q.Close()
		return report, sourceDataErr
	}
	var tc map[int][]byte
	for _, l := range locs {
		var src map[int][]byte
		if l.archive != "" {
			vp, er := OpenA18(casePath(sourceData, l.archive))
			if er != nil {
				q.Close()
				return report, er
			}
			b, er := readArchiveEntry(vp, `\`+l.folder+`\text\strcombineall.xml`)
			vp.Close()
			if er != nil {
				q.Close()
				return report, er
			}
			src = loadStringRows(b)
			if l.q == "tc" {
				tc = src
			}
		} else if useHantForHans && tc != nil {
			src = tc
		} else {
			continue
		}
		report.LocaleStringChanges[l.q] = map[string]int{}
		for _, stem := range []string{"strcombineall.xml", "str_costume.xml"} {
			name := `\saves\b1\text_` + l.q + `\` + stem
			b, er := readArchiveEntry(q, name)
			if er != nil {
				q.Close()
				return report, er
			}
			neu, n := patchStrings(b, src, ids)
			report.LocaleStringChanges[l.q][stem] = n
			if n > 0 {
				repl[name] = MemoryEntry{neu}
				if stem == "strcombineall.xml" {
					eb, er := enc.EncryptBR(neu, l.q+"_strcombineall.xml")
					if er != nil {
						q.Close()
						return report, er
					}
					if er = enc.VerifyBRRoundTrip(neu, eb, l.q+"_strcombineall.xml"); er != nil {
						q.Close()
						return report, er
					}
					ename := name + ".e"
					if _, er := readArchiveEntry(q, ename); er != nil {
						q.Close()
						return report, er
					}
					repl[ename] = MemoryEntry{eb}
				}
			}
		}
	}
	q.Close()
	st, err := RewriteA22(targetPack12, dst, ArchiveEdits{Replacements: repl}, progress)
	_ = st
	if err != nil {
		return report, err
	}
	verify, err := AuditA22Rewrite(targetPack12, dst, nil, repl, progress)
	if err != nil {
		return report, err
	}
	report.Verify = verify
	if len(verify.Problems) > 0 {
		return report, fmt.Errorf("PACK12 verification failed: %s", strings.Join(verify.Problems[:minInt(10, len(verify.Problems))], "; "))
	}
	for n := range repl {
		report.ReplacementEntries = append(report.ReplacementEntries, n)
	}
	sort.Slice(report.ReplacementEntries, func(i, j int) bool {
		return strings.ToLower(report.ReplacementEntries[i]) < strings.ToLower(report.ReplacementEntries[j])
	})
	return report, nil
}

func shaBytes(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
