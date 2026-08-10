package quartetdlc

import (
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"testing"
)

func TestSecondLightEBMRestoresOnlyBlankTextAndPreservesMetadata(t *testing.T) {
	makeDoc := func(text string) []byte {
		d := &secondLightEBMFile{
			MessageCount: 1, Duration1Words: 2, Duration2Words: 1, Trailer: []byte{0xaa, 0xbb},
			Messages: []secondLightEBMMessage{{
				Type: 3, VoiceID: 22, Unknown1: 33, NameID: 44, ExtraID: 55, ExprID: 66,
				Duration1: []uint32{77, 88}, MessageID: 99, Unknown2: 111, Text: []byte(text), Duration2: []uint32{123},
			}},
		}
		b, err := buildSecondLightEBM(d)
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	target := makeDoc("-")
	source := makeDoc("Restored text")
	got, n, err := restoreSecondLightEBMText(target, source)
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("changed=%d, want 1", n)
	}
	td, err := parseSecondLightEBM(got)
	if err != nil {
		t.Fatal(err)
	}
	if string(td.Messages[0].Text) != "Restored text" {
		t.Fatalf("text=%q", td.Messages[0].Text)
	}
	before, _ := parseSecondLightEBM(target)
	if !secondLightEBMHeaderEqual(before.Messages[0], td.Messages[0]) || !bytes.Equal(before.Trailer, td.Trailer) {
		t.Fatal("non-text EBM metadata changed")
	}
}

func TestSecondLightStringRestoreOnlyTouchesBlankTarget(t *testing.T) {
	target := []byte(`<root><str String_ID="A" String_No="0" Text="-"/><str String_ID="B" String_No="1" Text="Quartet"/></root>`)
	source := []byte(`<root><str String_ID="A" String_No="0" Text="DLC"/><str String_ID="B" String_No="1" Text="Source"/></root>`)
	got, n, err := restoreBlankSecondLightStrings(target, source)
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("changed=%d, want 1", n)
	}
	want := `<root><str String_ID="A" String_No="0" Text="DLC"/><str String_ID="B" String_No="1" Text="Quartet"/></root>`
	if string(got) != want {
		t.Fatalf("got %s", got)
	}
}

func TestSecondLightCostumePatchUsesSourcePointersButKeepsTargetNativeFields(t *testing.T) {
	targetChara := []byte(`<root><CharaBase BaseTag="PC000_ACC" Model="school/a" FileHead="school" defaultTexture="school" wetCharaBaseTag="PC000_WET" FMhig="quartet" swingMS="quartet"/></root>`)
	sourceChara := []byte(`<root><CharaBase BaseTag="PC000_ACC" Model="dlc_hat/a" FileHead="dlc_hat" defaultTexture="dlc_hat" wetCharaBaseTag="PC000_WET" FMhig="source" swingMS="source"/></root>`)
	targetCostume := []byte(`<root><elem id="COSTUME_BODY_ACC_HEAD_PC000_3" model_body="MODEL_HAT" cond_00="COSTUME_OPEN_COND_NEVER"/></root>`)
	sourceCostume := []byte(`<root><elem id="COSTUME_BODY_ACC_HEAD_PC000_3" model_body="MODEL_HAT" cond_00="COSTUME_OPEN_COND_DLC" cond_prm_00="DLC_X"/></root>`)
	targetModels := []byte(`<root><elem id="MODEL_HAT" chara_base="CHARA_BASE_PC000_ACC"/></root>`)
	gotChara, gotCostume, audit, err := patchSecondLightCostumeTables(targetChara, sourceChara, targetCostume, sourceCostume, targetModels,
		map[string]bool{"dlc_hat": true}, map[string]bool{"school": true})
	if err != nil {
		t.Fatal(err)
	}
	if audit.RepointedRows != 1 || audit.OpenedRows != 1 {
		t.Fatalf("audit=%+v", audit)
	}
	if !bytes.Contains(gotChara, []byte(`Model="dlc_hat/a"`)) || !bytes.Contains(gotChara, []byte(`FileHead="dlc_hat"`)) {
		t.Fatalf("pointers not restored: %s", gotChara)
	}
	if !bytes.Contains(gotChara, []byte(`FMhig="quartet"`)) || !bytes.Contains(gotChara, []byte(`swingMS="quartet"`)) {
		t.Fatalf("target-native tuning lost: %s", gotChara)
	}
	if bytes.Contains(gotChara, []byte(`FMhig="source"`)) {
		t.Fatal("source tuning leaked into target")
	}
	if !bytes.Contains(gotCostume, []byte(`cond_00="COSTUME_OPEN_COND_DEFAULT"`)) || bytes.Contains(gotCostume, []byte(`cond_prm_00=`)) {
		t.Fatalf("wrong gate patch: %s", gotCostume)
	}
}

