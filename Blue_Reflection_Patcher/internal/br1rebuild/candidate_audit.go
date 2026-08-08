package br1rebuild

import (
	"fmt"
	"os"
	"strings"
)

// CrossFileAudit is an independent post-build readback across the
// three costume-bearing targets.  It intentionally does not reuse in-memory
// builder blobs: B1.dll, PACK12 and PACK10_02 are reopened from their final
// candidate paths.
type CrossFileAudit struct {
	WardrobeRecords                       int    `json:"roster_records"`
	UniqueRosterPairs                     int    `json:"unique_roster_pairs"`
	RosterModelReferencesChecked          int    `json:"roster_model_references_checked"`
	ImportableCharacterCatalogRowsChecked int    `json:"backed_charabase_rows_checked"`
	EncryptedLocaleTablesChecked          int    `json:"encrypted_locale_tables_checked"`
	MissingModelReferences                int    `json:"missing_model_references"`
	LegacyScopedBoundsRemaining           int    `json:"legacy_scoped_bounds_remaining"`
	Status                                string `json:"status"`
}

func AuditCrossFileWardrobe(dllPath, pack10Path, pack12Path string, cs *WardrobePlan, enc EncryptedTextTool) (CrossFileAudit, error) {
	rep := CrossFileAudit{Status: "blocked"}

	recs, err := readWardrobeTable(dllPath, targetRosterOffset)
	if err != nil {
		return rep, fmt.Errorf("read candidate .b1cos roster: %w", err)
	}
	rep.WardrobeRecords = len(recs)
	if len(recs) != 122 {
		return rep, fmt.Errorf("candidate roster contains %d records, expected 122", len(recs))
	}

	p10, err := OpenA22(pack10Path)
	if err != nil {
		return rep, fmt.Errorf("open candidate PACK10_02: %w", err)
	}
	models := map[string]bool{}
	for _, e := range p10.Entries {
		if m := g1tModelRE.FindStringSubmatch(strings.ToLower(e.Name)); m != nil {
			models[m[1]] = true
		}
	}
	p10.Close()

	p12r, err := OpenA22(pack12Path)
	if err != nil {
		return rep, fmt.Errorf("open candidate PACK12: %w", err)
	}
	defer p12r.Close()
	cbBytes, err := readArchiveEntry(p12r, targetCharacterCatalogEntry)
	if err != nil {
		return rep, err
	}
	cb := parseCharacterCatalogBytes(cbBytes)
	if len(cb.Order) == 0 {
		return rep, fmt.Errorf("candidate charabase contains no rows")
	}

	pairs := map[string]bool{}
	for i, r := range recs {
		if r[slotCharacter] < 0 || r[slotCharacter] > 14 {
			return rep, fmt.Errorf("candidate roster %d has invalid character %d", i, r[slotCharacter])
		}
		pair := fmt.Sprintf("%d/%d", r[slotTextID], r[slotCharacter])
		pairs[pair] = true
		if i >= 56 && (r[slotDLCFlag] != 0 || r[slotProduct] != 0) {
			return rep, fmt.Errorf("reconstructed wardrobe record %d unexpectedly retains DLC ownership fields %d/%d", i, r[slotDLCFlag], r[slotProduct])
		}
		for _, f := range []int{slotBase, slotWet, slotWetAlt} {
			row := int(r[f])
			if row < 0 || row >= len(cb.Order) {
				return rep, fmt.Errorf("candidate roster %d charabase row %d outside 0..%d", i, row, len(cb.Order)-1)
			}
			tag := cb.Order[row]
			model := modelLeaf(cb.Rows[tag].Attr["Model"])
			if model == "" || !models[model] {
				rep.MissingModelReferences++
				return rep, fmt.Errorf("candidate roster %d field %d resolves %s -> missing model %q in candidate PACK10_02", i, f, tag, model)
			}
			rep.RosterModelReferencesChecked++
		}
	}
	rep.UniqueRosterPairs = len(pairs)

	// Independently verify the reconstructed charabase semantics from final PACK12.
	for tag := range cs.ImportableBaseTags() {
		v, vok := cs.SourceCharacterCatalog.Rows[tag]
		q, qok := cb.Rows[tag]
		if !vok || !qok {
			return rep, fmt.Errorf("backed BaseTag %s absent from candidate/source charabase", tag)
		}
		for _, attr := range []string{"Model", "defaultTexture"} {
			if want, ok := v.Attr[attr]; ok && q.Attr[attr] != want {
				return rep, fmt.Errorf("candidate charabase %s %s=%q, expected source %q", tag, attr, q.Attr[attr], want)
			}
		}
		if want, ok := v.Attr["ActionCharaBaseTag"]; ok && q.Attr["ActionCharaBaseTag"] != want {
			return rep, fmt.Errorf("candidate charabase %s ActionCharaBaseTag=%q, expected %q", tag, q.Attr["ActionCharaBaseTag"], want)
		}
		for _, attr := range []string{"Motion1", "Facial"} {
			if _, sourceHas := v.Attr[attr]; !sourceHas {
				if _, candidateHas := q.Attr[attr]; candidateHas {
					return rep, fmt.Errorf("candidate charabase %s still contains source-absent %s", tag, attr)
				}
			}
		}
		rep.ImportableCharacterCatalogRowsChecked++
	}

	// Read the required encrypted locale tables back out of the completed archive.
	// The audit derives its expectations from the title contract rather than the
	// builder report so it can validate an existing candidate set independently.
	for _, loc := range []string{"en", "jp", "tc"} {
		plainName := `\saves\b1\text_` + loc + `\strcombineall.xml`
		plain, err := readArchiveEntry(p12r, plainName)
		if err != nil {
			return rep, err
		}
		cipher, err := readArchiveEntry(p12r, plainName+".e")
		if err != nil {
			return rep, err
		}
		if err := enc.VerifyBRRoundTrip(plain, cipher, "readback_"+loc+"_strcombineall.xml"); err != nil {
			return rep, fmt.Errorf("candidate encrypted table readback %s: %w", loc, err)
		}
		rep.EncryptedLocaleTablesChecked++
	}

	// RewriteBR1Module already performs this check in-memory; repeat it on the file we
	// actually wrote to staging so a write/truncation error cannot evade it.
	dllBytes, err := osReadFile(dllPath)
	if err != nil {
		return rep, err
	}
	pe, err := parsePE(dllBytes)
	if err != nil {
		return rep, err
	}
	sec, ok := pe.section(".b1cos")
	if !ok {
		return rep, fmt.Errorf("candidate B1.dll missing .b1cos on integrated readback")
	}
	bounds, err := findRosterBounds(pe, sec.VAddr, uint32(122*rosterRecordSize))
	if err != nil {
		return rep, err
	}
	rep.LegacyScopedBoundsRemaining = len(bounds)
	if len(bounds) != 0 {
		return rep, fmt.Errorf("candidate B1.dll retains %d scoped 55/56 bounds", len(bounds))
	}

	rep.Status = "pass"
	return rep, nil
}

// osReadFile is a tiny seam kept here so integrated verification is visibly a
// file readback rather than reuse of RewriteBR1Module's input/output slice.
var osReadFile = func(path string) ([]byte, error) { return os.ReadFile(path) }
