"""Fix the double \r\r\n line endings in app.js"""
with open(r'd:\app\frontend\app.js', 'rb') as f:
    content = f.read()

print(f"Before: {len(content)} bytes")

# Replace \r\r\n with \r\n
content = content.replace(b'\r\r\n', b'\r\n')
# Also fix any remaining \r\r not followed by \n
content = content.replace(b'\r\r', b'\r')

print(f"After: {len(content)} bytes")

remaining_non_ascii = sum(1 for b in content if b > 127)
print(f"Non-ASCII bytes: {remaining_non_ascii}")

with open(r'd:\app\frontend\app.js', 'wb') as f:
    f.write(content)

print("Done!")
