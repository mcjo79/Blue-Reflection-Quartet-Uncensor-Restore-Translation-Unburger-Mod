package br1rebuild

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	quartetMarkerArchiveRelative = "Data/PACK00_04_01.PAK"
	quartetMarkerMember          = `\data\b4\x64\res_en\ui\b0_title.g1t`
	quartetMarkerTextureIndex    = 2
	quartetMarkerTextureType     = 0x5f
	quartetMarkerTextureBytes    = 0x2af80
	quartetMarkerWidth           = 1760
	quartetMarkerHeight          = 100
	quartetMarkerPlatformWindows = 0x0a
)

type QuartetTitleMarkerAudit struct {
	ArchiveRelativePath string `json:"archive_relative_path"`
	MemberPath          string `json:"member_path"`
	Label               string `json:"label"`
	TextureWidth        int    `json:"texture_width"`
	TextureHeight       int    `json:"texture_height"`
	PatchedBlocks       int    `json:"patched_blocks"`
	MemberSHA256        string `json:"member_sha256"`
	EntriesChecked      int    `json:"entries_checked"`
	OutputPath          string `json:"output_path"`
}

type markerRGBA struct{ r, g, b, a uint8 }

var quartetMarkerFont = map[rune][7]string{
	' ': {"00000", "00000", "00000", "00000", "00000", "00000", "00000"},
	'/': {"00001", "00010", "00100", "01000", "10000", "00000", "00000"},
	'.': {"00000", "00000", "00000", "00000", "00000", "00110", "00110"},
	'(': {"00010", "00100", "01000", "01000", "01000", "00100", "00010"},
	')': {"01000", "00100", "00010", "00010", "00010", "00100", "01000"},
	'0': {"01110", "10001", "10011", "10101", "11001", "10001", "01110"},
	'1': {"00100", "01100", "00100", "00100", "00100", "00100", "01110"},
	'2': {"01110", "10001", "00001", "00010", "00100", "01000", "11111"},
	'3': {"11110", "00001", "00001", "01110", "00001", "00001", "11110"},
	'4': {"00010", "00110", "01010", "10010", "11111", "00010", "00010"},
	'5': {"11111", "10000", "10000", "11110", "00001", "00001", "11110"},
	'6': {"01110", "10000", "10000", "11110", "10001", "10001", "01110"},
	'7': {"11111", "00001", "00010", "00100", "01000", "01000", "01000"},
	'8': {"01110", "10001", "10001", "01110", "10001", "10001", "01110"},
	'9': {"01110", "10001", "10001", "01111", "00001", "00001", "01110"},
	'v': {"00000", "00000", "10001", "10001", "10001", "01010", "00100"},
	'A': {"01110", "10001", "10001", "11111", "10001", "10001", "10001"},
	'B': {"11110", "10001", "10001", "11110", "10001", "10001", "11110"},
	'C': {"01111", "10000", "10000", "10000", "10000", "10000", "01111"},
	'D': {"11110", "10001", "10001", "10001", "10001", "10001", "11110"},
	'E': {"11111", "10000", "10000", "11110", "10000", "10000", "11111"},
	'G': {"01111", "10000", "10000", "10111", "10001", "10001", "01111"},
	'L': {"10000", "10000", "10000", "10000", "10000", "10000", "11111"},
	'M': {"10001", "11011", "10101", "10101", "10001", "10001", "10001"},
	'N': {"10001", "11001", "10101", "10011", "10001", "10001", "10001"},
	'O': {"01110", "10001", "10001", "10001", "10001", "10001", "01110"},
	'R': {"11110", "10001", "10001", "11110", "10100", "10010", "10001"},
	'S': {"01111", "10000", "10000", "01110", "00001", "00001", "11110"},
	'U': {"10001", "10001", "10001", "10001", "10001", "10001", "01110"},
}

