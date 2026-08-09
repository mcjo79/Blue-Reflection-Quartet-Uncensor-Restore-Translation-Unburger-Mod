package translationbundle

import (
	"encoding/binary"
	"testing"
)

func ebmFixture(texts []string, ids []uint32, d1, d2 int) []byte {
	buf := make([]byte, 4)
	binary.LittleEndian.PutUint32(buf, uint32(len(texts)))
	appendU32 := func(v uint32) { var b [4]byte; binary.LittleEndian.PutUint32(b[:], v); buf = append(buf, b[:]...) }
	for i, text := range texts {
		appendU32(2)
		appendU32(uint32(i + 1))
		appendU32(0)
		appendU32(uint32(i + 10))
		appendU32(0)
		appendU32(uint32(i + 20))
		for j := 0; j < d1; j++ {
			appendU32(uint32(100 + i + j))
		}
		appendU32(ids[i])
		appendU32(0)
		raw := append([]byte(text), 0)
		appendU32(uint32(len(raw)))
		buf = append(buf, raw...)
		for j := 0; j < d2; j++ {
			appendU32(uint32(200 + i + j))
		}
	}
	return buf
}

func TestEBMRoundTripLayouts(t *testing.T) {
	for _, layout := range [][2]int{{0, 0}, {0, 1}, {0, 2}, {2, 0}, {2, 1}, {2, 2}} {
		data := ebmFixture([]string{"alpha", "beta"}, []uint32{10, 11}, layout[0], layout[1])
		f, err := parseEBM(data)
		if err != nil {
			t.Fatalf("layout %v: %v", layout, err)
		}
		if f.D1 != layout[0] || f.D2 != layout[1] {
			t.Fatalf("layout selected %d/%d want %v", f.D1, f.D2, layout)
		}
		out, err := serializeEBM(f)
		if err != nil {
			t.Fatal(err)
		}
		if string(out) != string(data) {
			t.Fatalf("layout %v did not round-trip byte exact", layout)
		}
	}
}

