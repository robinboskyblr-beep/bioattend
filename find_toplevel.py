content = open(r'd:\app\frontend\app.js', encoding='utf-8').read()
lines = content.split('\n')

# Find all lines that are NOT inside functions (top-level executable statements)
# Simple heuristic: lines with no leading whitespace that are not: 
# - empty, comments, function defs, let/const/var declarations, class defs
# - but DO contain things like document.getElementById, IIFE, etc.

inside_block = 0
top_level_exec = []

for i, line in enumerate(lines, 1):
    stripped = line.strip()
    if not stripped or stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*'):
        continue
    
    # Count braces
    opens = stripped.count('{')
    closes = stripped.count('}')
    
    if inside_block == 0:
        # This is top-level
        if not (stripped.startswith('function ') or 
                stripped.startswith('async function ') or
                stripped.startswith('class ') or
                stripped.startswith('//') or
                stripped.startswith('let ') or
                stripped.startswith('const ') or
                stripped.startswith('var ') or
                stripped.startswith('}')):
            top_level_exec.append((i, stripped[:120]))
    
    inside_block += opens - closes
    if inside_block < 0:
        inside_block = 0

print(f"Top-level executable statements ({len(top_level_exec)} total):")
for lineno, line in top_level_exec:
    print(f"  Line {lineno}: {line}")