func ApplyQuartetTitleMarker(workDir, sourceArchive, label string, progress BuildProgressFunc) (QuartetTitleMarkerAudit, string, error) {
	label = strings.TrimSpace(label)
	if label == "" {
		return QuartetTitleMarkerAudit{}, "", fmt.Errorf("Quartet title marker label is empty")
	}
	for _, char := range label {
		if _, ok := quartetMarkerFont[char]; !ok {
			return QuartetTitleMarkerAudit{}, "", fmt.Errorf("Quartet title marker has unsupported character %q", char)
		}
	}
	reader, err := OpenA22(sourceArchive)
	if err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	entry, ok := reader.Find(quartetMarkerMember)
	if !ok {
		reader.Close()
		return QuartetTitleMarkerAudit{}, "", fmt.Errorf("Quartet title marker member is missing: %s", quartetMarkerMember)
	}
	original, err := reader.Read(entry)
	reader.Close()
	if err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	patched, patchedBlocks, err := patchQuartetMarkerG1T(original, label)
	if err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	output := filepath.Join(workDir, "quartet-title-marker.PAK")
	progressFn := byteProgress(nil)
	if progress != nil {
		progressFn = func(phase, name string, done, total int64) {
			progress(BuildProgress{Phase: "title_marker_" + phase, CurrentFile: quartetMarkerArchiveRelative + ": " + name, CurrentDone: done, CurrentTotal: total})
		}
	}
	input := MemoryEntry{Data: patched}
	if _, err := RewriteA22(sourceArchive, output, ArchiveEdits{Replacements: map[string]ArchiveInput{quartetMarkerMember: input}}, progressFn); err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	checked, err := auditQuartetMarkerRewrite(sourceArchive, output, patched)
	if err != nil {
		return QuartetTitleMarkerAudit{}, "", err
	}
	sum := sha256.Sum256(patched)
	return QuartetTitleMarkerAudit{
		ArchiveRelativePath: quartetMarkerArchiveRelative,
		MemberPath:          quartetMarkerMember,
		Label:               label,
		TextureWidth:        quartetMarkerWidth,
		TextureHeight:       quartetMarkerHeight,
		PatchedBlocks:       patchedBlocks,
		MemberSHA256:        hex.EncodeToString(sum[:]),
		EntriesChecked:      checked,
		OutputPath:          output,
	}, output, nil
}

type quartetG1TTexture struct {
	EntryOffset   int
	PayloadOffset int
	PayloadBytes  int
	Type          byte
	Mipmaps       int
	Width         int
	Height        int
	ExtendedBytes int
}

