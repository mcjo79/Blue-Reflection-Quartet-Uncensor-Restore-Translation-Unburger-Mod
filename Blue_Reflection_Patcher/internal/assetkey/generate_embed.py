#!/usr/bin/env python3
import secrets, sys
from pathlib import Path
if len(sys.argv) != 3:
    raise SystemExit("usage: generate_embed.py KEYFILE OUTGO")
key = Path(sys.argv[1]).read_bytes()
if len(key) != 32:
    raise SystemExit("key file must contain exactly 32 bytes")
perm = list(range(32))
secrets.SystemRandom().shuffle(perm)
a = bytearray(secrets.token_bytes(32))
b = bytearray(32)
# Store shares in permuted slots. Runtime reconstruction is intentionally simple
# obfuscation, not a security boundary; AES-GCM is the actual cryptographic layer.
for logical, slot in enumerate(perm):
    b[slot] = key[logical] ^ a[slot]

def arr(name, data):
    return f"var {name} = [...]byte{{" + ",".join(f"0x{x:02x}" for x in data) + "}\n"
text = "// Code generated locally for release builds. DO NOT COMMIT.\npackage assetkey\n\n"
text += arr("buildShareA", a)
text += arr("buildShareB", b)
text += "var buildPermutation = [...]byte{" + ",".join(map(str, perm)) + "}\n\n"
text += "func init() {\n\tseed := make([]byte, 32)\n\tfor logical, slot := range buildPermutation { seed[logical] = buildShareA[slot] ^ buildShareB[slot] }\n\tInstallEmbeddedSeed(seed)\n\tfor i := range seed { seed[i] = 0 }\n}\n"
Path(sys.argv[2]).write_text(text)
