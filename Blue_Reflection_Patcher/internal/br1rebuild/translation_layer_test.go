package br1rebuild

import (
	"bytes"
	"testing"
)

func TestMergeTranslatedStringRowsPreservesSourceAddedRows(t *testing.T) {
	template := []byte("<root>\r\n<str String_No=\"1\" Text=\"Stock\"/>\r\n<str String_No=\"2\" Text=\"Keep\"/>\r\n</root>\r\n")
	translated := []byte("<root>\r\n<str String_No=\"1\" Text=\"Translated\"/>\r\n<str String_No=\"2\" Text=\"Keep\"/>\r\n</root>\r\n")
	base := []byte("<root>\r\n<str String_No=\"1\" Text=\"Stock\"/>\r\n<str String_No=\"2\" Text=\"Keep\"/>\r\n<str String_No=\"99\" Text=\"Reconstructed\"/>\r\n</root>\r\n")
	got, changed, err := mergeTranslatedStringRows(base, template, translated)
	if err != nil {
		t.Fatal(err)
	}
	if changed != 1 {
		t.Fatalf("changed=%d", changed)
	}
	for _, want := range [][]byte{[]byte(`String_No="1" Text="Translated"`), []byte(`String_No="99" Text="Reconstructed"`)} {
		if !bytes.Contains(got, want) {
			t.Fatalf("missing %s in %s", want, got)
		}
	}
}

func TestMergeTranslatedStringRowsCanAppendTargetExtension(t *testing.T) {
	template := []byte("<root>\n<str String_No=\"1\" Text=\"Stock\"/>\n</root>\n")
	translated := []byte("<root>\n<str String_No=\"1\" Text=\"Stock\"/>\n<str String_No=\"5\" Text=\"Extension\"/>\n</root>\n")
	base := []byte("<root>\n<str String_No=\"1\" Text=\"Stock\"/>\n</root>\n")
	got, changed, err := mergeTranslatedStringRows(base, template, translated)
	if err != nil {
		t.Fatal(err)
	}
	if changed != 1 || !bytes.Contains(got, []byte(`String_No="5" Text="Extension"`)) {
		t.Fatalf("unexpected merge: changed=%d %s", changed, got)
	}
}