func locateQuartetMarkerTexture(g1t []byte) (quartetG1TTexture, error) {
	// G1T is little-endian for the Windows Quartet resource. The table offset
	// reported by gust_g1t is the start of g1t_tex_header, not the DDS payload.
	// Texture 002 is non-power-of-two and therefore carries 20 bytes of local
	// extended data between its 8-byte texture header and the BC7 payload.
	if len(g1t) < 52 || string(g1t[:4]) != "GT1G" {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title marker member is not a supported G1T")
	}
	total := int(binary.LittleEndian.Uint32(g1t[8:12]))
	headerSize := int(binary.LittleEndian.Uint32(g1t[12:16]))
	textureCount := int(binary.LittleEndian.Uint32(g1t[16:20]))
	platform := int(binary.LittleEndian.Uint32(g1t[20:24]))
	if total != len(g1t) {
		return quartetG1TTexture{}, fmt.Errorf("Quartet b0_title.g1t total-size mismatch: header=%d actual=%d", total, len(g1t))
	}
	if platform != quartetMarkerPlatformWindows {
		return quartetG1TTexture{}, fmt.Errorf("Quartet b0_title.g1t has unsupported platform 0x%x", platform)
	}
	if textureCount != 3 || quartetMarkerTextureIndex >= textureCount {
		return quartetG1TTexture{}, fmt.Errorf("Quartet b0_title.g1t has unsupported texture count: %d", textureCount)
	}
	// gust_g1t defines header_size as sizeof(g1t_header)+global_flags bytes.
	// The offset table itself starts at header_size and stores offsets relative
	// to that same base.
	if headerSize != 28+textureCount*4 || headerSize+textureCount*4 > len(g1t) {
		return quartetG1TTexture{}, fmt.Errorf("Quartet b0_title.g1t has unsupported header layout")
	}
	offsetAt := headerSize + quartetMarkerTextureIndex*4
	entryOffset := headerSize + int(binary.LittleEndian.Uint32(g1t[offsetAt:offsetAt+4]))
	entryEnd := len(g1t)
	if quartetMarkerTextureIndex+1 < textureCount {
		nextAt := headerSize + (quartetMarkerTextureIndex+1)*4
		entryEnd = headerSize + int(binary.LittleEndian.Uint32(g1t[nextAt:nextAt+4]))
	}
	if entryOffset < headerSize+textureCount*4 || entryOffset+8 > entryEnd || entryEnd > len(g1t) {
		return quartetG1TTexture{}, fmt.Errorf("Quartet b0_title.g1t texture 002 range is invalid")
	}
	typeByte := g1t[entryOffset+1]
	if typeByte != quartetMarkerTextureType {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 has unsupported type 0x%02x", typeByte)
	}
	// On little-endian G1T, mipmaps occupies the high nibble in the stored
	// first byte after gust_g1t's nibble conversion.
	mipmaps := int(g1t[entryOffset] >> 4)
	if mipmaps != 1 {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 has unsupported mipmap count: %d", mipmaps)
	}
	extendedOffset := entryOffset + 8
	if extendedOffset+4 > entryEnd {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 is missing extended data")
	}
	extendedBytes := int(binary.LittleEndian.Uint32(g1t[extendedOffset : extendedOffset+4]))
	if extendedBytes != 20 || extendedOffset+extendedBytes > entryEnd {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 has unsupported extended-data size: %d", extendedBytes)
	}
	width := int(binary.LittleEndian.Uint32(g1t[extendedOffset+12 : extendedOffset+16]))
	height := int(binary.LittleEndian.Uint32(g1t[extendedOffset+16 : extendedOffset+20]))
	if width != quartetMarkerWidth || height != quartetMarkerHeight {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 dimensions are %dx%d, expected %dx%d", width, height, quartetMarkerWidth, quartetMarkerHeight)
	}
	payloadOffset := extendedOffset + extendedBytes
	payloadBytes := entryEnd - payloadOffset
	if payloadBytes != quartetMarkerTextureBytes {
		return quartetG1TTexture{}, fmt.Errorf("Quartet title texture 002 BC7 payload is %d bytes, expected %d", payloadBytes, quartetMarkerTextureBytes)
	}
	return quartetG1TTexture{
		EntryOffset: entryOffset, PayloadOffset: payloadOffset, PayloadBytes: payloadBytes,
		Type: typeByte, Mipmaps: mipmaps, Width: width, Height: height, ExtendedBytes: extendedBytes,
	}, nil
}

func patchQuartetMarkerG1T(original []byte, label string) ([]byte, int, error) {
	textureInfo, err := locateQuartetMarkerTexture(original)
	if err != nil {
		return nil, 0, err
	}
	pixels, err := renderQuartetMarker(label)
	if err != nil {
		return nil, 0, err
	}
	texture, err := encodeQuartetMarkerBC7(pixels)
	if err != nil {
		return nil, 0, err
	}
	if len(texture) != textureInfo.PayloadBytes {
		return nil, 0, fmt.Errorf("Quartet title marker encoded payload size mismatch: %d", len(texture))
	}
	patched := append([]byte(nil), original...)
	start := textureInfo.PayloadOffset
	end := start + textureInfo.PayloadBytes
	copy(patched[start:end], texture)
	if !bytes.Equal(original[:start], patched[:start]) || !bytes.Equal(original[end:], patched[end:]) {
		return nil, 0, fmt.Errorf("Quartet title marker changed bytes outside texture 002 BC7 payload")
	}
	if bytes.Equal(original[start:end], patched[start:end]) {
		return nil, 0, fmt.Errorf("Quartet title marker produced no texture change")
	}
	// The runtime-approved production profile replaces every BC7 block in
	// texture 002: transparent background plus the project marker. This removes
	// the original KOEI/legal footer without touching texture headers, extended
	// dimensions, textures 000/001, or any other G1T bytes.
	return patched, quartetMarkerTextureBytes / 16, nil
}

