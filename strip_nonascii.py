"""
Strip all non-ASCII bytes from app.js comments and replace garbage Unicode
with clean ASCII. This fixes browser JS parsing failures caused by bad encoding.
"""

with open(r'd:\app\frontend\app.js', 'rb') as f:
    raw = f.read()

# Decode as UTF-8 (we know it works)
text = raw.decode('utf-8')

import re

# Replace the garbled section divider comments like:
# /* Ã¢ââ¬Ã¢ââ¬ Screens Ã¢ââ¬Ã¢ââ¬ */
# with clean ASCII comments like:
# /* ── Screens ── */
def clean_non_ascii(m):
    inner = m.group(1)
    # Remove all non-ASCII chars, collapse whitespace
    cleaned = re.sub(r'[^\x00-\x7F]+', '', inner).strip()
    if not cleaned:
        return '/* */'
    return f'/* {cleaned} */'

# Replace block comments containing non-ASCII
text = re.sub(r'/\*([^*]*)\*/', clean_non_ascii, text)

# Also replace any remaining non-ASCII characters outside comments
# (these appear in string literals and are display artifacts like arrows, emojis, rupee signs)
# We'll replace them with their intended characters based on known patterns

# Common garbled patterns in this file:
replacements = [
    # Scanning ellipsis
    ('Ã¢â¬Â¦', '...'),
    # Em dash  
    ('Ã¢â¬â', '—'),
    ('Ã¢â¬â€™', '–'),
    # Arrows
    ('Ã¢â â', '→'),
    ('Ã¢âÂ¬', '←'),
    # Check marks / X marks
    ('Ã¢Å...', '✅'),
    ('Ã¢ÂÅ', '❌'),
    ('Ã¢Ââ', '⚠'),
    ('Ã¢Å¡Â ', '⚡'),
    # Rupee sign
    ('Ã¢âÂ¹', '₹'),
    # Scanning icon
    ('Ã¢-â°', '◉'),
    # Wave/person emojis (these are already fine as \uXXXX but the garbled bytes remain)
    ('Ã°Å¸Å¸Â¢', '🟢'),
    ('Ã°Å¸ââ¹', '🚶'),
    ('Ã°Å¸âÂµ', '🚵'),
    # Any remaining non-ASCII sequences - replace with empty string  
]

for garbled, replacement in replacements:
    text = text.replace(garbled, replacement)

# Final pass: remove any remaining non-ASCII characters
# (these are only in comments and display strings, not in JS syntax)
cleaned_lines = []
for line in text.split('\n'):
    # Remove non-ASCII chars
    cleaned = ''.join(c if ord(c) < 128 else '' for c in line)
    cleaned_lines.append(cleaned)

text = '\n'.join(cleaned_lines)

print(f"File size after cleaning: {len(text.encode('utf-8'))} bytes")
remaining_non_ascii = sum(1 for c in text if ord(c) > 127)
print(f"Remaining non-ASCII chars: {remaining_non_ascii}")

with open(r'd:\app\frontend\app.js', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done! File written as clean ASCII.")