func TestSecondLightScenarioRegatingUsesStoryFlagsAndPreservesInertGate(t *testing.T) {
	input := []byte(`<root>` +
		`<Elem launch_param="EVENT_XF04_010" on_condition_1="1180" off_condition_1="999" launch_type="1"/>` +
		`<Elem launch_param="EVENT_SD00_430" on_condition_1="1226" off_condition_1="998" launch_type="1"/>` +
		`<Elem launch_param="MAP_SAFE" on_condition_1="1181" on_condition_2="110" off_condition_1="1" launch_type="1"/>` +
		`<Elem launch_param="LINKSKETCH_DLC_000" on_condition_1="1181" off_condition_1="1" launch_type="1"/>` +
		`</root>`)
	got, n, err := regateSecondLightScenario(input)
	if err != nil {
		t.Fatal(err)
	}
	if n != 3 {
		t.Fatalf("changed=%d, want 3", n)
	}
	if !bytes.Contains(got, []byte(`EVENT_XF04_010" on_condition_1="2660"`)) {
		t.Fatalf("XF04 not regated: %s", got)
	}
	if !bytes.Contains(got, []byte(`EVENT_SD00_430" on_condition_1="102"`)) {
		t.Fatalf("SD00 not regated: %s", got)
	}
	if bytes.Count(got, []byte(`"1181"`)) != 1 {
		t.Fatalf("surviving 1181 count=%d", bytes.Count(got, []byte(`"1181"`)))
	}
}

func TestSecondLightFacilityPlotIsNarrow(t *testing.T) {
	in := []byte(`<root><elem id="OTHER" size="-1"/><elem id="SD_PLACE_04_18" size="-1" foo="x"/></root>`)
	got, changed, err := enableSecondLightFacilityPlot(in)
	if err != nil {
		t.Fatal(err)
	}
	if !changed || string(got) != `<root><elem id="OTHER" size="-1"/><elem id="SD_PLACE_04_18" size="4" foo="x"/></root>` {
		t.Fatalf("got %s", got)
	}
}

func TestSecondLightBlowfishMatchesPublishedZeroVector(t *testing.T) {
	bf, err := newSecondLightBlowfish(make([]byte, 8))
	if err != nil {
		t.Fatal(err)
	}
	got := bf.transform(make([]byte, 8), true)
	want, _ := hex.DecodeString("4ef997456198dd78")
	if !bytes.Equal(got, want) {
		t.Fatalf("cipher=%x want=%x", got, want)
	}
	if plain := bf.transform(got, false); !bytes.Equal(plain, make([]byte, 8)) {
		t.Fatalf("decrypt=%x", plain)
	}
}