func encodeQuartetMarkerBC7(pixels []markerRGBA) ([]byte, error) {
	if len(pixels) != quartetMarkerWidth*quartetMarkerHeight {
		return nil, fmt.Errorf("Quartet title marker RGBA size mismatch")
	}
	if quartetMarkerWidth%4 != 0 || quartetMarkerHeight%4 != 0 {
		return nil, fmt.Errorf("Quartet title marker dimensions are not BC7 block aligned")
	}
	output := make([]byte, 0, quartetMarkerTextureBytes)
	for by := 0; by < quartetMarkerHeight; by += 4 {
		for bx := 0; bx < quartetMarkerWidth; bx += 4 {
			var block [16]markerRGBA
			index := 0
			for dy := 0; dy < 4; dy++ {
				for dx := 0; dx < 4; dx++ {
					block[index] = pixels[(by+dy)*quartetMarkerWidth+bx+dx]
					index++
				}
			}
			encoded, err := encodeBC7Mode5(block)
			if err != nil {
				return nil, err
			}
			output = append(output, encoded[:]...)
		}
	}
	if len(output) != quartetMarkerTextureBytes {
		return nil, fmt.Errorf("Quartet title marker BC7 traversal size mismatch: %d", len(output))
	}
	return output, nil
}

func auditQuartetMarkerRewrite(sourceArchive, outputArchive string, expectedMember []byte) (int, error) {
	source, err := OpenA22(sourceArchive)
	if err != nil {
		return 0, err
	}
	defer source.Close()
	output, err := OpenA22(outputArchive)
	if err != nil {
		return 0, err
	}
	defer output.Close()
	if len(source.Entries) != len(output.Entries) {
		return 0, fmt.Errorf("Quartet title marker changed archive entry count")
	}
	byName := map[string]ArchiveEntry{}
	for _, entry := range output.Entries {
		byName[strings.ToLower(entry.Name)] = entry
	}
	for _, before := range source.Entries {
		after, ok := byName[strings.ToLower(before.Name)]
		if !ok {
			return 0, fmt.Errorf("Quartet title marker lost archive entry: %s", before.Name)
		}
		if before.Size != after.Size || before.Offset != after.Offset || before.Flags != after.Flags || before.Extra != after.Extra || before.Encoded != after.Encoded || !bytes.Equal(before.Key, after.Key) {
			return 0, fmt.Errorf("Quartet title marker changed archive metadata for %s", before.Name)
		}
	}
	entry, ok := output.Find(quartetMarkerMember)
	if !ok {
		return 0, fmt.Errorf("Quartet title marker output member is missing")
	}
	actual, err := output.Read(entry)
	if err != nil {
		return 0, err
	}
	if !bytes.Equal(actual, expectedMember) {
		return 0, fmt.Errorf("Quartet title marker output member verification failed")
	}
	return len(source.Entries), nil
}

