package quartetdlc

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"local/blue-reflection-patcher/internal/br1rebuild"
)

const SecondLightDLCFamilyCapability = "quartet_second_light_dlc_restore_v1"

type SecondLightProgress func(stage, item string, done, total, overallDone, overallTotal int64)

type SecondLightBuildOptions struct {
	SourceRoot      string
	TargetRoot      string
	Workspace       string
	TargetOverrides map[string]string
	TextTool        br1rebuild.EncryptedTextTool
}

type secondLightProgressTracker struct {
	callback  SecondLightProgress
	total     int64
	completed int64
}

func newSecondLightProgressTracker(callback SecondLightProgress, weights ...int64) *secondLightProgressTracker {
	t := &secondLightProgressTracker{callback: callback}
	for _, weight := range weights {
		if weight > 0 {
			t.total += weight
		}
	}
	return t
}

func (t *secondLightProgressTracker) status(stage, item string) {
	if t != nil && t.callback != nil {
		t.callback(stage, item, 0, 0, t.completed, t.total)
	}
}

func (t *secondLightProgressTracker) byteCallback(stage string, weight int64) br1rebuild.ByteProgressFunc {
	return func(_ string, name string, done, total int64) {
		if t == nil || t.callback == nil {
			return
		}
		scaled := int64(0)
		if total > 0 && weight > 0 {
			scaled = done * weight / total
			if scaled > weight {
				scaled = weight
			}
		}
		t.callback(stage, name, done, total, t.completed+scaled, t.total)
	}
}

func (t *secondLightProgressTracker) finishStep(weight int64) {
	if t == nil || weight <= 0 {
		return
	}
	t.completed += weight
	if t.completed > t.total {
		t.completed = t.total
	}
}

func secondLightFileSize(path string) int64 {
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() {
		return 0
	}
	return info.Size()
}

type SecondLightBuildAudit struct {
	Capability             string            `json:"capability"`
	DialogueMembers        int               `json:"dialogue_members"`
	DialogueMessages       int               `json:"dialogue_messages"`
	UIStringMembers        int               `json:"ui_string_members"`
	UIStrings              int               `json:"ui_strings"`
	MapMembersAdded        int               `json:"map_members_added"`
	ModelMembersAdded      int               `json:"model_members_added"`
	CostumeRepointedRows   int               `json:"costume_repointed_rows"`
	CostumeOpenedRows      int               `json:"costume_opened_rows"`
	CostumeReclosedRows    int               `json:"costume_reclosed_rows"`
	ScenarioRowsRegated    int               `json:"scenario_rows_regated"`
	FacilityPlotChanged    bool              `json:"facility_plot_changed"`
	ResonanceRowsRestored  int               `json:"resonance_rows_restored"`
	ResonancePanelsRegated int               `json:"resonance_panels_regated"`
	StreamRoutesChanged    int               `json:"stream_routes_changed"`
	StubSoundsRemoved      int               `json:"stub_sounds_removed"`
	AudioSectionsConverted int               `json:"audio_sections_converted"`
	AudioStreamsEncrypted  int               `json:"audio_streams_encrypted"`
	CauldronPointerChanged bool              `json:"cauldron_pointer_changed"`
	OutputSHA256           map[string]string `json:"output_sha256"`
	OutputBytes            map[string]int64  `json:"output_bytes"`
}

func (a SecondLightBuildAudit) Ready() bool {
	// Steam 1.04 -> Quartet closure established by the real-input parity audit.
	// This is intentionally conjunctive: a partially restored family must never
	// be promoted to a transaction merely because one counter is non-zero.
	return a.Capability == SecondLightDLCFamilyCapability &&
		a.DialogueMembers == 466 && a.DialogueMessages == 7217 &&
		a.UIStringMembers == 105 && a.UIStrings == 2536 &&
		a.MapMembersAdded == 41 && a.ModelMembersAdded == 264 &&
		a.CostumeRepointedRows == 106 && a.CostumeOpenedRows == 78 && a.CostumeReclosedRows == 2 &&
		a.ScenarioRowsRegated == 15 && a.FacilityPlotChanged &&
		a.ResonanceRowsRestored == 10 && a.ResonancePanelsRegated == 4 &&
		a.StreamRoutesChanged == 6 && a.StubSoundsRemoved == 6 &&
		a.AudioSectionsConverted == 12 && a.AudioStreamsEncrypted == 6 &&
		a.CauldronPointerChanged && len(a.OutputSHA256) == len(a.OutputBytes) && len(a.OutputSHA256) == 8
}

