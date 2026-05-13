import json, sys
import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path

BASE = Path('D:/app')

if not firebase_admin._apps:
    cred = credentials.Certificate(str(BASE / 'backend' / 'bioattend-c4f14-firebase-adminsdk-fbsvc-0008324a24.json'))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ── Migrate employees ──
db_path = BASE / 'data' / 'database.json'
if db_path.exists():
    data = json.load(open(db_path))
    users = data.get('users', {})
    for emp_id, emp in users.items():
        # Firestore doesn't allow nested arrays.
        # Serialize each embedding (List[float]) as a JSON string.
        raw_embs = emp.get('embeddings', [])
        emp['embeddings'] = [json.dumps(e) for e in raw_embs]
        db.collection('employees').document(emp_id).set(emp)
        print("Migrated employee:", emp_id, "-", emp.get("name"))
    print("Total employees migrated:", len(users))
else:
    print("No database.json found - skipping")

# ── Migrate attendance ──
att_path = BASE / 'data' / 'attendance.json'
if att_path.exists():
    att = json.load(open(att_path))
    records = att.get('records', [])
    for rec in records:
        if 'id' in rec:
            db.collection('attendance').document(rec['id']).set(rec)
    print("Total attendance records migrated:", len(records))
else:
    print("No attendance.json found - skipping")

print("Migration complete!")
