#!/usr/bin/env python3
"""
Fix the encoding corruption in app.js where ':' was replaced by '--'
in specific JavaScript contexts.
"""
import re

with open(r'd:\app\frontend\app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# ── Fix 1: fetch headers  'Content-Type'--'application/json'
# Should be: 'Content-Type': 'application/json'
content = content.replace("'Content-Type'--'application/json'", "'Content-Type': 'application/json'")

# ── Fix 2: startCamera('...'--'...') and similar 2-arg calls
# Should be: startCamera('...', '...')
content = re.sub(r"startCamera\('([^']+)'--'([^']+)'\)", r"startCamera('\1', '\2')", content)
content = re.sub(r"captureFrame\('([^']+)'--'([^']+)'\)", r"captureFrame('\1', '\2')", content)

# ── Fix 3: setScanStatus('...'--'...') and toast('...'--'...')
content = re.sub(r"setScanStatus\('([^']+)'--'([^']+)'\)", r"setScanStatus('\1', '\2')", content)
content = re.sub(r"toast\('([^']+)'--'([^']+)'\)", r"toast('\1', '\2')", content)
content = re.sub(r"toast\(([^,)]+)--'([^']+)'\)", r"toast(\1, '\2')", content)

# ── Fix 4: showError('...'--'...')
content = re.sub(r"showError\('([^']+)'--'([^']+)'\)", r"showError('\1', '\2')", content)

# ── Fix 5: Ternary expressions  condition ? 'a'--'b'  should be  condition ? 'a' : 'b'
# Match: ? 'string'--'string'
content = re.sub(r"\? '([^']+)'--'([^']+)'", r"? '\1' : '\2'", content)
content = re.sub(r"\? '([^']+)'--`", r"? '\1' : `", content)  # mixed quote/template

# ── Fix 6: Multi-value ternaries like  a ? b--c--d  (chained)
# e.g. type === 'error'--'gradient...' : type === 'success'--'gradient...'--'gradient...'
# These are complex; handle one-by-one below

# ── Fix 7: Array literals with '--' as separator e.g. ['a'--'b'--'c']
# CAL_MONTHS = ['January'--'February'-- ...]
content = re.sub(r"const CAL_MONTHS = \[([^\]]+)\]", lambda m: 
    "const CAL_MONTHS = [" + m.group(1).replace("'--'", "', '") + "]", content)

# ── Fix 8: selects = ['manual-emp'--'report-emp-select'--'payroll-emp']
content = re.sub(r"\[('manual-emp')--('report-emp-select')--('payroll-emp')\]",
    r"[\1, \2, \3]", content)

# ── Fix 9: (isPayroll ? 'option...'--'option...')
content = re.sub(r"\(isPayroll \? '([^']+)'--'([^']+)'\)",
    r"(isPayroll ? '\1' : '\2')", content)

# ── Fix 10: status.classList.remove('hidden'--'error'--'success')
content = re.sub(r"classList\.remove\('([^']+)'--'([^']+)'--'([^']+)'\)",
    r"classList.remove('\1', '\2', '\3')", content)
content = re.sub(r"classList\.remove\('([^']+)'--'([^']+)'\)",
    r"classList.remove('\1', '\2')", content)
content = re.sub(r"classList\.remove\('([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'\)",
    r"classList.remove('\1', '\2', '\3', '\4')", content)

# ── Fix 11: el.classList.remove('hidden'--'success'--'error')
# Already covered above

# ── Fix 12: URL query string  url += '--' + params
content = content.replace("url += '--' + params.toString()", "url += '?' + params.toString()")
content = content.replace("url += '--' + p.toString()", "url += '?' + p.toString()")

# ── Fix 13: padStart(2,'--')  should be  padStart(2,'0')
content = content.replace("padStart(2,'--')", "padStart(2,'0')")
content = content.replace("padStart(2, '--')", "padStart(2, '0')")

# ── Fix 14: join('--')  should be  join(' ')  (for class list building)
# Be careful — some join('') are intentional. Only fix the class-list joins.
# Line: ].filter(Boolean).join('--');
content = content.replace("].filter(Boolean).join('--')", "].filter(Boolean).join(' ')")

# ── Fix 15: Template literal string concat issues in renderEmployees
# 'en-IN'--'/mo</div>'  should be 'en-IN') + '/mo</div>'
content = content.replace("toLocaleString('en-IN'--'/mo</div>'", "toLocaleString('en-IN')) + '/mo</div>'")

# ── Fix 16: shift start/end concat in renderEmployees
# '09:00'--' - '   should be  '09:00') + ' - '
content = content.replace("(e.shift_start || '09:00'--' - ' + (e.shift_end || '18:00')",
    "(e.shift_start || '09:00') + ' - ' + (e.shift_end || '18:00')")

# ── Fix 17: Attendance rate display  d.attendance_rate + '--'  → + '%'
content = content.replace("d.attendance_rate + '--'", "d.attendance_rate + '%'")

# ── Fix 18: lunch info string concat  '--' +  → '-' +   (lunch time range display)
# e.lunch_break_start + '--' + (e.lunch_break_end  should use '-'
content = content.replace("e.lunch_break_start + '--' + (e.lunch_break_end", 
    "e.lunch_break_start + '-' + (e.lunch_break_end")

# ── Fix 19: exportAttendance csv  .replace(/\n/g,'--')  should be ,'  ')
content = content.replace(r"replace(/\n/g,'--')", r"replace(/\n/g,' ')")
# Also the join in export  .join('--')  → .join(',')
content = content.replace(".map(c => `\"${c.innerText.replace(/\\n/g,' ')}\"`).join('--')",
    ".map(c => `\"${c.innerText.replace(/\\n/g,' ')}\"`).join(',')")

# ── Fix 20: report concat  join(''--'</tbody></table>'  → join('') + '</tbody></table>'
content = content.replace("join(''--'</tbody></table>'", "join('') + '</tbody></table>'")

# ── Fix 21: confidence display in attendance table  r.confidence + '--'  → + '%'
content = content.replace("r.confidence + '--'", "r.confidence + '%'")

# ── Fix 22: payroll penalty display  '--' + fmt(...)  → '-' + fmt(...)
content = content.replace("'--' + fmt(p.total_penalty)", "'-' + fmt(p.total_penalty)")

# ── Fix 23: exportPayrollCSV  department || '--'  → || ''
content = content.replace('"${p.department || \'--\'}"', '"${p.department || \'\'}"')

# ── Fix 24: toast style ternary chain
# type === 'error'--'linear-gradient...' : type === 'success'--'gradient...'--'gradient...'
content = content.replace(
    "t.style.background = type === 'error'--'linear-gradient(135deg,#f43f5e,#be123c)' : type === 'success'--'linear-gradient(135deg,#0ea5e9,#1d4ed8)'--'linear-gradient(135deg,#3b82f6,#1d4ed8)';",
    "t.style.background = type === 'error' ? 'linear-gradient(135deg,#f43f5e,#be123c)' : type === 'success' ? 'linear-gradient(135deg,#0ea5e9,#1d4ed8)' : 'linear-gradient(135deg,#3b82f6,#1d4ed8)';"
)

# ── Fix 25: hr < 17 ? 'Good Afternoon,'--'Good Evening,'
content = content.replace("? 'Good Afternoon,'--'Good Evening,'", "? 'Good Afternoon,' : 'Good Evening,'")

# ── Fix 26: badge-out vs badge-in ternary in template literals
# badge-${r.check_out ? 'out'--'in'}  → badge-${r.check_out ? 'out' : 'in'}
content = re.sub(r"\$\{([^}]+) \? '(out)'--'(in)'\}", r"${\1 ? '\2' : '\3'}", content)
content = re.sub(r"\$\{([^}]+) \? '(in)'--'(out)'\}", r"${\1 ? '\2' : '\3'}", content)
content = re.sub(r"\$\{([^}]+) \? '(Complete)'--'(In)'\}", r"${\1 ? '\2' : '\3'}", content)
content = re.sub(r"\$\{([^}]+) \? '(badge-present)'--'(badge-in)'\}", r"${\1 ? '\2' : '\3'}", content)
content = re.sub(r"\$\{([^}]+) \? '(status-full)'--'(status-half)'\}", r"${\1 ? '\2' : '\3'}", content)
content = re.sub(r"\$\{([^}]+) \? '(penalty-cell)'--'(zero-cell)'\}", r"${\1 ? '\2' : '\3'}", content)

# ── Fix 27: cal-day class join
# .join('--')  for the calendar classes → .join(' ')
content = content.replace("].filter(Boolean).join('--')", "].filter(Boolean).join(' ')")

# ── Fix 28: isWeekend?'weekend'-- ... chained ternaries in cls array
# ['cal-day', isWeekend?'weekend'--', isToday?'today'--', isFuture?'future'--', isSelected?'selected'--', statusClass]
content = content.replace(
    "['cal-day', isWeekend?'weekend'--', isToday?'today'--',\r\n\r\n      isFuture?'future'--', isSelected?'selected'--', statusClass",
    "['cal-day', isWeekend?'weekend':'', isToday?'today':'',\r\n\r\n      isFuture?'future':'', isSelected?'selected':'', statusClass"
)
content = content.replace(
    "['cal-day', isWeekend?'weekend'--', isToday?'today'--',\n\n      isFuture?'future'--', isSelected?'selected'--', statusClass",
    "['cal-day', isWeekend?'weekend':'', isToday?'today':'',\n\n      isFuture?'future':'', isSelected?'selected':'', statusClass"
)

# ── Fix 29: allFull ? 'status-full'--'status-half'
content = content.replace("allFull ? 'status-full'--'status-half'", "allFull ? 'status-full' : 'status-half'")
content = content.replace("allFull ? 'var(--green)'--'#f59e0b'", "allFull ? 'var(--green)' : '#f59e0b'")

# ── Fix 30: badge ${hasOut?'badge-present'--'badge-in'}
content = content.replace("${hasOut?'badge-present'--'badge-in'}", "${hasOut?'badge-present':'badge-in'}")
content = content.replace("${hasOut?'Complete'--'In'}", "${hasOut?'Complete':'In'}")

# ── Fix 31: d.total === 1 ? 'y'--'ies'
content = content.replace("d.total === 1 ? 'y'--'ies'", "d.total === 1 ? 'y' : 'ies'")

# ── Fix 32: capturedPhotos.length > 1 ? 's'--'' 
content = content.replace("capturedPhotos.length > 1 ? 's'--''", "capturedPhotos.length > 1 ? 's' : ''")
content = content.replace("capturedPhotos.length \u003e 1 ? 's'--''", "capturedPhotos.length > 1 ? 's' : ''")

# ── Fix 33: rec.check_out ? 'Complete'--'In'  (non-template)
content = content.replace("rec.check_out ? 'Complete'--'In'", "rec.check_out ? 'Complete' : 'In'")
content = content.replace("rec.check_out ? 'out'--'in'", "rec.check_out ? 'out' : 'in'")

# ── Fix 34: 'log-entry-badge ' + (rec.check_out ? 'out'--'in')
content = content.replace("(rec.check_out ? 'out'--'in')", "(rec.check_out ? 'out' : 'in')")

# ── Fix 35: d.success ? 'a'--'b' in simple fetch responses  (if any remain)
# General catch-all for remaining  'string'--'string'  patterns that are ternary false-branches
# We look for: ? 'anything' -- 'anything'
content = re.sub(r"\? '([^'<>{}()\n]+)'--'([^'<>{}()\n]+)'", r"? '\1' : '\2'", content)

# ── Fix 36: Remaining array '--' separators between quoted strings
content = re.sub(r"'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'",
    r"'\1', '\2', '\3', '\4', '\5', '\6'", content)
content = re.sub(r"'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'",
    r"'\1', '\2', '\3', '\4', '\5'", content)
content = re.sub(r"'([^']+)'--'([^']+)'--'([^']+)'--'([^']+)'",
    r"'\1', '\2', '\3', '\4'", content)
content = re.sub(r"'([^']+)'--'([^']+)'--'([^']+)'",
    r"'\1', '\2', '\3'", content)
content = re.sub(r"'([^']+)'--'([^']+)'",
    r"'\1', '\2'", content)

print("Writing fixed file...")
with open(r'd:\app\frontend\app.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done! Check app.js for remaining issues.")

# Show any remaining '--' occurrences for review
lines = content.split('\n')
remaining = [(i+1, l.rstrip()) for i, l in enumerate(lines) if "'--'" in l or '"--"' in l]
if remaining:
    print(f"\n{len(remaining)} lines still contain '--' (may need manual review):")
    for lineno, line in remaining[:30]:
        print(f"  Line {lineno}: {line.strip()}")
else:
    print("\nNo remaining '--' patterns found!")
