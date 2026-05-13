with open(r'd:\app\frontend\app.js', 'rb') as f:
    content = f.read()

nulls = content.count(b'\x00')
print(f'Null bytes: {nulls}')
print(f'Last 50 bytes (hex): {content[-50:].hex()}')
print(f'Last chars: {repr(content[-100:])}')

text = content.decode('utf-8')
backtick_count = text.count('`')
even = backtick_count % 2 == 0
print(f'Backtick count: {backtick_count}')
if even:
    print('Backticks: EVEN - OK')
else:
    print('Backticks: ODD - PROBLEM!')
