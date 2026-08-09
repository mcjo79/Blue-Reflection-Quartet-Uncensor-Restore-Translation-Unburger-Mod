package translationbundle

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

var technicalTokenRE = regexp.MustCompile(`<(?:IM\d+|KEY_ASSIGN_[A-Z0-9_]+)>`)

type sourceUnit struct {
	Type    string         `json:"type"`
	Records []sourceRecord `json:"records"`
}

type sourceRecord struct {
	Index       int            `json:"index"`
	LogicalID   string         `json:"logical_id"`
	MsgID       *uint32        `json:"msg_id"`
	StringNo    string         `json:"string_no"`
	StringID    string         `json:"string_id"`
	Metadata    map[string]any `json:"metadata"`
	JP          string         `json:"jp"`
	ENOriginal  *string        `json:"en_original"`
	ENAuxiliary *string        `json:"en_auxiliary"`
	EN          string         `json:"en"`
	Alignment   struct {
		TargetIndices map[string]*int   `json:"target_indices"`
		TargetMapping map[string]string `json:"target_mapping"`
	} `json:"alignment"`
}

type quartetPolicyFile struct {
	Type          string `json:"type"`
	FormatVersion int    `json:"format_version"`
	TargetID      string `json:"target_id"`
	Policy        struct {
		AllowRedacted bool   `json:"allow_redacted_target_import"`
		Marker        string `json:"redacted_target_marker"`
	} `json:"policy"`
	Records []quartetPolicyRecord `json:"records"`
}

type quartetPolicyRecord struct {
	LogicalID              string   `json:"logical_id"`
	SourceJPSHA256         string   `json:"source_jp_sha256"`
	TargetTemplateENSHA256 string   `json:"target_template_en_sha256"`
	Action                 string   `json:"action"`
	SourceTokens           []string `json:"source_tokens"`
	TargetTokens           []string `json:"target_tokens"`
	Replacements           []struct {
		Old                 string `json:"old"`
		New                 string `json:"new"`
		ExpectedOccurrences int    `json:"expected_occurrences"`
	} `json:"replacements"`
}

type targetRule struct {
	Project        string
	TargetID       string
	EventArchive   string
	SystemArchive  string
	EventPrefix    string
	SystemPrefix   string
	BaselineSource string
	QuartetAdapt   bool
}

