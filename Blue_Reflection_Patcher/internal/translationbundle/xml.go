package translationbundle

import (
	"bytes"
	"fmt"
	"html"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

var xmlRowRE = regexp.MustCompile(`(?i)<str\b([^>]*)/?>`)
var xmlAttrRE = regexp.MustCompile(`([A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*"([^"]*)"`)
var xmlTextAttrRE = regexp.MustCompile(`(?i)(\bText\s*=\s*")([^"]*)(")`)

type xmlRow struct {
	index int
	start int
	end   int
	attrs map[string]string
	text  string
}

func parseXML(data []byte) ([]xmlRow, int, error) {
	bom := 0
	payload := data
	if bytes.HasPrefix(payload, []byte{0xef, 0xbb, 0xbf}) {
		bom = 3
		payload = payload[3:]
	}
	if !utf8.Valid(payload) {
		return nil, 0, fmt.Errorf("XML is not UTF-8")
	}
	text := string(payload)
	matches := xmlRowRE.FindAllStringSubmatchIndex(text, -1)
	rows := make([]xmlRow, 0, len(matches))
	for i, m := range matches {
		// Full match [m0,m1], group1 [m2,m3].
		attrsText := text[m[2]:m[3]]
		attrs := map[string]string{}
		for _, am := range xmlAttrRE.FindAllStringSubmatch(attrsText, -1) {
			attrs[am[1]] = html.UnescapeString(am[2])
		}
		rows = append(rows, xmlRow{index: i, start: bom + m[0], end: bom + m[1], attrs: attrs, text: attrs["Text"]})
	}
	if len(rows) == 0 {
		return nil, bom, fmt.Errorf("XML contains no <str> rows")
	}
	return rows, bom, nil
}

func xmlKey(row xmlRow) string {
	if v := row.attrs["String_No"]; v != "" {
		return "no:" + v
	}
	if v := row.attrs["String_ID"]; v != "" {
		return "id:" + v
	}
	return fmt.Sprintf("index:%d", row.index)
}

func escapeXMLText(s string) string {
	s = strings.ReplaceAll(s, "&", "&amp;")
	s = strings.ReplaceAll(s, "<", "&lt;")
	s = strings.ReplaceAll(s, ">", "&gt;")
	s = strings.ReplaceAll(s, `"`, "&quot;")
	return s
}

type xmlEdit struct {
	start, end int
	value      string
}

func applyXML(data []byte, records []Record) ([]byte, int, int, error) {
	rows, _, err := parseXML(data)
	if err != nil {
		return nil, 0, 0, err
	}
	byKey := map[string][]int{}
	for i, row := range rows {
		byKey[xmlKey(row)] = append(byKey[xmlKey(row)], i)
	}
	used := map[int]bool{}
	already, rebase := 0, 0
	var edits []xmlEdit
	for _, r := range records {
		key := ""
		if r.StringNo != "" {
			key = "no:" + r.StringNo
		} else if r.StringID != "" {
			key = "id:" + r.StringID
		} else {
			key = fmt.Sprintf("index:%d", r.TargetIndex)
		}
		candidates := byKey[key]
		idx := -1
		if len(candidates) == 1 {
			idx = candidates[0]
		}
		if idx < 0 && r.TargetIndex >= 0 && r.TargetIndex < len(rows) {
			row := rows[r.TargetIndex]
			if xmlKey(row) == key {
				idx = r.TargetIndex
			}
		}
		if idx < 0 {
			return nil, 0, 0, fmt.Errorf("cannot uniquely resolve XML record %s", r.LogicalID)
		}
		if used[idx] {
			return nil, 0, 0, fmt.Errorf("multiple Translation records resolve to XML row %d", idx)
		}
		used[idx] = true
		row := rows[idx]
		if textHash(row.text) == textHash(r.DesiredText) {
			already++
			continue
		}
		if len(r.ExpectedTechnicalTokens) > 0 {
			actual := technicalTokenRE.FindAllString(row.text, -1)
			if len(actual) != len(r.ExpectedTechnicalTokens) {
				return nil, 0, 0, fmt.Errorf("technical token count changed for %s", r.LogicalID)
			}
			for i := range actual {
				if actual[i] != r.ExpectedTechnicalTokens[i] {
					return nil, 0, 0, fmt.Errorf("technical token sequence changed for %s", r.LogicalID)
				}
			}
		}
		if r.ExpectedTextSHA256 != "" && textHash(row.text) != r.ExpectedTextSHA256 {
			rebase++
		}
		// Find Text attr within this exact row.
		rowBytes := data[row.start:row.end]
		loc := xmlTextAttrRE.FindSubmatchIndex(rowBytes)
		if loc == nil {
			return nil, 0, 0, fmt.Errorf("XML row has no Text attribute for %s", r.LogicalID)
		}
		edits = append(edits, xmlEdit{start: row.start + loc[4], end: row.start + loc[5], value: escapeXMLText(r.DesiredText)})
	}
	sort.Slice(edits, func(i, j int) bool { return edits[i].start > edits[j].start })
	out := append([]byte(nil), data...)
	for _, e := range edits {
		repl := []byte(e.value)
		buf := make([]byte, 0, len(out)-(e.end-e.start)+len(repl))
		buf = append(buf, out[:e.start]...)
		buf = append(buf, repl...)
		buf = append(buf, out[e.end:]...)
		out = buf
	}
	verify, _, err := parseXML(out)
	if err != nil {
		return nil, 0, 0, err
	}
	byVerify := map[string]xmlRow{}
	dupe := map[string]bool{}
	for _, row := range verify {
		k := xmlKey(row)
		if _, ok := byVerify[k]; ok {
			dupe[k] = true
		} else {
			byVerify[k] = row
		}
	}
	for _, r := range records {
		key := ""
		if r.StringNo != "" {
			key = "no:" + r.StringNo
		} else if r.StringID != "" {
			key = "id:" + r.StringID
		} else {
			continue
		}
		if dupe[key] {
			continue
		}
		row, ok := byVerify[key]
		if !ok || row.text != r.DesiredText {
			return nil, 0, 0, fmt.Errorf("XML round-trip mismatch for %s", r.LogicalID)
		}
	}
	return out, already, rebase, nil
}