func renderQuartetMarker(label string) ([]markerRGBA, error) {
	pixels := make([]markerRGBA, quartetMarkerWidth*quartetMarkerHeight)
	const (
		rectX       = 320
		rectY       = 55
		rectWidth   = 1120
		rectHeight  = 24
		scaleX      = 2
		scaleY      = 3
		letterSpace = 1
	)
	glyphCount := len([]rune(label))
	glyphColumns := 5*glyphCount + letterSpace*maxIntLocal(0, glyphCount-1)
	textWidth := glyphColumns * scaleX
	textHeight := 7 * scaleY
	if textWidth > rectWidth-24 || textHeight > rectHeight-2 {
		return nil, fmt.Errorf("Quartet title marker does not fit approved title rectangle: %s", label)
	}
	startX := rectX + (rectWidth-textWidth)/2
	startY := rectY + (rectHeight-textHeight)/2
	mask := make([]bool, len(pixels))
	cursor := startX
	advance := (5 + letterSpace) * scaleX
	for _, char := range label {
		glyph := quartetMarkerFont[char]
		for row, bits := range glyph {
			for column, bit := range bits {
				if bit != '1' {
					continue
				}
				for dy := 0; dy < scaleY; dy++ {
					for dx := 0; dx < scaleX; dx++ {
						x := cursor + column*scaleX + dx
						y := startY + row*scaleY + dy
						if x >= 0 && y >= 0 && x < quartetMarkerWidth && y < quartetMarkerHeight {
							mask[y*quartetMarkerWidth+x] = true
						}
					}
				}
			}
		}
		cursor += advance
	}
	shadow := markerRGBA{20, 50, 90, 80}
	white := markerRGBA{255, 255, 255, 255}
	for y := 0; y < quartetMarkerHeight; y++ {
		for x := 0; x < quartetMarkerWidth; x++ {
			if !mask[y*quartetMarkerWidth+x] {
				continue
			}
			if x+1 < quartetMarkerWidth {
				blendMarkerPixel(&pixels[y*quartetMarkerWidth+x+1], shadow)
			}
		}
	}
	for index, set := range mask {
		if set {
			blendMarkerPixel(&pixels[index], white)
		}
	}
	return pixels, nil
}

func blendMarkerPixel(dst *markerRGBA, src markerRGBA) {
	if src.a == 0 {
		return
	}
	da := int(dst.a)
	sa := int(src.a)
	outA := sa + (da*(255-sa)+127)/255
	if outA == 0 {
		*dst = markerRGBA{}
		return
	}
	denom := outA * 255
	blend := func(s, d uint8) uint8 {
		return uint8((int(s)*sa*255 + int(d)*da*(255-sa) + denom/2) / denom)
	}
	*dst = markerRGBA{blend(src.r, dst.r), blend(src.g, dst.g), blend(src.b, dst.b), uint8(outA)}
}

