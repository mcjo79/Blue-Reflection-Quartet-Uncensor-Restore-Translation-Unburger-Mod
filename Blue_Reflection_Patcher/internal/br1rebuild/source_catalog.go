package br1rebuild

import (
	"fmt"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const (
	sourceCharacterPrefix             = `\data\x64\character\`
	targetCharacterPrefix             = `\data\b1\x64\character\`
	expectedWardrobeSourceFiles       = 264
	expectedWardrobeSourceBytes int64 = 2_413_669_897
	expectedWardrobeImports           = 244
	expectedWardrobeImportBytes int64 = 2_239_785_505
	islandFieldKey                    = "s120_dlc_beach_01"
)

var printableRunRE = regexp.MustCompile(`[\x20-\x7e]{4,}`)

func isWardrobeAssetPath(name string) bool {
	lo := strings.ToLower(name)
	if !strings.HasPrefix(lo, sourceCharacterPrefix) {
		return false
	}
	rest := strings.Split(name[len(sourceCharacterPrefix):], `\`)
	if len(rest) != 2 {
		return false
	}
	return strings.HasPrefix(strings.ToLower(rest[0]), "pc") && strings.Contains(strings.ToLower(rest[1]), "_dlc_")
}

func targetWardrobeAssetName(sourceName string) (string, bool) {
	if !isWardrobeAssetPath(sourceName) {
		return "", false
	}
	return strings.Replace(sourceName, `\data\x64\character\`, `\data\b1\x64\character\`, 1), true
}

type CharacterAssetBuildReport struct {
	SourceFiles int                `json:"source_files"`
	SourceBytes int64              `json:"source_bytes"`
	AddedFiles  int                `json:"added_files"`
	AddedBytes  int64              `json:"added_bytes"`
	Verify      ArchiveAuditResult `json:"verify"`
}

func MeasureWardrobeArchive(sourcePack string) (int, int64, error) {
	p, err := OpenA18(sourcePack)
	if err != nil {
		return 0, 0, err
	}
	defer p.Close()
	n := 0
	var b int64
	for _, e := range p.Entries {
		if isWardrobeAssetPath(e.Name) {
			n++
			b += int64(e.Size)
		}
	}
	return n, b, nil
}
func BuildCharacterAssetArchive(sourcePack, targetPack, outputPath string, progress byteProgress) (CharacterAssetBuildReport, error) {
	src, err := OpenA18(sourcePack)
	if err != nil {
		return CharacterAssetBuildReport{}, err
	}
	defer src.Close()
	q, err := OpenA22(targetPack)
	if err != nil {
		return CharacterAssetBuildReport{}, err
	}
	have := map[string]bool{}
	for _, e := range q.Entries {
		have[strings.ToLower(e.Name)] = true
	}
	q.Close()
	sourceN := 0
	var sourceB int64
	adds := map[string]ArchiveInput{}
	dig := map[string]string{}
	var total int64
	for _, e := range src.Entries {
		if !isWardrobeAssetPath(e.Name) {
			continue
		}
		sourceN++
		sourceB += int64(e.Size)
		newName, _ := targetWardrobeAssetName(e.Name)
		if have[strings.ToLower(newName)] {
			continue
		}
		s := CrossFormatEntry{src, e}
		adds[newName] = s
		d, er := s.PlainSHA256()
		if er != nil {
			return CharacterAssetBuildReport{}, er
		}
		dig[newName] = d
		total += int64(e.Size)
	}
	if sourceN != expectedWardrobeSourceFiles || sourceB != expectedWardrobeSourceBytes {
		return CharacterAssetBuildReport{}, fmt.Errorf("source costume source mismatch: %d files/%d bytes; expected %d/%d", sourceN, sourceB, expectedWardrobeSourceFiles, expectedWardrobeSourceBytes)
	}
	if len(adds) != expectedWardrobeImports || total != expectedWardrobeImportBytes {
		return CharacterAssetBuildReport{}, fmt.Errorf("costume transplant mismatch: %d files/%d bytes; expected %d/%d", len(adds), total, expectedWardrobeImports, expectedWardrobeImportBytes)
	}
	_, err = RewriteA22(targetPack, outputPath, ArchiveEdits{Additions: adds}, progress)
	if err != nil {
		return CharacterAssetBuildReport{}, err
	}
	v, err := AuditA22Rewrite(targetPack, outputPath, dig, nil, progress)
	if err != nil {
		return CharacterAssetBuildReport{}, err
	}
	if len(v.Problems) > 0 {
		return CharacterAssetBuildReport{}, fmt.Errorf("PACK10_02 verify failed: %s", strings.Join(v.Problems[:minInt(10, len(v.Problems))], "; "))
	}
	return CharacterAssetBuildReport{sourceN, sourceB, len(adds), total, v}, nil
}

type IslandMapReport struct {
	Added   int                `json:"added"`
	Bytes   int64              `json:"bytes"`
	Entries []string           `json:"entries"`
	Verify  ArchiveAuditResult `json:"verify"`
}

func planIslandMapMerge(sourcePack, targetPack string) (*ArchiveReader, map[string]ArchiveInput, map[string]string, []string, int64, error) {
	v, err := OpenA18(sourcePack)
	if err != nil {
		return nil, nil, nil, nil, 0, err
	}
	q, err := OpenA22(targetPack)
	if err != nil {
		v.Close()
		return nil, nil, nil, nil, 0, err
	}
	have := map[string]bool{}
	for _, e := range q.Entries {
		have[strings.ToLower(e.Name)] = true
	}
	q.Close()
	adds := map[string]ArchiveInput{}
	dig := map[string]string{}
	var names []string
	var total int64
	needle := `\field\` + islandFieldKey + `\`
	for _, e := range v.Entries {
		if !strings.Contains(strings.ToLower(e.Name), needle) {
			continue
		}
		newName := strings.Replace(e.Name, `\data\x64\`, `\data\b1\x64\`, 1)
		if have[strings.ToLower(newName)] {
			continue
		}
		s := CrossFormatEntry{v, e}
		adds[newName] = s
		d, er := s.PlainSHA256()
		if er != nil {
			v.Close()
			return nil, nil, nil, nil, 0, er
		}
		dig[newName] = d
		names = append(names, newName)
		total += int64(e.Size)
	}
	sort.Slice(names, func(i, j int) bool { return strings.ToLower(names[i]) < strings.ToLower(names[j]) })
	if len(adds) != 3 {
		v.Close()
		return nil, nil, nil, nil, 0, fmt.Errorf("island geometry expected 3 additions, got %d", len(adds))
	}
	return v, adds, dig, names, total, nil
}
func BuildIslandMapArchive(sourcePack, targetPack, outputPath string, progress byteProgress) (IslandMapReport, error) {
	v, adds, dig, names, total, err := planIslandMapMerge(sourcePack, targetPack)
	if err != nil {
		return IslandMapReport{}, err
	}
	defer v.Close()
	_, err = RewriteA22(targetPack, outputPath, ArchiveEdits{Additions: adds}, progress)
	if err != nil {
		return IslandMapReport{}, err
	}
	vr, err := AuditA22Rewrite(targetPack, outputPath, dig, nil, progress)
	if err != nil {
		return IslandMapReport{}, err
	}
	if len(vr.Problems) > 0 {
		return IslandMapReport{}, fmt.Errorf("PACK10_03 verify failed: %s", strings.Join(vr.Problems[:minInt(10, len(vr.Problems))], "; "))
	}
	return IslandMapReport{len(adds), total, names, vr}, nil
}

func textBytes(b []byte) int {
	n := 0
	for _, m := range printableRunRE.FindAll(b, -1) {
		n += len(m)
	}
	return n
}

type IslandEventReport struct {
	Replaced  int                `json:"replaced"`
	PerLocale map[string]int     `json:"per_locale"`
	Verify    ArchiveAuditResult `json:"verify"`
}

func BuildIslandEventArchive(sourcePack, targetPack, outputPath string, progress byteProgress) (IslandEventReport, error) {
	v, err := OpenA18(sourcePack)
	if err != nil {
		return IslandEventReport{}, err
	}
	defer v.Close()
	q, err := OpenA22(targetPack)
	if err != nil {
		return IslandEventReport{}, err
	}
	defer q.Close()
	qn := map[string]ArchiveEntry{}
	for _, e := range q.Entries {
		qn[strings.ToLower(e.Name)] = e
	}
	filesOf := func(loc string) map[string]ArchiveEntry {
		m := map[string]ArchiveEntry{}
		tag := `\` + loc + `\`
		for _, e := range v.Entries {
			lo := strings.ToLower(e.Name)
			if strings.HasSuffix(lo, ".ebm") && strings.Contains(lo, tag) {
				parts := strings.SplitN(lo, tag, 2)
				m[parts[1]] = e
			}
		}
		return m
	}
	ven := filesOf("event_en")
	stripped := map[string]bool{}
	for rel, ve := range ven {
		qe, ok := qn[`\event\b1\event_en\`+rel]
		if !ok || qe.Size >= ve.Size {
			continue
		}
		vb, er := v.Read(ve)
		if er != nil {
			return IslandEventReport{}, er
		}
		qb, er := q.Read(qe)
		if er != nil {
			return IslandEventReport{}, er
		}
		tv := textBytes(vb)
		if tv >= 40 && float64(textBytes(qb)) <= float64(tv)*0.15 {
			stripped[rel] = true
		}
	}
	locales := [][2]string{{"event_en", "event_en"}, {"event_jp", "event_jp"}, {"event_ch", "event_tc"}}
	repl := map[string]ArchiveInput{}
	per := map[string]int{}
	rels := make([]string, 0, len(stripped))
	for r := range stripped {
		rels = append(rels, r)
	}
	sort.Strings(rels)
	for _, pair := range locales {
		vf := filesOf(pair[0])
		for _, rel := range rels {
			ve, ok := vf[rel]
			if !ok {
				continue
			}
			qname := `\event\b1\` + pair[1] + `\` + rel
			qe, ok := qn[qname]
			if !ok || qe.Size >= ve.Size {
				continue
			}
			b, er := v.Read(ve)
			if er != nil {
				return IslandEventReport{}, er
			}
			repl[qe.Name] = MemoryEntry{b}
			per[pair[1]]++
		}
	}
	q.Close()
	_, err = RewriteA22(targetPack, outputPath, ArchiveEdits{Replacements: repl}, progress)
	if err != nil {
		return IslandEventReport{}, err
	}
	vr, err := AuditA22Rewrite(targetPack, outputPath, nil, repl, progress)
	if err != nil {
		return IslandEventReport{}, err
	}
	if len(vr.Problems) > 0 {
		return IslandEventReport{}, fmt.Errorf("PACK11 verify failed: %s", strings.Join(vr.Problems[:minInt(10, len(vr.Problems))], "; "))
	}
	return IslandEventReport{len(repl), per, vr}, nil
}

func ResolveContentFiles(sourceRoot, targetRoot string) (map[string]string, map[string]string) {
	sourceData, err := sourceDataDirectory(sourceRoot)
	if err != nil {
		sourceData = filepath.Join(sourceRoot, "DATA")
	}
	v := map[string]string{"exe": casePath(sourceRoot, "BLUE_REFLECTION.exe"), "pack00_02": casePath(sourceData, "PACK00_02.PAK"), "pack00_03": casePath(sourceData, "PACK00_03.PAK"), "pack01": casePath(sourceData, "PACK01.PAK")}
	qd := filepath.Join(targetRoot, "Data")
	q := map[string]string{"dll": filepath.Join(targetRoot, "B1.dll"), "pack10_02": casePath(qd, "PACK10_02.PAK"), "pack10_03": casePath(qd, "PACK10_03.PAK"), "pack11": casePath(qd, "PACK11.PAK"), "pack12": casePath(qd, "PACK12.PAK")}
	return v, q
}