func TestApplyEBMUsesStableMessageIDAndStructuralRebase(t *testing.T) {
	data := ebmFixture([]string{"changed by game update", "keep"}, []uint32{7, 8}, 0, 0)
	msg := uint32(7)
	records := []Record{{LogicalID: "x", TargetIndex: 0, MsgID: &msg, Metadata: &EBMMetadata{Type: 2, VoiceID: 1, Unknown1: 0, NameID: 10, ExtraID: 0, ExprID: 20, MsgID: 7, Unknown2: 0}, ExpectedTextSHA256: textHash("old official"), DesiredText: "our translation"}}
	out, already, rebase, err := applyEBM(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 1 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	f, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if f.Messages[0].Text != "our translation" || f.Messages[1].Text != "keep" {
		t.Fatalf("unexpected texts: %+v", f.Messages)
	}
}

func TestApplyXMLUsesStringNoAcrossReorder(t *testing.T) {
	data := []byte("<?xml version=\"1.0\"?>\r\n<root>\r\n<str String_ID=\"B\" String_No=\"20\" Text=\"Other\"/>\r\n<str String_ID=\"A\" String_No=\"10\" Text=\"Old\"/>\r\n</root>\r\n")
	records := []Record{{LogicalID: "x", TargetIndex: 0, StringNo: "10", StringID: "A", ExpectedTextSHA256: textHash("Old"), DesiredText: "New & Better"}}
	out, already, rebase, err := applyXML(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 0 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	rows, _, err := parseXML(out)
	if err != nil {
		t.Fatal(err)
	}
	if rows[0].text != "Other" || rows[1].text != "New & Better" {
		t.Fatalf("unexpected rows: %+v", rows)
	}
}

func TestApplyXMLAllowsCompatibleTextRebaseByStableKey(t *testing.T) {
	data := []byte("<root><str String_No=\"10\" Text=\"Updated official text\"/></root>")
	records := []Record{{LogicalID: "x", TargetIndex: 0, StringNo: "10", ExpectedTextSHA256: textHash("Old official text"), DesiredText: "Translation"}}
	_, _, rebase, err := applyXML(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if rebase != 1 {
		t.Fatalf("rebase=%d", rebase)
	}
}

func TestApplyEBMDisambiguatesDuplicateMessageIDByUniqueMetadata(t *testing.T) {
	data := ebmFixture([]string{"same baseline", "same baseline", "other"}, []uint32{17588, 17588, 999}, 0, 0)
	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "second_light:event:dm03/event_message_dm03_200.ebm:source_index:44:msg_id:17588",
		TargetIndex:        2, // deliberately stale/non-matching target index
		MsgID:              &msg,
		Metadata:           &EBMMetadata{Type: 2, VoiceID: 2, Unknown1: 0, NameID: 11, ExtraID: 0, ExprID: 21, MsgID: 17588, Unknown2: 0},
		ExpectedTextSHA256: textHash("same baseline"), // deliberately ambiguous across both ID matches
		DesiredText:        "translated",
	}}
	out, already, rebase, err := applyEBM(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 0 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	f, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if f.Messages[0].Text != "same baseline" || f.Messages[1].Text != "translated" || f.Messages[2].Text != "other" {
		t.Fatalf("unexpected texts: %+v", f.Messages)
	}
}

func TestApplyEBMRejectsDuplicateMessageIDWhenMetadataIsAlsoAmbiguous(t *testing.T) {
	data := ebmFixture([]string{"same baseline", "same baseline", "other"}, []uint32{17588, 17588, 999}, 0, 0)
	f, err := parseEBM(data)
	if err != nil {
		t.Fatal(err)
	}
	// Make the two duplicate-ID records structurally identical as well.
	f.Messages[1].Type = f.Messages[0].Type
	f.Messages[1].VoiceID = f.Messages[0].VoiceID
	f.Messages[1].Unknown1 = f.Messages[0].Unknown1
	f.Messages[1].NameID = f.Messages[0].NameID
	f.Messages[1].ExtraID = f.Messages[0].ExtraID
	f.Messages[1].ExprID = f.Messages[0].ExprID
	f.Messages[1].Unknown2 = f.Messages[0].Unknown2
	data, err = serializeEBM(f)
	if err != nil {
		t.Fatal(err)
	}

	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "ambiguous",
		TargetIndex:        2,
		MsgID:              &msg,
		Metadata:           &EBMMetadata{Type: 2, VoiceID: 1, Unknown1: 0, NameID: 10, ExtraID: 0, ExprID: 20, MsgID: 17588, Unknown2: 0},
		ExpectedTextSHA256: textHash("same baseline"),
		DesiredText:        "translated",
	}}
	if _, _, _, err := applyEBM(data, records); err == nil {
		t.Fatal("expected ambiguous duplicate-ID/metadata resolution to fail closed")
	}
}

func TestApplyEBMUsesTargetIndexWhenBaselineHashConfirmsDifferentTargetMessageID(t *testing.T) {
	data := ebmFixture([]string{"decoy one", "Rena!", "decoy two"}, []uint32{17588, 90001, 17588}, 0, 0)
	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "second_light:event:dm03/event_message_dm03_200.ebm:source_index:44:msg_id:17588",
		TargetIndex:        1,
		MsgID:              &msg,
		Metadata:           &EBMMetadata{Type: 2, VoiceID: 0, Unknown1: 0, NameID: 3, ExtraID: ^uint32(0), ExprID: ^uint32(0), MsgID: 17588, Unknown2: 2},
		ExpectedTextSHA256: textHash("Rena!"),
		DesiredText:        "Rena-san!",
	}}
	out, already, rebase, err := applyEBM(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 0 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	f, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if f.Messages[0].Text != "decoy one" || f.Messages[1].Text != "Rena-san!" || f.Messages[2].Text != "decoy two" {
		t.Fatalf("unexpected texts: %+v", f.Messages)
	}
}