func makeSyntheticCauldronPE(t *testing.T) []byte {
	t.Helper()
	data := make([]byte, 0x1000)
	copy(data[:2], "MZ")
	binary.LittleEndian.PutUint32(data[0x3c:], 0x80)
	copy(data[0x80:], "PE\x00\x00")
	coff := 0x84
	binary.LittleEndian.PutUint16(data[coff:], 0x8664)
	binary.LittleEndian.PutUint16(data[coff+2:], 2)
	binary.LittleEndian.PutUint16(data[coff+16:], 0xf0)
	opt := coff + 20
	binary.LittleEndian.PutUint16(data[opt:], 0x20b)
	imageBase := uint64(0x180000000)
	binary.LittleEndian.PutUint64(data[opt+0x18:], imageBase)
	sec := opt + 0xf0
	// .rdata at file 0x400, RVA 0x2000.
	copy(data[sec:sec+8], []byte(".rdata\x00\x00"))
	binary.LittleEndian.PutUint32(data[sec+8:], 0x200)
	binary.LittleEndian.PutUint32(data[sec+12:], 0x2000)
	binary.LittleEndian.PutUint32(data[sec+16:], 0x200)
	binary.LittleEndian.PutUint32(data[sec+20:], 0x400)
	// .data at file 0x800, RVA 0x3000.
	sec += 40
	copy(data[sec:sec+8], []byte(".data\x00\x00\x00"))
	binary.LittleEndian.PutUint32(data[sec+8:], 0x100)
	binary.LittleEndian.PutUint32(data[sec+12:], 0x3000)
	binary.LittleEndian.PutUint32(data[sec+16:], 0x100)
	binary.LittleEndian.PutUint32(data[sec+20:], 0x800)
	badOff, goodOff := 0x420, 0x460
	copy(data[badOff:], append([]byte(secondLightCauldronBadPath), 0))
	copy(data[goodOff:], append([]byte(secondLightCauldronGoodPath), 0))
	badVA := imageBase + 0x2000 + uint64(badOff-0x400)
	goodVA := imageBase + 0x2000 + uint64(goodOff-0x400)
	// Real Quartet has one legitimate pointer to the B4/ path immediately before
	// the miswired constructor slot. The fix makes the adjacent pair agree.
	binary.LittleEndian.PutUint64(data[0x818:], goodVA)
	binary.LittleEndian.PutUint64(data[0x820:], badVA)
	return data
}

func TestSecondLightCauldronFixChangesOnePointerByteAndIsIdempotent(t *testing.T) {
	in := makeSyntheticCauldronPE(t)
	got, changed, err := fixSecondLightCauldronPointer(in)
	if err != nil {
		t.Fatal(err)
	}
	if !changed {
		t.Fatal("expected change")
	}
	if n := countByteDiff(in, got); n != 1 {
		t.Fatalf("diff bytes=%d", n)
	}
	again, changed, err := fixSecondLightCauldronPointer(got)
	if err != nil {
		t.Fatal(err)
	}
	if changed || !bytes.Equal(got, again) {
		t.Fatal("already-patched image should be accepted unchanged")
	}
}

func TestRestoreSecondLightEBMRemovesDashWhenStandaloneIsEmpty(t *testing.T) {
	targetDoc := secondLightEBMFile{MessageCount: 1, Duration1Words: 0, Duration2Words: 0, Messages: []secondLightEBMMessage{{Type: 1, NameID: 2, VoiceID: 3, Text: []byte("-")}}}
	sourceDoc := secondLightEBMFile{MessageCount: 1, Duration1Words: 0, Duration2Words: 0, Messages: []secondLightEBMMessage{{Type: 1, NameID: 2, VoiceID: 3, Text: []byte("")}}}
	target, err := buildSecondLightEBM(&targetDoc)
	if err != nil {
		t.Fatal(err)
	}
	source, err := buildSecondLightEBM(&sourceDoc)
	if err != nil {
		t.Fatal(err)
	}
	patched, changed, err := restoreSecondLightEBMText(target, source)
	if err != nil {
		t.Fatal(err)
	}
	if changed != 1 {
		t.Fatalf("changed=%d, want 1", changed)
	}
	doc, err := parseSecondLightEBM(patched)
	if err != nil {
		t.Fatal(err)
	}
	if len(doc.Messages) != 1 || len(doc.Messages[0].Text) != 0 {
		t.Fatalf("restored text=%q, want empty standalone value", doc.Messages[0].Text)
	}
}

func TestSecondLightStringRestorePreservesSourceWhitespaceValue(t *testing.T) {
	target := []byte(`<root><str String_ID="STR_MENU_DEFINE_261" String_No="0" Text=""/></root>`)
	source := []byte(`<root><str String_ID="STR_MENU_DEFINE_261" String_No="0" Text=" "/></root>`)
	got, n, err := restoreBlankSecondLightStrings(target, source)
	if err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("changed=%d, want 1", n)
	}
	if !bytes.Contains(got, []byte(`Text=" "`)) {
		t.Fatalf("whitespace source value was not restored: %s", got)
	}
}