func encodeBC7Mode5(pixels [16]markerRGBA) ([16]byte, error) {
	weights := [4]int{0, 21, 43, 64}
	type rgb struct{ r, g, b int }
	unique := map[rgb]bool{}
	var colours []rgb
	for _, pixel := range pixels {
		c := rgb{int(pixel.r), int(pixel.g), int(pixel.b)}
		if !unique[c] {
			unique[c] = true
			colours = append(colours, c)
		}
	}
	sort.Slice(colours, func(i, j int) bool {
		if colours[i].r != colours[j].r {
			return colours[i].r < colours[j].r
		}
		if colours[i].g != colours[j].g {
			return colours[i].g < colours[j].g
		}
		return colours[i].b < colours[j].b
	})
	first, second := colours[0], colours[0]
	best := -1
	for i := range colours {
		for j := i + 1; j < len(colours); j++ {
			dr, dg, db := colours[i].r-colours[j].r, colours[i].g-colours[j].g, colours[i].b-colours[j].b
			distance := dr*dr + dg*dg + db*db
			if distance > best {
				best, first, second = distance, colours[i], colours[j]
			}
		}
	}
	quant := func(value int) int {
		value = (value*127 + 127) / 255
		if value < 0 {
			return 0
		}
		if value > 127 {
			return 127
		}
		return value
	}
	expand := func(value int) int { return (value << 1) | (value >> 6) }
	interp := func(a, b, weight int) int { return ((64-weight)*a + weight*b + 32) >> 6 }
	e0 := [3]int{quant(first.r), quant(first.g), quant(first.b)}
	e1 := [3]int{quant(second.r), quant(second.g), quant(second.b)}
	x0 := [3]int{expand(e0[0]), expand(e0[1]), expand(e0[2])}
	x1 := [3]int{expand(e1[0]), expand(e1[1]), expand(e1[2])}
	var palette [4][3]int
	for choice, weight := range weights {
		for channel := 0; channel < 3; channel++ {
			palette[choice][channel] = interp(x0[channel], x1[channel], weight)
		}
	}
	var colourIndex [16]int
	for i, pixel := range pixels {
		bestChoice, bestDistance := 0, int(^uint(0)>>1)
		components := [3]int{int(pixel.r), int(pixel.g), int(pixel.b)}
		for choice := 0; choice < 4; choice++ {
			distance := 0
			for channel := 0; channel < 3; channel++ {
				delta := components[channel] - palette[choice][channel]
				distance += delta * delta
			}
			if distance < bestDistance {
				bestChoice, bestDistance = choice, distance
			}
		}
		colourIndex[i] = bestChoice
	}
	if colourIndex[0] >= 2 {
		e0, e1 = e1, e0
		for i := range colourIndex {
			colourIndex[i] = 3 - colourIndex[i]
		}
	}
	alpha0, alpha1 := 255, 0
	for _, pixel := range pixels {
		if int(pixel.a) < alpha0 {
			alpha0 = int(pixel.a)
		}
		if int(pixel.a) > alpha1 {
			alpha1 = int(pixel.a)
		}
	}
	var alphaPalette [4]int
	for choice, weight := range weights {
		alphaPalette[choice] = interp(alpha0, alpha1, weight)
	}
	var alphaIndex [16]int
	for i, pixel := range pixels {
		bestChoice, bestDistance := 0, 1<<30
		for choice := 0; choice < 4; choice++ {
			delta := int(pixel.a) - alphaPalette[choice]
			if delta < 0 {
				delta = -delta
			}
			if delta < bestDistance {
				bestChoice, bestDistance = choice, delta
			}
		}
		alphaIndex[i] = bestChoice
	}
	if alphaIndex[0] >= 2 {
		alpha0, alpha1 = alpha1, alpha0
		for i := range alphaIndex {
			alphaIndex[i] = 3 - alphaIndex[i]
		}
	}
	var output [16]byte
	bitOffset := 0
	put := func(value, bits int) error {
		if value < 0 || value >= 1<<bits {
			return fmt.Errorf("BC7 value %d does not fit in %d bits", value, bits)
		}
		for bit := 0; bit < bits; bit++ {
			if value&(1<<bit) != 0 {
				output[bitOffset/8] |= 1 << (bitOffset % 8)
			}
			bitOffset++
		}
		return nil
	}
	if err := put(1<<5, 6); err != nil {
		return output, err
	}
	if err := put(0, 2); err != nil {
		return output, err
	}
	for channel := 0; channel < 3; channel++ {
		if err := put(e0[channel], 7); err != nil {
			return output, err
		}
		if err := put(e1[channel], 7); err != nil {
			return output, err
		}
	}
	if err := put(alpha0, 8); err != nil {
		return output, err
	}
	if err := put(alpha1, 8); err != nil {
		return output, err
	}
	for i, selector := range colourIndex {
		bits := 2
		if i == 0 {
			bits = 1
		}
		if err := put(selector, bits); err != nil {
			return output, err
		}
	}
	for i, selector := range alphaIndex {
		bits := 2
		if i == 0 {
			bits = 1
		}
		if err := put(selector, bits); err != nil {
			return output, err
		}
	}
	if bitOffset != 128 {
		return output, fmt.Errorf("BC7 mode 5 used %d bits", bitOffset)
	}
	return output, nil
}

func maxIntLocal(a, b int) int {
	if a > b {
		return a
	}
	return b
}
