package wardrobe

import "encoding/binary"

func EncodeRecord(r LogicalRecord) []byte {
	values := []uint32{r.LabelID, r.Character, r.Field08, r.Field0C, r.Field10, r.Field14, r.Field18, r.Field1C, r.Field20, r.Field24, r.Field28, r.Field2C}
	out := make([]byte, 0x30)
	for i, v := range values {
		binary.LittleEndian.PutUint32(out[i*4:], v)
	}
	return out
}
