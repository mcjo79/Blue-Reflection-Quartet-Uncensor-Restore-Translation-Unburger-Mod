package quartetdlc

import (
	"bytes"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

var (
	xmlStringRowRE          = regexp.MustCompile(`<str\s+String_ID="([^"]*)"\s+String_No="[^"]*"\s+Text="([^"]*)"`)
	xmlCharaBaseRowRE       = regexp.MustCompile(`<CharaBase\b[^>]*/>`)
	xmlElemRowRE            = regexp.MustCompile(`<elem\b[^>]*/>`)
	xmlPartySkillRowRE      = regexp.MustCompile(`<party_skill\b[^>]*/>`)
	xmlFreeAchievementRowRE = regexp.MustCompile(`<FreeAchievement\b[^>]*/>`)
	xmlScenarioRowRE        = regexp.MustCompile(`<Elem\b[^>]*/>`)
	xmlAttrRE               = regexp.MustCompile(`([A-Za-z0-9_]+)="([^"]*)"`)
)

func xmlAttrs(row []byte) map[string]string {
	out := map[string]string{}
	for _, m := range xmlAttrRE.FindAllSubmatch(row, -1) {
		out[string(m[1])] = string(m[2])
	}
	return out
}

func replaceXMLAttr(row []byte, name, value string) ([]byte, bool) {
	re := regexp.MustCompile(`\b` + regexp.QuoteMeta(name) + `="[^"]*"`)
	loc := re.FindIndex(row)
	if loc == nil {
		return row, false
	}
	replacement := []byte(name + `="` + value + `"`)
	if bytes.Equal(row[loc[0]:loc[1]], replacement) {
		return row, false
	}
	out := make([]byte, 0, len(row)-loc[1]+loc[0]+len(replacement))
	out = append(out, row[:loc[0]]...)
	out = append(out, replacement...)
	out = append(out, row[loc[1]:]...)
	return out, true
}

func removeXMLAttr(row []byte, name string) ([]byte, bool) {
	re := regexp.MustCompile(`\s+` + regexp.QuoteMeta(name) + `="[^"]*"`)
	loc := re.FindIndex(row)
	if loc == nil {
		return row, false
	}
	out := append([]byte(nil), row[:loc[0]]...)
	out = append(out, row[loc[1]:]...)
	return out, true
}

func secondLightBlankXMLText(v []byte) bool {
	// The reference string restore treats only the literal empty value and "-"
	// sentinel as blank. Whitespace is content: one shipped DLC label is exactly
	// one ASCII space and must be restored as such.
	return len(v) == 0 || bytes.Equal(v, []byte("-"))
}

func restoreBlankSecondLightStrings(target, source []byte) ([]byte, int, error) {
	src := map[string][]byte{}
	for _, loc := range xmlStringRowRE.FindAllSubmatchIndex(source, -1) {
		id := string(source[loc[2]:loc[3]])
		src[id] = append([]byte(nil), source[loc[4]:loc[5]]...)
	}
	matches := xmlStringRowRE.FindAllSubmatchIndex(target, -1)
	if len(matches) == 0 {
		return target, 0, nil
	}
	var out bytes.Buffer
	last, changed := 0, 0
	for _, loc := range matches {
		out.Write(target[last:loc[4]])
		current := target[loc[4]:loc[5]]
		id := string(target[loc[2]:loc[3]])
		wanted, ok := src[id]
		if ok && secondLightBlankXMLText(current) && !secondLightBlankXMLText(wanted) {
			out.Write(wanted)
			changed++
		} else {
			out.Write(current)
		}
		last = loc[5]
	}
	out.Write(target[last:])
	return out.Bytes(), changed, nil
}

type secondLightCostumeAudit struct {
	RepointedRows int
	OpenedRows    int
	ReclosedRows  int
	AddedFolders  []string
	SkippedRows   []string
}

func patchSecondLightCostumeTables(targetChara, sourceChara, targetCostume, sourceCostume, targetModelTable []byte, sourceFolders, targetFolders map[string]bool) ([]byte, []byte, secondLightCostumeAudit, error) {
	audit := secondLightCostumeAudit{}
	sourceRows := map[string][]byte{}
	for _, row := range xmlCharaBaseRowRE.FindAll(sourceChara, -1) {
		a := xmlAttrs(row)
		if tag := a["BaseTag"]; tag != "" {
			sourceRows[tag] = append([]byte(nil), row...)
		}
	}
	repoint := map[string]map[string]string{}
	needFolders := map[string]bool{}
	for _, row := range xmlCharaBaseRowRE.FindAll(targetChara, -1) {
		a := xmlAttrs(row)
		tag := a["BaseTag"]
		srcRow, ok := sourceRows[tag]
		if !ok {
			continue
		}
		sa := xmlAttrs(srcRow)
		folder := strings.Split(sa["Model"], "/")[0]
		if folder != "" && sourceFolders[folder] && sa["Model"] != a["Model"] {
			fields := map[string]string{}
			for _, key := range []string{"Model", "FileHead", "defaultTexture", "wetCharaBaseTag"} {
				if v, ok := sa[key]; ok {
					fields[key] = v
				}
			}
			repoint[tag] = fields
			needFolders[folder] = true
			if wet := sa["wetCharaBaseTag"]; wet != "" {
				if wr, ok := sourceRows[wet]; ok {
					wf := strings.Split(xmlAttrs(wr)["Model"], "/")[0]
					if sourceFolders[wf] {
						needFolders[wf] = true
					}
				}
			}
		}
	}
	for folder := range sourceFolders {
		if !targetFolders[folder] {
			needFolders[folder] = true
		}
	}
	for f := range needFolders {
		audit.AddedFolders = append(audit.AddedFolders, f)
	}
	sort.Strings(audit.AddedFolders)

	newChara := replaceRows(targetChara, xmlCharaBaseRowRE, func(row []byte) ([]byte, error) {
		a := xmlAttrs(row)
		fields, ok := repoint[a["BaseTag"]]
		if !ok {
			return row, nil
		}
		out := append([]byte(nil), row...)
		changed := false
		for _, key := range []string{"Model", "FileHead", "defaultTexture", "wetCharaBaseTag"} {
			if v, ok := fields[key]; ok {
				var c bool
				out, c = replaceXMLAttr(out, key, v)
				changed = changed || c
			}
		}
		if changed {
			audit.RepointedRows++
		}
		return out, nil
	})

	modelToBase := map[string]string{}
	for _, row := range xmlElemRowRE.FindAll(targetModelTable, -1) {
		a := xmlAttrs(row)
		if id := a["id"]; id != "" {
			modelToBase[id] = a["chara_base"]
		}
	}
	baseToFolder := map[string]string{}
	for _, row := range xmlCharaBaseRowRE.FindAll(newChara, -1) {
		a := xmlAttrs(row)
		if tag := a["BaseTag"]; tag != "" {
			baseToFolder["CHARA_BASE_"+tag] = strings.Split(a["Model"], "/")[0]
		}
	}
	intendedFolder := map[string]string{}
	for _, row := range xmlCharaBaseRowRE.FindAll(sourceChara, -1) {
		a := xmlAttrs(row)
		if tag := a["BaseTag"]; tag != "" {
			intendedFolder["CHARA_BASE_"+tag] = strings.Split(a["Model"], "/")[0]
		}
	}
	sourceConditions := map[string]string{}
	for _, row := range xmlElemRowRE.FindAll(sourceCostume, -1) {
		a := xmlAttrs(row)
		if id := a["id"]; id != "" {
			sourceConditions[id] = a["cond_00"]
		}
	}
	available := map[string]bool{}
	for f := range sourceFolders {
		available[f] = true
	}
	for f := range targetFolders {
		available[f] = true
	}

	// Pass 1 mirrors the source restoration: open source-restorable rows whose
	// currently routed model is available. Keep this separate from the missing-
	// model closure below: two shipped rows begin at NEVER, are opened here, and
	// must be seen again by pass 2 before the final table is accepted.
	openedCostume := replaceRows(targetCostume, xmlElemRowRE, func(row []byte) ([]byte, error) {
		a := xmlAttrs(row)
		id, cond := a["id"], a["cond_00"]
		if id == "" || cond != "COSTUME_OPEN_COND_NEVER" {
			return row, nil
		}
		was := sourceConditions[id]
		if was == "" || was == "COSTUME_OPEN_COND_NEVER" {
			return row, nil
		}
		folder := baseToFolder[modelToBase[a["model_body"]]]
		if folder != "" && !available[folder] {
			audit.SkippedRows = append(audit.SkippedRows, id)
			return row, nil
		}
		out, changed := replaceXMLAttr(row, "cond_00", "COSTUME_OPEN_COND_DEFAULT")
		if changed {
			audit.OpenedRows++
		}
		return out, nil
	})

	// Pass 2 is a final reachability closure over the already-opened table.
	// A DEFAULT body row must not point at a standalone-intended model folder
	// absent from both the source and target PC archives. This is deliberately a
	// second pass so rows opened above cannot bypass the guard in the same call.
	newCostume := replaceRows(openedCostume, xmlElemRowRE, func(row []byte) ([]byte, error) {
		a := xmlAttrs(row)
		if a["cond_00"] != "COSTUME_OPEN_COND_DEFAULT" {
			return row, nil
		}
		base := modelToBase[a["model_body"]]
		want := intendedFolder[base]
		if want == "" || available[want] {
			return row, nil
		}
		out, changed := replaceXMLAttr(row, "cond_00", "COSTUME_OPEN_COND_NEVER")
		if changed {
			audit.ReclosedRows++
		}
		return out, nil
	})
	sort.Strings(audit.SkippedRows)
	return newChara, newCostume, audit, nil
}

func replaceRows(input []byte, re *regexp.Regexp, fn func([]byte) ([]byte, error)) []byte {
	matches := re.FindAllIndex(input, -1)
	if len(matches) == 0 {
		return append([]byte(nil), input...)
	}
	var out bytes.Buffer
	last := 0
	for _, loc := range matches {
		out.Write(input[last:loc[0]])
		row, err := fn(input[loc[0]:loc[1]])
		if err != nil {
			panic(err)
		}
		out.Write(row)
		last = loc[1]
	}
	out.Write(input[last:])
	return out.Bytes()
}

func regateSecondLightScenario(input []byte) ([]byte, int, error) {
	out := append([]byte(nil), input...)
	changed := 0
	for _, spec := range []struct{ event, entitlement, story string }{{"EVENT_XF04_010", "1180", "2660"}, {"EVENT_SD00_430", "1226", "102"}} {
		rows := xmlScenarioRowRE.FindAllIndex(out, -1)
		hits := []int{}
		for i, loc := range rows {
			if xmlAttrs(out[loc[0]:loc[1]])["launch_param"] == spec.event {
				hits = append(hits, i)
			}
		}
		if len(hits) != 1 {
			return nil, 0, fmt.Errorf("scenario event %s occurrence count=%d", spec.event, len(hits))
		}
		loc := rows[hits[0]]
		row := append([]byte(nil), out[loc[0]:loc[1]]...)
		a := xmlAttrs(row)
		hasEnt := false
		keepOff := false
		for i := 1; i <= 5; i++ {
			if a[fmt.Sprintf("on_condition_%d", i)] == spec.entitlement {
				hasEnt = true
			}
		}
		for k := range a {
			if strings.HasPrefix(k, "off_condition_1") {
				keepOff = true
			}
		}
		if !hasEnt {
			continue
		}
		for i := 1; i <= 5; i++ {
			row, _ = removeXMLAttr(row, fmt.Sprintf("on_condition_%d", i))
		}
		row, _ = removeXMLAttr(row, "off_condition_2")
		// Insert one story gate before the first stable control attribute.
		marker := []byte(" off_condition_1=")
		pos := bytes.Index(row, marker)
		if pos < 0 {
			for _, alt := range [][]byte{[]byte(" launch_type="), []byte(" pp_type="), []byte(" on_flag=")} {
				if p := bytes.Index(row, alt); p >= 0 {
					pos = p
					break
				}
			}
		}
		if pos < 0 || !keepOff {
			return nil, 0, fmt.Errorf("scenario event %s lacks safe insertion/one-shot gate", spec.event)
		}
		ins := []byte(fmt.Sprintf(` on_condition_1="%s"`, spec.story))
		row = append(append(append([]byte(nil), row[:pos]...), ins...), row[pos:]...)
		out = append(append(append([]byte(nil), out[:loc[0]]...), row...), out[loc[1]:]...)
		changed++
	}
	// Remove Hidden Island entitlement only when the genuine story flag is already present.
	for {
		rows := xmlScenarioRowRE.FindAllIndex(out, -1)
		did := false
		for _, loc := range rows {
			row := out[loc[0]:loc[1]]
			a := xmlAttrs(row)
			vals := []string{}
			for i := 1; i <= 5; i++ {
				if v := a[fmt.Sprintf("on_condition_%d", i)]; v != "" {
					vals = append(vals, v)
				}
			}
			if !containsString(vals, "1181") || !containsString(vals, "110") {
				continue
			}
			keep := []string{}
			for _, v := range vals {
				if v != "1181" {
					keep = append(keep, v)
				}
			}
			nr := append([]byte(nil), row...)
			for i := 1; i <= 5; i++ {
				nr, _ = removeXMLAttr(nr, fmt.Sprintf("on_condition_%d", i))
			}
			insertAt := -1
			for _, alt := range [][]byte{[]byte(" off_condition_"), []byte(" launch_type="), []byte(" pp_type="), []byte(" on_flag=")} {
				if p := bytes.Index(nr, alt); p >= 0 {
					insertAt = p
					break
				}
			}
			if insertAt < 0 {
				return nil, 0, fmt.Errorf("cannot renumber scenario gate")
			}
			var b strings.Builder
			for i, v := range keep {
				fmt.Fprintf(&b, ` on_condition_%d="%s"`, i+1, v)
			}
			nr = append(append(append([]byte(nil), nr[:insertAt]...), []byte(b.String())...), nr[insertAt:]...)
			out = append(append(append([]byte(nil), out[:loc[0]]...), nr...), out[loc[1]:]...)
			changed++
			did = true
			break
		}
		if !did {
			break
		}
	}
	return out, changed, nil
}

func enableSecondLightFacilityPlot(input []byte) ([]byte, bool, error) {
	re := regexp.MustCompile(`<elem\s+id="SD_PLACE_04_18"[^>]*/>`)
	loc := re.FindIndex(input)
	if loc == nil {
		return nil, false, fmt.Errorf("SD_PLACE_04_18 not found")
	}
	row := input[loc[0]:loc[1]]
	a := xmlAttrs(row)
	if a["size"] == "4" {
		return input, false, nil
	}
	if a["size"] != "-1" {
		return nil, false, fmt.Errorf("unexpected SD_PLACE_04_18 size=%q", a["size"])
	}
	nr, _ := replaceXMLAttr(row, "size", "4")
	out := append([]byte(nil), input[:loc[0]]...)
	out = append(out, nr...)
	out = append(out, input[loc[1]:]...)
	return out, true, nil
}

func restoreSecondLightDualSkills(target, source []byte) ([]byte, int, error) {
	type block struct {
		tag  string
		rows [][]byte
		abs  []int
	}
	parse := func(data []byte) []block {
		rows := xmlPartySkillRowRE.FindAll(data, -1)
		out := []block{}
		cur := block{}
		abs := 0
		for _, r := range rows {
			a := xmlAttrs(r)
			if tag := a["charaTag"]; tag != "" {
				if len(cur.rows) > 0 {
					out = append(out, cur)
				}
				cur = block{tag: tag}
			}
			cur.rows = append(cur.rows, append([]byte(nil), r...))
			cur.abs = append(cur.abs, abs)
			abs++
		}
		if len(cur.rows) > 0 {
			out = append(out, cur)
		}
		return out
	}
	tb := parse(target)
	sb := parse(source)
	tm := map[string]block{}
	for _, b := range tb {
		tm[b.tag] = b
	}
	replaceAbs := map[int][]byte{}
	want := regexp.MustCompile(`skillTag="SKILL_PC000_DUAL_PC00[1-5]"`)
	blank := []byte(`<party_skill skillTag="SKILL_NONE" lv="-1" endLv="-1"/>`)
	for _, s := range sb {
		t, ok := tm[s.tag]
		if !ok {
			continue
		}
		if len(t.rows) != len(s.rows) {
			return nil, 0, fmt.Errorf("party_skill block %s size mismatch", s.tag)
		}
		for i := range s.rows {
			if !want.Match(s.rows[i]) {
				continue
			}
			if bytes.Equal(t.rows[i], s.rows[i]) {
				continue
			}
			if !bytes.Equal(t.rows[i], blank) {
				return nil, 0, fmt.Errorf("party_skill %s row %d is not blank", s.tag, i)
			}
			replaceAbs[t.abs[i]] = s.rows[i]
		}
	}
	if len(replaceAbs) == 0 {
		return target, 0, nil
	}
	if len(replaceAbs) != 10 {
		return nil, 0, fmt.Errorf("Resonance Tide row count=%d, expected 10", len(replaceAbs))
	}
	matches := xmlPartySkillRowRE.FindAllIndex(target, -1)
	var out bytes.Buffer
	last := 0
	for i, loc := range matches {
		out.Write(target[last:loc[0]])
		if r, ok := replaceAbs[i]; ok {
			out.Write(r)
		} else {
			out.Write(target[loc[0]:loc[1]])
		}
		last = loc[1]
	}
	out.Write(target[last:])
	return out.Bytes(), len(replaceAbs), nil
}

func regateSecondLightDualPanels(input []byte) ([]byte, int, error) {
	matches := xmlFreeAchievementRowRE.FindAllIndex(input, -1)
	type item struct {
		idx int
		p2  string
	}
	todo := []item{}
	for i, loc := range matches {
		a := xmlAttrs(input[loc[0]:loc[1]])
		if !strings.HasPrefix(a["Name"], "DLC_") || a["Prm1"] != "1181" {
			continue
		}
		todo = append(todo, item{i, a["Prm2"]})
	}
	if len(todo) == 0 {
		return input, 0, nil
	}
	if len(todo) != 4 {
		return nil, 0, fmt.Errorf("Resonance Tide panel count=%d, expected 4", len(todo))
	}
	mapping := map[string]string{"3110": "3110", "4620": "4620", "2660": "2660", "": "67"}
	seen := map[string]bool{}
	replace := map[int][]byte{}
	for _, it := range todo {
		newFlag, ok := mapping[it.p2]
		if !ok {
			return nil, 0, fmt.Errorf("unexpected Resonance Tide Prm2=%q", it.p2)
		}
		if seen[it.p2] {
			return nil, 0, fmt.Errorf("duplicate Resonance Tide Prm2=%q", it.p2)
		}
		seen[it.p2] = true
		row := append([]byte(nil), input[matches[it.idx][0]:matches[it.idx][1]]...)
		row, _ = replaceXMLAttr(row, "Prm1", newFlag)
		row, _ = removeXMLAttr(row, "Prm2")
		replace[it.idx] = row
	}
	var out bytes.Buffer
	last := 0
	for i, loc := range matches {
		out.Write(input[last:loc[0]])
		if r, ok := replace[i]; ok {
			out.Write(r)
		} else {
			out.Write(input[loc[0]:loc[1]])
		}
		last = loc[1]
	}
	out.Write(input[last:])
	// Exactly one inert 1181 reference should remain.
	if bytes.Count(out.Bytes(), []byte(`"1181"`)) != 1 {
		return nil, 0, fmt.Errorf("unexpected surviving entitlement 1181 reference count")
	}
	return out.Bytes(), len(todo), nil
}

func containsString(v []string, needle string) bool {
	for _, s := range v {
		if s == needle {
			return true
		}
	}
	return false
}