func TestApplyEBMUsesTargetIndexWhenDesiredTextAlreadyPresentWithDifferentTargetMessageID(t *testing.T) {
	data := ebmFixture([]string{"decoy one", "Rena-san!", "decoy two"}, []uint32{17588, 90001, 17588}, 0, 0)
	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "already",
		TargetIndex:        1,
		MsgID:              &msg,
		ExpectedTextSHA256: textHash("Rena!"),
		DesiredText:        "Rena-san!",
	}}
	out, already, rebase, err := applyEBM(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 1 || rebase != 0 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	if string(out) != string(data) {
		t.Fatal("idempotent target-index resolution changed bytes")
	}
}

func TestApplyEBMFailsClosedWhenTargetIndexAndSourceIDDoNotConfirm(t *testing.T) {
	data := ebmFixture([]string{"decoy one", "wrong target", "decoy two"}, []uint32{17588, 90001, 17588}, 0, 0)
	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "still-ambiguous",
		TargetIndex:        1,
		MsgID:              &msg,
		ExpectedTextSHA256: textHash("Rena!"),
		DesiredText:        "Rena-san!",
	}}
	if _, _, _, err := applyEBM(data, records); err == nil {
		t.Fatal("expected unresolved target/source identity to fail closed")
	}
}

func TestApplyEBMUpdatesPreviousTranslationWithoutHistoricalTextHashOrState(t *testing.T) {
	data := ebmFixture([]string{"decoy one", "previous Translation release", "decoy two"}, []uint32{17588, 90001, 17588}, 0, 0)
	f, err := parseEBM(data)
	if err != nil {
		t.Fatal(err)
	}
	// Quartet keeps the target record role/order but uses a target-native MsgID.
	// Match every stable structural field to the source identity while keeping the
	// deliberately different target MsgID and a text that is neither stock nor new.
	m := &f.Messages[1]
	m.Type = 2
	m.VoiceID = 0
	m.Unknown1 = 0
	m.NameID = 3
	m.ExtraID = ^uint32(0)
	m.ExprID = ^uint32(0)
	m.Unknown2 = 2
	data, err = serializeEBM(f)
	if err != nil {
		t.Fatal(err)
	}

	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "second_light:event:dm03/event_message_dm03_200.ebm:source_index:44:msg_id:17588",
		TargetIndex:        1,
		MsgID:              &msg,
		Metadata:           &EBMMetadata{Type: 2, VoiceID: 0, Unknown1: 0, NameID: 3, ExtraID: ^uint32(0), ExprID: ^uint32(0), MsgID: 17588, Unknown2: 2},
		ExpectedTextSHA256: textHash("Rena!"),
		DesiredText:        "new Translation release",
	}}
	out, already, rebase, err := applyEBM(data, records)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 1 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	got, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if got.Messages[1].Text != "new Translation release" {
		t.Fatalf("target text=%q", got.Messages[1].Text)
	}
	if got.Messages[0].Text != "decoy one" || got.Messages[2].Text != "decoy two" {
		t.Fatal("neighboring records changed")
	}
}

func TestApplyEBMManagedExactMemberAllowsUpgradeWhenTargetMetadataAlsoDiffers(t *testing.T) {
	data := ebmFixture([]string{"one", "previous managed translation", "three"}, []uint32{1, 90001, 2}, 0, 0)
	msg := uint32(17588)
	records := []Record{{
		LogicalID:          "managed",
		TargetIndex:        1,
		MsgID:              &msg,
		Metadata:           &EBMMetadata{Type: 77, VoiceID: 88, Unknown1: 99, NameID: 100, ExtraID: 101, ExprID: 102, MsgID: 17588, Unknown2: 103},
		ExpectedTextSHA256: textHash("stock baseline no longer present"),
		DesiredText:        "new managed translation",
	}}
	out, already, rebase, err := applyEBMManaged(data, records, true, 0)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 1 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	got, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if got.Messages[1].Text != "new managed translation" {
		t.Fatalf("target text=%q", got.Messages[1].Text)
	}
}

