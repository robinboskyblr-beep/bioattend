content = open(r'd:\app\frontend\app.js', encoding='utf-8').read()
issues = []
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    stripped = line.strip()
    # Check for remaining '--' in JS argument positions (not in HTML/strings that should have --)
    if "('--'" in stripped or "'--')" in stripped:
        issues.append(f'Line {i}: possible corruption: {stripped[:120]}')
    # Double closing parens from our fix
    double_paren = "toLocaleString('en-IN'))"
    if double_paren in line:
        issues.append(f'Line {i}: extra paren: {stripped[:120]}')

if issues:
    for x in issues[:20]:
        print(x)
else:
    print('No obvious issues found!')
print(f'Total lines: {len(lines)}, Total bytes: {len(content.encode())}')