func TestSecondLightCostumePatchReclosesRowsOpenedWithoutAnyModelFolder(t *testing.T) {
	targetChara := []byte(`<root><CharaBase BaseTag="PC000_J" Model="quartet_j/body"/><CharaBase BaseTag="PC000_R" Model="quartet_r/body"/></root>`)
	sourceChara := []byte(`<root><CharaBase BaseTag="PC000_J" Model="pc000_luna_scl/body"/><CharaBase BaseTag="PC000_R" Model="pc000_ryza/body"/></root>`)
	targetCostume := []byte(`<root>` +
		`<elem id="COSTUME_BODY_PC000J" model_body="MODEL_J" cond_00="COSTUME_OPEN_COND_NEVER"/>` +
		`<elem id="COSTUME_BODY_PC000R" model_body="MODEL_R" cond_00="COSTUME_OPEN_COND_NEVER"/>` +
		`</root>`)
	sourceCostume := []byte(`<root>` +
		`<elem id="COSTUME_BODY_PC000J" model_body="MODEL_J" cond_00="COSTUME_OPEN_COND_DLC"/>` +
		`<elem id="COSTUME_BODY_PC000R" model_body="MODEL_R" cond_00="COSTUME_OPEN_COND_DLC"/>` +
		`</root>`)
	targetModels := []byte(`<root><elem id="MODEL_J" chara_base="CHARA_BASE_PC000_J"/><elem id="MODEL_R" chara_base="CHARA_BASE_PC000_R"/></root>`)

	_, got, audit, err := patchSecondLightCostumeTables(
		targetChara, sourceChara, targetCostume, sourceCostume, targetModels,
		map[string]bool{}, map[string]bool{"quartet_j": true, "quartet_r": true},
	)
	if err != nil {
		t.Fatal(err)
	}
	if audit.OpenedRows != 2 || audit.ReclosedRows != 2 {
		t.Fatalf("audit=%+v", audit)
	}
	if bytes.Count(got, []byte(`cond_00="COSTUME_OPEN_COND_NEVER"`)) != 2 {
		t.Fatalf("dangling model rows remained reachable: %s", got)
	}
	if bytes.Contains(got, []byte(`cond_00="COSTUME_OPEN_COND_DEFAULT"`)) {
		t.Fatalf("DEFAULT row with absent model survived: %s", got)
	}
}

func TestSecondLightBuildAuditReadyRequiresFullClosure(t *testing.T) {
	a := SecondLightBuildAudit{Capability: SecondLightDLCFamilyCapability, OutputSHA256: map[string]string{"x": "y"}, OutputBytes: map[string]int64{"x": 1}, DialogueMessages: 1}
	if a.Ready() {
		t.Fatal("partial Second Light restoration must not be ready")
	}
	a = SecondLightBuildAudit{
		Capability:      SecondLightDLCFamilyCapability,
		DialogueMembers: 466, DialogueMessages: 7217, UIStringMembers: 105, UIStrings: 2536,
		MapMembersAdded: 41, ModelMembersAdded: 264, CostumeRepointedRows: 106, CostumeOpenedRows: 78, CostumeReclosedRows: 2,
		ScenarioRowsRegated: 15, FacilityPlotChanged: true, ResonanceRowsRestored: 10, ResonancePanelsRegated: 4,
		StreamRoutesChanged: 6, StubSoundsRemoved: 6, AudioSectionsConverted: 12, AudioStreamsEncrypted: 6,
		CauldronPointerChanged: true, OutputSHA256: map[string]string{}, OutputBytes: map[string]int64{},
	}
	for _, rel := range []string{"Data/PACK00_02.PAK", "Data/PACK00_03.PAK", "Data/PACK01_03.PAK", "Data/PACK02_03.PAK", "Data/B4/x64/Sound/Legacy_BGM.ktsl2asbin", "Data/B4/x64/Sound/Legacy_BGM.ktsl2stbin", "Data/B4/x64/Sound/Seed_BGM.ktsl2asbin", "B4.dll"} {
		a.OutputSHA256[rel] = "digest"
		a.OutputBytes[rel] = 1
	}
	if !a.Ready() {
		t.Fatalf("complete closure should be ready: %+v", a)
	}
	a.CostumeReclosedRows = 0
	if a.Ready() {
		t.Fatal("missing-model costume closure must be required")
	}
}
