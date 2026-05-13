import subprocess, sys

# Check the actual encoding and look for BOM or invalid characters
with open(r'd:\app\frontend\app.js', 'rb') as f:
    raw = f.read()

print(f"File size: {len(raw)} bytes")
print(f"First 10 bytes (hex): {raw[:10].hex()}")
print(f"BOM check: {'UTF-8 BOM' if raw[:3] == b'\xef\xbb\xbf' else 'No BOM'}")

# Try decoding as utf-8
try:
    text = raw.decode('utf-8')
    print("UTF-8 decode: OK")
except UnicodeDecodeError as e:
    print(f"UTF-8 decode ERROR: {e}")

# Try decoding as latin-1 (always succeeds)
text_latin = raw.decode('latin-1')
print(f"Latin-1 decode: OK, {len(text_latin)} chars")

# Find any non-ASCII characters
non_ascii = [(i, hex(b)) for i, b in enumerate(raw) if b > 127]
print(f"\nNon-ASCII bytes: {len(non_ascii)}")
if non_ascii:
    print("First 10 non-ASCII byte positions:")
    for pos, h in non_ascii[:10]:
        ctx = raw[max(0,pos-20):pos+20]
        print(f"  pos {pos} ({h}): ...{ctx}...")

# Check for Windows-1252 issues
print("\nChecking for Windows-1252 encoding artifacts...")
# Common pattern: e2 80 94 = em dash in UTF-8
em_dash = raw.count(b'\xe2\x80\x94')
print(f"UTF-8 em-dash sequences: {em_dash}")

# Check if it's actually latin-1 encoded UTF-8 text (double-encoded)
test_slice = raw[27:50]
print(f"\nBytes 27-50: {test_slice}")
print(f"As latin-1: {test_slice.decode('latin-1')}")