func TestMemberBindingFingerprintChangesWhenTargetMappingChanges(t *testing.T) {
	a := []Record{{LogicalID: "a", TargetIndex: 4}, {LogicalID: "b", TargetIndex: 9}}
	b := []Record{{LogicalID: "a", TargetIndex: 4}, {LogicalID: "b", TargetIndex: 10}}
	if memberBindingSHA(a) == memberBindingSHA(b) {
		t.Fatal("mapping change must invalidate managed binding fingerprint")
	}
	c := []Record{{LogicalID: "b", TargetIndex: 9}, {LogicalID: "a", TargetIndex: 4}}
	if memberBindingSHA(a) != memberBindingSHA(c) {
		t.Fatal("binding fingerprint must be order-independent")
	}
}

func TestEBMStructuralFingerprintIgnoresTextButDetectsStructure(t *testing.T) {
	base := ebmFixture([]string{"old one", "old two"}, []uint32{100, 200}, 0, 0)
	f, err := parseEBM(base)
	if err != nil {
		t.Fatal(err)
	}
	sha1 := ebmStructuralSHAFromFile(f)
	f.Messages[0].Text = "completely different translation with a different length"
	sha2 := ebmStructuralSHAFromFile(f)
	if sha1 != sha2 {
		t.Fatal("text-only change altered structural fingerprint")
	}
	f.Messages[0].MsgID++
	if ebmStructuralSHAFromFile(f) == sha1 {
		t.Fatal("structural MsgID change was not detected")
	}
}

func TestApplyEBMCanonicalWholeMemberBindingHandlesTargetNativeMetadata(t *testing.T) {
	data := ebmFixture([]string{"old A", "old B", "old C"}, []uint32{90001, 90002, 90003}, 0, 0)
	msg := uint32(17072)
	records := []Record{{
		LogicalID:   "second_light:event:xf04/event_message_xf04_200.ebm:source_index:11:msg_id:17072",
		TargetIndex: 1, MsgID: &msg,
		Metadata:           &EBMMetadata{Type: 77, VoiceID: 88, Unknown1: 99, NameID: 100, ExtraID: 101, ExprID: 102, MsgID: msg, Unknown2: 103},
		ExpectedTextSHA256: textHash("unavailable Quartet auxiliary"),
		DesiredText:        "new Translation",
	}}
	out, already, rebase, err := applyEBMManaged(data, records, false, 3)
	if err != nil {
		t.Fatal(err)
	}
	if already != 0 || rebase != 1 {
		t.Fatalf("already=%d rebase=%d", already, rebase)
	}
	got, err := parseEBM(out)
	if err != nil {
		t.Fatal(err)
	}
	if got.Messages[1].Text != "new Translation" || got.Messages[0].Text != "old A" || got.Messages[2].Text != "old C" {
		t.Fatal("canonical target index did not isolate the intended record")
	}
}

func TestApplyEBMCanonicalWholeMemberBindingRequiresRecordCountAndUniqueIndices(t *testing.T) {
	data := ebmFixture([]string{"A", "B", "C"}, []uint32{1, 2, 3}, 0, 0)
	msg := uint32(9999)
	r := Record{LogicalID: "x", TargetIndex: 1, MsgID: &msg, ExpectedTextSHA256: textHash("other"), DesiredText: "new"}
	if _, _, _, err := applyEBMManaged(data, []Record{r}, false, 4); err == nil {
		t.Fatal("wrong target record count trusted canonical indices")
	}
	r2 := r
	r2.LogicalID = "y"
	if _, _, _, err := applyEBMManaged(data, []Record{r, r2}, false, 3); err == nil {
		t.Fatal("duplicate target index trusted canonical indices")
	}
}