func ComposeSecondLightDLC(opts SecondLightBuildOptions, progress SecondLightProgress) (SecondLightBuildAudit, map[string]string, error) {
	audit := SecondLightBuildAudit{Capability: SecondLightDLCFamilyCapability, OutputSHA256: map[string]string{}, OutputBytes: map[string]int64{}}
	if strings.TrimSpace(opts.SourceRoot) == "" || strings.TrimSpace(opts.TargetRoot) == "" || strings.TrimSpace(opts.Workspace) == "" {
		return audit, nil, fmt.Errorf("Second Light source, Quartet target and workspace are required")
	}
	if err := ValidateSecondLightSource(opts.SourceRoot); err != nil {
		return audit, nil, err
	}
	if err := os.MkdirAll(opts.Workspace, 0o755); err != nil {
		return audit, nil, err
	}
	if opts.TargetOverrides == nil {
		opts.TargetOverrides = map[string]string{}
	}
	outputs := map[string]string{}

	sourceData := filepath.Join(opts.SourceRoot, "Data")
	paths := struct{ models, field, events, data string }{filepath.Join(sourceData, "PACK00_02.PAK"), filepath.Join(sourceData, "PACK00_03.PAK"), filepath.Join(sourceData, "PACK01.PAK"), filepath.Join(sourceData, "PACK02.PAK")}
	targetModelsPath := secondLightTargetInput(opts, "Data/PACK00_02.PAK")
	targetFieldPath := secondLightTargetInput(opts, "Data/PACK00_03.PAK")
	targetEventsPath := secondLightTargetInput(opts, "Data/PACK01_03.PAK")
	targetDataPath := secondLightTargetInput(opts, "Data/PACK02_03.PAK")
	modelWeight := secondLightFileSize(targetModelsPath)
	fieldWeight := secondLightFileSize(targetFieldPath)
	eventWeight := secondLightFileSize(targetEventsPath)
	dataWeight := secondLightFileSize(targetDataPath)
	archiveWork := int64(2) * (modelWeight + fieldWeight + eventWeight + dataWeight)
	tracker := newSecondLightProgressTracker(progress, archiveWork)

	// Read table inputs first so the model archive and PACK02 composition agree on the same closure.
	srcData, err := br1rebuild.OpenA22(paths.data)
	if err != nil {
		return audit, nil, fmt.Errorf("open Second Light PACK02: %w", err)
	}
	defer srcData.Close()
	tgtData, err := br1rebuild.OpenA22(targetDataPath)
	if err != nil {
		return audit, nil, fmt.Errorf("open Quartet PACK02_03: %w", err)
	}
	defer tgtData.Close()
	get := func(p *br1rebuild.ArchiveReader, name string) ([]byte, error) {
		e, ok := p.Find(name)
		if !ok {
			return nil, fmt.Errorf("archive member missing: %s", name)
		}
		return p.Read(e)
	}
	qChara, err := get(tgtData, `\saves\b4\chara\charabase.xml`)
	if err != nil {
		return audit, nil, err
	}
	sChara, err := get(srcData, `\saves\chara\charabase.xml`)
	if err != nil {
		return audit, nil, err
	}
	qCostume, err := get(tgtData, `\saves\b4\costume\costume_body.xml`)
	if err != nil {
		return audit, nil, err
	}
	sCostume, err := get(srcData, `\saves\costume\costume_body.xml`)
	if err != nil {
		return audit, nil, err
	}
	qCostumeModel, err := get(tgtData, `\saves\b4\costume\costume_model.xml`)
	if err != nil {
		return audit, nil, err
	}

	srcModels, err := br1rebuild.OpenA22(paths.models)
	if err != nil {
		return audit, nil, fmt.Errorf("open Second Light PACK00_02: %w", err)
	}
	defer srcModels.Close()
	tgtModels, err := br1rebuild.OpenA22(targetModelsPath)
	if err != nil {
		return audit, nil, fmt.Errorf("open Quartet PACK00_02: %w", err)
	}
	defer tgtModels.Close()
	sourceFolders := secondLightCharacterFolders(srcModels, `\data\x64\character\`)
	targetFolders := secondLightCharacterFolders(tgtModels, `\data\b4\x64\character\`)
	newChara, newCostume, costumeAudit, err := patchSecondLightCostumeTables(qChara, sChara, qCostume, sCostume, qCostumeModel, sourceFolders, targetFolders)
	if err != nil {
		return audit, nil, err
	}
	audit.CostumeRepointedRows = costumeAudit.RepointedRows
	audit.CostumeOpenedRows = costumeAudit.OpenedRows
	audit.CostumeReclosedRows = costumeAudit.ReclosedRows

	// PACK00_02: add every source character folder absent from b4, preserving target-native members.
	tracker.status("second_light_models", "Collecting missing Second Light costume model members")
	modelAdds := map[string]br1rebuild.ArchiveInput{}
	modelDigests := map[string]string{}
	for _, e := range srcModels.Entries {
		low := strings.ToLower(e.Name)
		pre := `\data\x64\character\`
		if !strings.HasPrefix(low, pre) {
			continue
		}
		rel := e.Name[len(pre):]
		dst := `\data\b4\x64\character\` + rel
		if _, exists := tgtModels.Find(dst); exists {
			continue
		}
		modelAdds[dst] = br1rebuild.CrossFormatEntry{Pak: srcModels, Entry: e}
		dig, derr := srcModels.PlainDigest(e)
		if derr != nil {
			return audit, nil, derr
		}
		modelDigests[dst] = dig
	}
	if len(modelAdds) > 0 {
		out := filepath.Join(opts.Workspace, "PACK00_02.PAK")
		stats, err := br1rebuild.RewriteA22(targetModelsPath, out, br1rebuild.ArchiveEdits{Additions: modelAdds}, tracker.byteCallback("second_light_models_build", modelWeight))
		if err != nil {
			return audit, nil, err
		}
		tracker.finishStep(modelWeight)
		vr, err := br1rebuild.AuditA22Rewrite(targetModelsPath, out, modelDigests, nil, tracker.byteCallback("second_light_models_verify", modelWeight))
		if err != nil {
			return audit, nil, err
		}
		if len(vr.Problems) > 0 {
			return audit, nil, fmt.Errorf("Second Light model archive audit: %s", strings.Join(vr.Problems, "; "))
		}
		tracker.finishStep(modelWeight)
		outputs["Data/PACK00_02.PAK"] = out
		audit.OutputSHA256["Data/PACK00_02.PAK"] = stats.OutputSHA256
		audit.OutputBytes["Data/PACK00_02.PAK"] = stats.SizeAfter
		audit.ModelMembersAdded = len(modelAdds)
	}

	// PACK00_03: the two DLC map families plus all battle arenas they preload.
	tracker.status("second_light_maps", "Collecting DLC field and battle-stage members")
	srcField, err := br1rebuild.OpenA22(paths.field)
	if err != nil {
		return audit, nil, err
	}
	defer srcField.Close()
	tgtField, err := br1rebuild.OpenA22(targetFieldPath)
	if err != nil {
		return audit, nil, err
	}
	defer tgtField.Close()
	wantedFolders := map[string]bool{"st110_00": true, "st120_00": true, "st120_01": true, "st120_02": true, "bt300": true, "bt305": true, "bt400": true, "bt410": true, "bt420": true}
	fieldAdds := map[string]br1rebuild.ArchiveInput{}
	fieldDigests := map[string]string{}
	for _, e := range srcField.Entries {
		pre := `\data\x64\field\`
		if !strings.HasPrefix(strings.ToLower(e.Name), pre) {
			continue
		}
		rel := e.Name[len(pre):]
		folder := strings.SplitN(rel, `\`, 2)[0]
		if !wantedFolders[strings.ToLower(folder)] {
			continue
		}
		dst := `\data\b4\x64\field\` + rel
		if _, ok := tgtField.Find(dst); ok {
			continue
		}
		fieldAdds[dst] = br1rebuild.CrossFormatEntry{Pak: srcField, Entry: e}
		dig, derr := srcField.PlainDigest(e)
		if derr != nil {
			return audit, nil, derr
		}
		fieldDigests[dst] = dig
	}
	if len(fieldAdds) > 0 {
		out := filepath.Join(opts.Workspace, "PACK00_03.PAK")
		stats, err := br1rebuild.RewriteA22(targetFieldPath, out, br1rebuild.ArchiveEdits{Additions: fieldAdds}, tracker.byteCallback("second_light_maps_build", fieldWeight))
		if err != nil {
			return audit, nil, err
		}
		tracker.finishStep(fieldWeight)
		vr, err := br1rebuild.AuditA22Rewrite(targetFieldPath, out, fieldDigests, nil, tracker.byteCallback("second_light_maps_verify", fieldWeight))
		if err != nil {
			return audit, nil, err
		}
		if len(vr.Problems) > 0 {
			return audit, nil, fmt.Errorf("Second Light field archive audit: %s", strings.Join(vr.Problems, "; "))
		}
		tracker.finishStep(fieldWeight)
		outputs["Data/PACK00_03.PAK"] = out
		audit.OutputSHA256["Data/PACK00_03.PAK"] = stats.OutputSHA256
		audit.OutputBytes["Data/PACK00_03.PAK"] = stats.SizeAfter
		audit.MapMembersAdded = len(fieldAdds)
	}

	// PACK01_03: one robust in-process EBM pass handles both ordinary blank dialogue and popup records.
	tracker.status("second_light_dialogue", "Restoring blanked Second Light DLC messages")
	srcEvents, err := br1rebuild.OpenA22(paths.events)
	if err != nil {
		return audit, nil, err
	}
	defer srcEvents.Close()
	tgtEvents, err := br1rebuild.OpenA22(targetEventsPath)
	if err != nil {
		return audit, nil, err
	}
	defer tgtEvents.Close()
	eventRepl := map[string]br1rebuild.ArchiveInput{}
	folders := map[string]bool{}
	for _, f := range []string{"xf01", "xf02", "xf03", "xf04", "xx00", "dm01", "dm02", "dm03", "dm04", "dm05", "dm08", "dm09", "dm10", "dm11", "sd00", "xs04", "xs07"} {
		folders[f] = true
	}
	for _, qe := range tgtEvents.Entries {
		parts := strings.Split(strings.TrimPrefix(strings.ToLower(qe.Name), `\`), `\`)
		if len(parts) < 5 || parts[0] != "event" || parts[1] != "b4" || !folders[parts[3]] || !strings.HasSuffix(parts[len(parts)-1], ".ebm") {
			continue
		}
		lang := parts[2]
		if lang != "event_en" && lang != "event_jp" && lang != "event_sc" && lang != "event_tc" {
			continue
		}
		sourceName := `\event\` + strings.Join(parts[2:], `\`)
		se, ok := srcEvents.Find(sourceName)
		if !ok {
			continue
		}
		qb, er := tgtEvents.Read(qe)
		if er != nil {
			return audit, nil, er
		}
		sb, er := srcEvents.Read(se)
		if er != nil {
			return audit, nil, er
		}
		patched, n, er := restoreSecondLightEBMText(qb, sb)
		if er != nil {
			return audit, nil, fmt.Errorf("restore %s: %w", qe.Name, er)
		}
		if n == 0 {
			continue
		}
		eventRepl[qe.Name] = br1rebuild.MemoryEntry{Data: patched}
		audit.DialogueMembers++
		audit.DialogueMessages += n
	}
	if len(eventRepl) > 0 {
		out := filepath.Join(opts.Workspace, "PACK01_03.PAK")
		stats, err := br1rebuild.RewriteA22(targetEventsPath, out, br1rebuild.ArchiveEdits{Replacements: eventRepl}, tracker.byteCallback("second_light_dialogue_build", eventWeight))
		if err != nil {
			return audit, nil, err
		}
		tracker.finishStep(eventWeight)
		vr, err := br1rebuild.AuditA22Rewrite(targetEventsPath, out, nil, eventRepl, tracker.byteCallback("second_light_dialogue_verify", eventWeight))
		if err != nil {
			return audit, nil, err
		}
		if len(vr.Problems) > 0 {
			return audit, nil, fmt.Errorf("Second Light dialogue archive audit: %s", strings.Join(vr.Problems, "; "))
		}
		tracker.finishStep(eventWeight)
		outputs["Data/PACK01_03.PAK"] = out
		audit.OutputSHA256["Data/PACK01_03.PAK"] = stats.OutputSHA256
		audit.OutputBytes["Data/PACK01_03.PAK"] = stats.SizeAfter
	}

	// PACK02_03: all data-table changes are composed in memory and written once.
	tracker.status("second_light_tables", "Composing Second Light DLC data tables")
	dataRepl := map[string]br1rebuild.ArchiveInput{}
	put := func(name string, data []byte) error {
		dataRepl[name] = br1rebuild.MemoryEntry{Data: data}
		if _, ok := tgtData.Find(name + ".e"); ok {
			cipher, er := opts.TextTool.EncryptA21(data)
			if er != nil {
				return er
			}
			plain, er := opts.TextTool.DecryptA21(cipher)
			if er != nil {
				return er
			}
			if string(plain) != string(data) {
				return fmt.Errorf("A21 round-trip mismatch for %s", name)
			}
			dataRepl[name+".e"] = br1rebuild.MemoryEntry{Data: cipher}
		}
		return nil
	}
	if err := put(`\saves\b4\chara\charabase.xml`, newChara); err != nil {
		return audit, nil, err
	}
	if err := put(`\saves\b4\costume\costume_body.xml`, newCostume); err != nil {
		return audit, nil, err
	}

	// UI/menu strings: match by String_ID and restore only blank target values.
	for _, qe := range tgtData.Entries {
		low := strings.ToLower(qe.Name)
		if !strings.HasSuffix(low, ".xml") || !strings.Contains(low, `\b4\text_`) {
			continue
		}
		base := qe.Name[strings.LastIndex(qe.Name, `\`)+1:]
		parts := strings.Split(strings.TrimPrefix(low, `\`), `\`)
		langIndex := -1
		for i, p := range parts {
			if strings.HasPrefix(p, "text_") {
				langIndex = i
				break
			}
		}
		if langIndex < 0 {
			continue
		}
		sourceName := `\saves\` + parts[langIndex] + `\` + base
		se, ok := srcData.Find(sourceName)
		if !ok {
			continue
		}
		qb, er := tgtData.Read(qe)
		if er != nil {
			return audit, nil, er
		}
		sb, er := srcData.Read(se)
		if er != nil {
			return audit, nil, er
		}
		patched, n, er := restoreBlankSecondLightStrings(qb, sb)
		if er != nil {
			return audit, nil, er
		}
		if n > 0 {
			if err := put(qe.Name, patched); err != nil {
				return audit, nil, err
			}
			audit.UIStringMembers++
			audit.UIStrings += n
		}
	}

	// Scenario gates, facility plot, Resonance Tide skill rows and Talent visibility.
	chapterName, chapterRaw, err := readA22MemberBySuffix(tgtData, "/b4/scenario/chapter_99.xml")
	if err != nil {
		return audit, nil, err
	}
	chapterNew, n, err := regateSecondLightScenario(chapterRaw)
	if err != nil {
		return audit, nil, err
	}
	audit.ScenarioRowsRegated = n
	if n > 0 {
		if err := put(chapterName, chapterNew); err != nil {
			return audit, nil, err
		}
	}
	placeName, placeRaw, err := readA22MemberBySuffix(tgtData, "/b4/schooldev/place.xml")
	if err != nil {
		return audit, nil, err
	}
	placeNew, changed, err := enableSecondLightFacilityPlot(placeRaw)
	if err != nil {
		return audit, nil, err
	}
	audit.FacilityPlotChanged = changed
	if changed {
		if err := put(placeName, placeNew); err != nil {
			return audit, nil, err
		}
	}
	skillName, skillRaw, err := readA22MemberBySuffix(tgtData, "/b4/party/party_skill.xml")
	if err != nil {
		return audit, nil, err
	}
	_, sourceSkill, err := readA22MemberBySuffix(srcData, "/party/party_skill.xml")
	if err != nil {
		return audit, nil, err
	}
	skillNew, n, err := restoreSecondLightDualSkills(skillRaw, sourceSkill)
	if err != nil {
		return audit, nil, err
	}
	audit.ResonanceRowsRestored = n
	if n > 0 {
		if err := put(skillName, skillNew); err != nil {
			return audit, nil, err
		}
	}
	panelName, panelRaw, err := readA22MemberBySuffix(tgtData, "/b4/achievement/freeachievement.xml")
	if err != nil {
		return audit, nil, err
	}
	panelNew, n, err := regateSecondLightDualPanels(panelRaw)
	if err != nil {
		return audit, nil, err
	}
	audit.ResonancePanelsRegated = n
	if n > 0 {
		if err := put(panelName, panelNew); err != nil {
			return audit, nil, err
		}
	}

	// Audio route table. The loose banks and Seed_BGM are produced below.
	streamName, streamRaw, err := readA22MemberBySuffix(tgtData, "/b4/sound/stream.xml")
	if err != nil {
		return audit, nil, err
	}
	streamNew, n, err := routeSecondLightCollabAudio(streamRaw)
	if err != nil {
		return audit, nil, err
	}
	audit.StreamRoutesChanged = n
	if n > 0 {
		if err := put(streamName, streamNew); err != nil {
			return audit, nil, err
		}
	}

	dataOut := filepath.Join(opts.Workspace, "PACK02_03.PAK")
	dataStats, err := br1rebuild.RewriteA22(targetDataPath, dataOut, br1rebuild.ArchiveEdits{Replacements: dataRepl}, tracker.byteCallback("second_light_tables_build", dataWeight))
	if err != nil {
		return audit, nil, err
	}
	tracker.finishStep(dataWeight)
	vr, err := br1rebuild.AuditA22Rewrite(targetDataPath, dataOut, nil, dataRepl, tracker.byteCallback("second_light_tables_verify", dataWeight))
	if err != nil {
		return audit, nil, err
	}
	if len(vr.Problems) > 0 {
		return audit, nil, fmt.Errorf("Second Light data archive audit: %s", strings.Join(vr.Problems, "; "))
	}
	tracker.finishStep(dataWeight)
	outputs["Data/PACK02_03.PAK"] = dataOut
	audit.OutputSHA256["Data/PACK02_03.PAK"] = dataStats.OutputSHA256
	audit.OutputBytes["Data/PACK02_03.PAK"] = dataStats.SizeAfter

	// Ryza collaboration audio and target Seed_BGM shadow records.
	tracker.status("second_light_audio", "Converting and encrypting collaboration audio")
	audioOutputs, audioAudit, err := buildSecondLightAudio(filepath.Join(opts.SourceRoot, "Data", "x64", "Sound"), filepath.Join(opts.TargetRoot, "Data", "B4", "x64", "Sound"), opts.Workspace, opts.TargetOverrides)
	if err != nil {
		return audit, nil, err
	}
	for k, v := range audioOutputs {
		outputs[k] = v
	}
	audit.StubSoundsRemoved = audioAudit.StubsRemoved
	audit.AudioSectionsConverted = audioAudit.ConvertedSections
	audit.AudioStreamsEncrypted = audioAudit.EncryptedStreams

	// Quartet's latent Cauldron path bug: change only the miswired pointer slot.
	dllInput := secondLightTargetInput(opts, "B4.dll")
	dllBytes, err := os.ReadFile(dllInput)
	if err != nil {
		return audit, nil, err
	}
	dllNew, dllChanged, err := fixSecondLightCauldronPointer(dllBytes)
	if err != nil {
		return audit, nil, err
	}
	audit.CauldronPointerChanged = dllChanged
	if dllChanged {
		dllOut := filepath.Join(opts.Workspace, "B4.dll")
		if err := os.WriteFile(dllOut, dllNew, 0o644); err != nil {
			return audit, nil, err
		}
		outputs["B4.dll"] = dllOut
	}

	for rel, path := range outputs {
		if _, ok := audit.OutputSHA256[rel]; !ok {
			sum, err := fileSHA256(path)
			if err != nil {
				return audit, nil, err
			}
			audit.OutputSHA256[rel] = sum
		}
		if _, ok := audit.OutputBytes[rel]; !ok {
			info, err := os.Stat(path)
			if err != nil {
				return audit, nil, err
			}
			audit.OutputBytes[rel] = info.Size()
		}
	}
	return audit, outputs, nil
}

func ValidateSecondLightSource(root string) error {
	required := []string{"Data/PACK00_02.PAK", "Data/PACK00_03.PAK", "Data/PACK01.PAK", "Data/PACK02.PAK", "Data/x64/Sound/Le0000_BGM.ktsl2asbin", "Data/x64/Sound/Le0000_BGM.ktsl2stbin"}
	for _, rel := range required {
		p := filepath.Join(root, filepath.FromSlash(rel))
		info, err := os.Stat(p)
		if err != nil || !info.Mode().IsRegular() {
			return fmt.Errorf("Second Light source missing %s", rel)
		}
	}
	return nil
}

func secondLightTargetInput(opts SecondLightBuildOptions, rel string) string {
	if p := opts.TargetOverrides[filepath.ToSlash(rel)]; strings.TrimSpace(p) != "" {
		return p
	}
	return filepath.Join(opts.TargetRoot, filepath.FromSlash(rel))
}

func secondLightCharacterFolders(p *br1rebuild.ArchiveReader, prefix string) map[string]bool {
	out := map[string]bool{}
	lowPre := strings.ToLower(prefix)
	for _, e := range p.Entries {
		low := strings.ToLower(e.Name)
		if strings.HasPrefix(low, lowPre) {
			rel := e.Name[len(prefix):]
			folder := strings.SplitN(rel, `\`, 2)[0]
			if folder != "" {
				out[folder] = true
			}
		}
	}
	return out
}

func readA22MemberBySuffix(p *br1rebuild.ArchiveReader, suffix string) (string, []byte, error) {
	norm := strings.ToLower(strings.ReplaceAll(suffix, `\`, "/"))
	var hit *br1rebuild.ArchiveEntry
	for i := range p.Entries {
		n := strings.ToLower(strings.ReplaceAll(p.Entries[i].Name, `\`, "/"))
		if strings.HasSuffix(n, norm) {
			if hit != nil {
				return "", nil, fmt.Errorf("multiple archive members end with %s", suffix)
			}
			e := p.Entries[i]
			hit = &e
		}
	}
	if hit == nil {
		return "", nil, fmt.Errorf("archive member ending with %s not found", suffix)
	}
	b, err := p.Read(*hit)
	return hit.Name, b, err
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func sortedKeys[T any](m map[string]T) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
