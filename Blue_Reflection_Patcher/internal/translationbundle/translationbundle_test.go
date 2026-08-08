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