var targetRules = []targetRule{
	{Project: "blue_reflection", TargetID: "blue_reflection_original", EventArchive: "DATA/PACK01.PAK", SystemArchive: "DATA/PACK02_1.PAK", EventPrefix: `\event\event_en\`, SystemPrefix: `\saves_en\text\`, BaselineSource: "original"},
	{Project: "blue_reflection", TargetID: "blue_reflection_quartet", EventArchive: "Data/PACK11.PAK", SystemArchive: "Data/PACK12.PAK", EventPrefix: `\event\b1\event_en\`, SystemPrefix: `\saves\b1\text_en\`, BaselineSource: "auxiliary", QuartetAdapt: true},
	{Project: "blue_reflection_ray", TargetID: "blue_reflection_ray_quartet", EventArchive: "Data/PACK01_01.PAK", SystemArchive: "Data/PACK02_01.PAK", EventPrefix: `\event\b2\event_en\`, SystemPrefix: `\saves\b2\text_en\`, BaselineSource: "original"},
	{Project: "blue_reflection_sun", TargetID: "blue_reflection_sun_quartet", EventArchive: "Data/PACK01_02.PAK", SystemArchive: "Data/PACK02_02.PAK", EventPrefix: `\event\b3\event_en\`, SystemPrefix: `\saves\b3\text_en\`, BaselineSource: "original"},
	{Project: "second_light", TargetID: "second_light_original", EventArchive: "Data/PACK01.PAK", SystemArchive: "Data/PACK02.PAK", EventPrefix: `\event\event_en\`, SystemPrefix: `\saves\text_en\`, BaselineSource: "original"},
	{Project: "second_light", TargetID: "second_light_quartet", EventArchive: "Data/PACK01_03.PAK", SystemArchive: "Data/PACK02_03.PAK", EventPrefix: `\event\b4\event_en\`, SystemPrefix: `\saves\b4\text_en\`, BaselineSource: "auxiliary"},
}

func textHash(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

func readTrimmed(path string) (string, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	v := strings.TrimSpace(string(b))
	if v == "" {
		return "", fmt.Errorf("empty file: %s", path)
	}
	return v, nil
}

func loadQuartetPolicy(projectRoot string) (map[string]quartetPolicyRecord, quartetPolicyFile, error) {
	path := filepath.Join(projectRoot, "workstreams", "translation_tooling", "config", "quartet_target_adaptations.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, quartetPolicyFile{}, err
	}
	var policy quartetPolicyFile
	if err := json.Unmarshal(data, &policy); err != nil {
		return nil, policy, err
	}
	if policy.Type != "br_quartet_target_adaptation_policy" || policy.FormatVersion != 1 || policy.TargetID != "blue_reflection_quartet" {
		return nil, policy, fmt.Errorf("unsupported Quartet target adaptation policy")
	}
	byID := map[string]quartetPolicyRecord{}
	for _, entry := range policy.Records {
		if entry.LogicalID == "" {
			return nil, policy, fmt.Errorf("Quartet policy record has empty logical_id")
		}
		if _, exists := byID[entry.LogicalID]; exists {
			return nil, policy, fmt.Errorf("duplicate Quartet policy record: %s", entry.LogicalID)
		}
		byID[entry.LogicalID] = entry
	}
	return byID, policy, nil
}

func baselineText(record sourceRecord, rule targetRule) (string, bool) {
	if rule.BaselineSource == "auxiliary" && record.ENAuxiliary != nil {
		return *record.ENAuxiliary, true
	}
	if record.ENOriginal != nil {
		return *record.ENOriginal, true
	}
	return "", false
}

func replaceTokenSequence(text string, expected, target []string) (string, error) {
	matches := technicalTokenRE.FindAllStringIndex(text, -1)
	actual := technicalTokenRE.FindAllString(text, -1)
	if len(actual) != len(expected) || len(actual) != len(target) {
		return "", fmt.Errorf("technical token count changed")
	}
	for i := range actual {
		if actual[i] != expected[i] {
			return "", fmt.Errorf("technical token source changed")
		}
	}
	var b strings.Builder
	cursor := 0
	for i, m := range matches {
		b.WriteString(text[cursor:m[0]])
		b.WriteString(target[i])
		cursor = m[1]
	}
	b.WriteString(text[cursor:])
	return b.String(), nil
}

func desiredForTarget(record sourceRecord, rule targetRule, policies map[string]quartetPolicyRecord, policy quartetPolicyFile) (string, bool, error) {
	desired := record.EN
	if !rule.QuartetAdapt {
		return desired, true, nil
	}
	baseline, baselineOK := baselineText(record, rule)
	entry, classified := policies[record.LogicalID]
	if !classified {
		// The canonical Translation tooling classifies every target-specific
		// structural/token difference. If no rule exists, the editable text is
		// shared directly with the Quartet target.
		return desired, true, nil
	}
	if entry.SourceJPSHA256 != "" && !strings.EqualFold(entry.SourceJPSHA256, textHash(record.JP)) {
		return "", false, fmt.Errorf("Quartet source fingerprint changed for %s", record.LogicalID)
	}
	if baselineOK && entry.TargetTemplateENSHA256 != "" && !strings.EqualFold(entry.TargetTemplateENSHA256, textHash(baseline)) {
		return "", false, fmt.Errorf("Quartet target template fingerprint changed for %s", record.LogicalID)
	}
	switch entry.Action {
	case "shared_translation_allowed":
		return desired, true, nil
	case "preserve_target_template":
		return "", false, nil
	case "replace_technical_token_sequence":
		adapted, err := replaceTokenSequence(desired, entry.SourceTokens, entry.TargetTokens)
		return adapted, true, err
	case "literal_replacements":
		adapted := desired
		for _, repl := range entry.Replacements {
			if repl.ExpectedOccurrences < 0 || strings.Count(adapted, repl.Old) != repl.ExpectedOccurrences {
				return "", false, fmt.Errorf("Quartet replacement source changed for %s", record.LogicalID)
			}
			adapted = strings.ReplaceAll(adapted, repl.Old, repl.New)
		}
		return adapted, true, nil
	default:
		return "", false, fmt.Errorf("unsupported Quartet adaptation action %q for %s", entry.Action, record.LogicalID)
	}
}

func parseLogicalMember(record sourceRecord, unitType string) (kind, relative string, err error) {
	parts := strings.Split(record.LogicalID, ":")
	if len(parts) < 3 {
		return "", "", fmt.Errorf("invalid logical_id: %s", record.LogicalID)
	}
	if unitType == "br_event_translation_unit" {
		marker := ":event:"
		if strings.Contains(record.LogicalID, ":event_quartet_extension:") {
			marker = ":event_quartet_extension:"
		}
		pos := strings.Index(record.LogicalID, marker)
		if pos < 0 {
			return "", "", fmt.Errorf("event logical_id has no member path: %s", record.LogicalID)
		}
		tail := record.LogicalID[pos+len(marker):]
		end := strings.Index(tail, ":source_index:")
		if end < 0 {
			return "", "", fmt.Errorf("event logical_id has no source index: %s", record.LogicalID)
		}
		relative = tail[:end]
		return "ebm", strings.ReplaceAll(relative, "/", `\`), nil
	}
	if unitType == "br_system_translation_unit" {
		marker := ":system:"
		pos := strings.Index(record.LogicalID, marker)
		if pos < 0 {
			return "", "", fmt.Errorf("system logical_id has no member path: %s", record.LogicalID)
		}
		rest := record.LogicalID[pos+len(marker):]
		cut := len(rest)
		for _, suffix := range []string{":String_No:", ":String_ID:", ":index:"} {
			if p := strings.Index(rest, suffix); p >= 0 && p < cut {
				cut = p
			}
		}
		relative = rest[:cut]
		if relative == "" {
			return "", "", fmt.Errorf("system logical_id has empty member path: %s", record.LogicalID)
		}
		return "xml", strings.ReplaceAll(relative, "/", `\`), nil
	}
	return "", "", fmt.Errorf("unsupported unit type %q", unitType)
}

func metadataFromSource(raw map[string]any, msgID uint32) (*EBMMetadata, error) {
	get := func(name string) (uint32, error) {
		v, ok := raw[name]
		if !ok {
			return 0, fmt.Errorf("missing EBM metadata %s", name)
		}
		switch x := v.(type) {
		case float64:
			if x < 0 || x > 4294967295 || x != float64(uint32(x)) {
				return 0, fmt.Errorf("invalid EBM metadata %s", name)
			}
			return uint32(x), nil
		case json.Number:
			n, err := strconv.ParseUint(string(x), 10, 32)
			return uint32(n), err
		default:
			return 0, fmt.Errorf("invalid EBM metadata type for %s", name)
		}
	}
	m := &EBMMetadata{MsgID: msgID}
	var err error
	if m.Type, err = get("type"); err != nil {
		return nil, err
	}
	if m.VoiceID, err = get("voice_id"); err != nil {
		return nil, err
	}
	if m.Unknown1, err = get("unknown1"); err != nil {
		return nil, err
	}
	if m.NameID, err = get("name_id"); err != nil {
		return nil, err
	}
	if m.ExtraID, err = get("extra_id"); err != nil {
		return nil, err
	}
	if m.ExprID, err = get("expr_id"); err != nil {
		return nil, err
	}
	if m.Unknown2, err = get("unknown2"); err != nil {
		return nil, err
	}
	return m, nil
}

type memberKey struct{ target, archive, internal, kind string }

// Build creates a slim, target-aware Translation bundle from the canonical
// translation records in a project checkout. It never copies game archives,
// extracted members, or source-game workspaces into the distributable bundle.
func Build(projectRoot string) (Bundle, BuildStats, error) {
	version, err := readTrimmed(filepath.Join(projectRoot, "workstreams", "translation", "VERSION"))
	if err != nil {
		return Bundle{}, BuildStats{}, err
	}
	policies, rawPolicy, err := loadQuartetPolicy(projectRoot)
	if err != nil {
		return Bundle{}, BuildStats{}, err
	}

	groups := map[memberKey][]Record{}
	targetIndexSets := map[memberKey]map[int]string{}
	for _, rule := range targetRules {
		root := filepath.Join(projectRoot, "titles", rule.Project, "translation")
		err := filepath.WalkDir(root, func(path string, d os.DirEntry, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if d.IsDir() || !strings.HasSuffix(strings.ToLower(d.Name()), ".json") {
				return nil
			}
			data, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			var unit sourceUnit
			if err := json.Unmarshal(data, &unit); err != nil {
				return fmt.Errorf("decode %s: %w", path, err)
			}
			if unit.Type != "br_event_translation_unit" && unit.Type != "br_system_translation_unit" {
				return nil
			}
			for _, sr := range unit.Records {
				targetIndex, ok := sr.Alignment.TargetIndices[rule.TargetID]
				if !ok || targetIndex == nil {
					continue
				}
				kind, relative, err := parseLogicalMember(sr, unit.Type)
				if err != nil {
					return err
				}
				archive := rule.SystemArchive
				internal := rule.SystemPrefix + relative
				if kind == "ebm" {
					archive = rule.EventArchive
					internal = rule.EventPrefix + relative
				}
				key := memberKey{rule.TargetID, filepath.ToSlash(archive), internal, kind}
				if kind == "ebm" {
					if *targetIndex < 0 {
						return fmt.Errorf("negative target EBM index for %s", sr.LogicalID)
					}
					set := targetIndexSets[key]
					if set == nil {
						set = map[int]string{}
						targetIndexSets[key] = set
					}
					if prior, exists := set[*targetIndex]; exists && prior != sr.LogicalID {
						return fmt.Errorf("duplicate target EBM index %d for %s and %s", *targetIndex, prior, sr.LogicalID)
					}
					set[*targetIndex] = sr.LogicalID
				}
				desired, apply, err := desiredForTarget(sr, rule, policies, rawPolicy)
				if err != nil {
					return err
				}
				if !apply {
					continue
				}
				baseline, baselineOK := baselineText(sr, rule)
				if baselineOK && baseline == desired {
					continue
				}
				rec := Record{LogicalID: sr.LogicalID, TargetIndex: *targetIndex, StringNo: sr.StringNo, StringID: sr.StringID, DesiredText: desired}
				if baselineOK {
					rec.ExpectedTextSHA256 = textHash(baseline)
					rec.ExpectedTechnicalTokens = technicalTokenRE.FindAllString(baseline, -1)
				}
				if kind == "ebm" {
					if sr.MsgID == nil {
						return fmt.Errorf("event record missing msg_id: %s", sr.LogicalID)
					}
					msg := *sr.MsgID
					rec.MsgID = &msg
					meta, err := metadataFromSource(sr.Metadata, msg)
					if err != nil {
						return fmt.Errorf("%s: %w", sr.LogicalID, err)
					}
					rec.Metadata = meta
				}
				groups[key] = append(groups[key], rec)
			}
			return nil
		})
		if err != nil {
			return Bundle{}, BuildStats{}, err
		}
	}

	byTarget := map[string][]Member{}
	for key, records := range groups {
		sort.Slice(records, func(i, j int) bool {
			if records[i].TargetIndex != records[j].TargetIndex {
				return records[i].TargetIndex < records[j].TargetIndex
			}
			return records[i].LogicalID < records[j].LogicalID
		})
		targetRecordCount := 0
		if key.kind == "ebm" {
			set := targetIndexSets[key]
			if len(set) > 0 {
				complete := true
				for i := 0; i < len(set); i++ {
					if _, ok := set[i]; !ok {
						complete = false
						break
					}
				}
				if complete {
					targetRecordCount = len(set)
				}
			}
		}
		byTarget[key.target] = append(byTarget[key.target], Member{ArchiveRelativePath: key.archive, InternalPath: key.internal, Kind: key.kind, TargetRecordCount: targetRecordCount, Records: records})
	}
	bundle := Bundle{Type: "unburger_translation_records", FormatVersion: 1, TranslationVersion: version}
	stats := BuildStats{TranslationVersion: version, TargetMembers: map[string]int{}, TargetRecords: map[string]int{}}
	targetIDs := make([]string, 0, len(byTarget))
	for id := range byTarget {
		targetIDs = append(targetIDs, id)
	}
	sort.Strings(targetIDs)
	for _, id := range targetIDs {
		members := byTarget[id]
		sort.Slice(members, func(i, j int) bool {
			if members[i].ArchiveRelativePath != members[j].ArchiveRelativePath {
				return members[i].ArchiveRelativePath < members[j].ArchiveRelativePath
			}
			return strings.ToLower(members[i].InternalPath) < strings.ToLower(members[j].InternalPath)
		})
		bundle.Targets = append(bundle.Targets, TargetPack{TargetID: id, Members: members})
		stats.TargetMembers[id] = len(members)
		stats.TotalMembers += len(members)
		for _, member := range members {
			stats.TargetRecords[id] += len(member.Records)
			stats.TotalRecords += len(member.Records)
		}
	}
	return bundle, stats, nil
}

func Write(projectRoot, output string) (BuildStats, error) {
	bundle, stats, err := Build(projectRoot)
	if err != nil {
		return stats, err
	}
	data, err := json.Marshal(bundle)
	if err != nil {
		return stats, err
	}
	if err := os.MkdirAll(filepath.Dir(output), 0o755); err != nil {
		return stats, err
	}
	if err := os.WriteFile(output, append(data, '\n'), 0o644); err != nil {
		return stats, err
	}
	return stats, nil
}
