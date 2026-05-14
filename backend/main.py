import os
import cv2
import json
import time
import uuid
import base64
import shutil
import logging
import hashlib
import numpy as np
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ─────────────────────────────────────────────
# Firebase / Firestore init
# ─────────────────────────────────────────────
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    _env_creds = os.environ.get("FIREBASE_CREDENTIALS")
    if _env_creds:
        # Cloud / Render: credentials stored as JSON string in env var
        cred_dict = json.loads(_env_creds)
        cred = credentials.Certificate(cred_dict)
    else:
        # Local development: load from file
        _SA_PATH = Path(__file__).parent / "bioattend-c4f14-firebase-adminsdk-fbsvc-0008324a24.json"
        cred = credentials.Certificate(str(_SA_PATH))
    firebase_admin.initialize_app(cred)

db_fs = firestore.client()

# Firestore collection references
EMPLOYEES_COL   = db_fs.collection("employees")
ATTENDANCE_COL  = db_fs.collection("attendance")
ADMINS_COL      = db_fs.collection("admins")


# ─────────────────────────────────────────────
# Configure logging
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Robinbosky BioAttend API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR   = Path(__file__).parent.parent
FACES_DIR  = BASE_DIR / "data" / "faces"
FACES_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────
# Password helper
# ─────────────────────────────────────────────

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# ─────────────────────────────────────────────
# Firestore helpers — Admins
# ─────────────────────────────────────────────

def ensure_default_admins():
    """Seed admin & manager accounts if they don't exist in Firestore."""
    defaults = {
        "admin": {
            "password": hash_password("admin123"),
            "name": "Administrator",
            "role": "admin",
            "email": "admin@robinbosky.com"
        },
        "manager": {
            "password": hash_password("manager123"),
            "name": "Manager",
            "role": "manager",
            "email": "manager@robinbosky.com"
        }
    }
    for username, data in defaults.items():
        doc = ADMINS_COL.document(username).get()
        if not doc.exists:
            ADMINS_COL.document(username).set(data)
            logger.info(f"Seeded default admin: {username}")

ensure_default_admins()

def get_admin(username: str) -> Optional[dict]:
    doc = ADMINS_COL.document(username).get()
    return doc.to_dict() if doc.exists else None

def set_admin(username: str, data: dict):
    ADMINS_COL.document(username).set(data, merge=True)

# ─────────────────────────────────────────────
# Firestore helpers — Employees
# ─────────────────────────────────────────────

def get_employee(employee_id: str) -> Optional[dict]:
    doc = EMPLOYEES_COL.document(employee_id).get()
    return doc.to_dict() if doc.exists else None

def set_employee(employee_id: str, data: dict):
    EMPLOYEES_COL.document(employee_id).set(data)

def update_employee_fields(employee_id: str, fields: dict):
    EMPLOYEES_COL.document(employee_id).update(fields)

def delete_employee_doc(employee_id: str):
    EMPLOYEES_COL.document(employee_id).delete()

def get_all_employees() -> List[dict]:
    docs = EMPLOYEES_COL.stream()
    return [d.to_dict() for d in docs]

def get_employee_by_email(email: str) -> Optional[dict]:
    """Find an employee document by their email address."""
    docs = EMPLOYEES_COL.where("email", "==", email.lower().strip()).limit(1).stream()
    for d in docs:
        return d.to_dict()
    return None

# ─────────────────────────────────────────────
# Firestore helpers — Attendance
# ─────────────────────────────────────────────

def get_attendance_record(record_id: str) -> Optional[dict]:
    doc = ATTENDANCE_COL.document(record_id).get()
    return doc.to_dict() if doc.exists else None

def set_attendance_record(record_id: str, data: dict):
    ATTENDANCE_COL.document(record_id).set(data)

def update_attendance_record(record_id: str, fields: dict):
    ATTENDANCE_COL.document(record_id).update(fields)

def get_today_records(today: str) -> List[dict]:
    docs = ATTENDANCE_COL.where("date", "==", today).stream()
    return [d.to_dict() for d in docs]

def get_employee_today_records(employee_id: str, today: str) -> List[dict]:
    docs = (ATTENDANCE_COL
            .where("employee_id", "==", employee_id)
            .where("date", "==", today)
            .stream())
    return [d.to_dict() for d in docs]

def get_attendance_by_filters(start_date=None, end_date=None, employee_id=None) -> List[dict]:
    query = ATTENDANCE_COL
    if employee_id:
        query = query.where("employee_id", "==", employee_id)
    if start_date:
        query = query.where("date", ">=", start_date)
    if end_date:
        query = query.where("date", "<=", end_date)
    docs = query.stream()
    return [d.to_dict() for d in docs]

# ─────────────────────────────────────────────
# Face Recognition helpers — LBP Histogram (v2)
# ─────────────────────────────────────────────

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

EMB_V2_SIZE = 512   # 4×4 grid × 32 bins = 512
EMB_V1_SIZE = 16384  # legacy raw pixel (128×128)

def detect_faces(img_array: np.ndarray):
    gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    # CLAHE normalises illumination before detection
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80))
    return faces, gray


def extract_face_embedding(gray: np.ndarray, face_rect) -> np.ndarray:
    """
    Extract LBP (Local Binary Pattern) histogram features from a face.
    Returns a 512-dim normalised float32 vector — far more discriminative
    than raw pixel values and robust to lighting / minor pose changes.
    """
    x, y, w, h = face_rect
    face_roi = gray[y:y+h, x:x+w]

    # Resize to fixed 64×64
    face_resized = cv2.resize(face_roi, (64, 64))

    # CLAHE illumination normalisation on the crop
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    face_eq = clahe.apply(face_resized)

    # LBP in a 4×4 grid of cells → 16 cells × 32 histogram bins = 512 features
    GRID = 4
    cell_h = face_eq.shape[0] // GRID
    cell_w = face_eq.shape[1] // GRID
    NEIGHBORS = [(-1,-1),(-1,0),(-1,1),(0,1),(1,1),(1,0),(1,-1),(0,-1)]
    features = []

    for gy in range(GRID):
        for gx in range(GRID):
            cell = face_eq[gy*cell_h:(gy+1)*cell_h, gx*cell_w:(gx+1)*cell_w].astype(np.int32)
            lbp_map = np.zeros(cell.shape, dtype=np.uint8)
            for bit_idx, (dy, dx) in enumerate(NEIGHBORS):
                ys = np.clip(np.arange(cell_h) + dy, 0, cell_h - 1)
                xs = np.clip(np.arange(cell_w) + dx, 0, cell_w - 1)
                neighbor = cell[np.ix_(ys, xs)]
                lbp_map |= ((cell >= neighbor).astype(np.uint8) << bit_idx)
            hist, _ = np.histogram(lbp_map.flatten(), bins=32, range=(0, 256))
            features.extend(hist.tolist())

    feat = np.array(features, dtype=np.float32)
    total = feat.sum()
    return feat / total if total > 0 else feat


def chi_square_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Chi-square similarity for histograms — the standard metric for LBP.
    Returns a value in (0, 1]; 1.0 = identical histograms.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if len(a) != len(b):
        return 0.0
    mask = (a + b) > 0
    if not mask.any():
        return 0.0
    chi2 = float(np.sum((a[mask] - b[mask]) ** 2 / (a[mask] + b[mask])))
    return 1.0 / (1.0 + chi2)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Legacy cosine similarity for v1 raw-pixel embeddings."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def emb_to_str(emb: list) -> str:
    return json.dumps(emb)


def str_to_emb(s: str) -> np.ndarray:
    return np.array(json.loads(s), dtype=np.float32)


def compare_with_all_employees(embedding: np.ndarray):
    """
    Compare a face embedding against all employees.
    - v2 (LBP, 512-dim): chi-square similarity, threshold 0.72
    - v1 (raw pixel, 16384-dim): cosine similarity, threshold 0.90
    Uses average of top-3 stored-sample scores per employee for robustness.
    """
    employees = get_all_employees()
    best_match = None
    best_score = 0.0
    is_v2 = (len(embedding) == EMB_V2_SIZE)

    THRESHOLD_V2 = 0.72
    THRESHOLD_V1 = 0.90

    for emp in employees:
        stored_embeddings = emp.get("embeddings", [])
        scores_for_emp = []

        for stored_emb in stored_embeddings:
            emb_arr = str_to_emb(stored_emb) if isinstance(stored_emb, str) else np.array(stored_emb, dtype=np.float32)
            stored_is_v2 = (len(emb_arr) == EMB_V2_SIZE)

            # Only compare same-version embeddings
            if is_v2 != stored_is_v2:
                continue

            score = chi_square_similarity(embedding, emb_arr) if is_v2 else cosine_similarity(embedding, emb_arr)
            scores_for_emp.append(score)

        if scores_for_emp:
            # Average of best 3 samples → more robust than single best
            top3 = sorted(scores_for_emp, reverse=True)[:3]
            avg = sum(top3) / len(top3)
            if avg > best_score:
                best_score = avg
                best_match = emp.get("id")

    threshold = THRESHOLD_V2 if is_v2 else THRESHOLD_V1
    if best_score >= threshold:
        return best_match, best_score
    return None, best_score

def decode_base64_image(b64_str: str) -> np.ndarray:
    if "," in b64_str:
        b64_str = b64_str.split(",")[1]
    img_bytes = base64.b64decode(b64_str)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

# ─────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    employee_id: str
    department: str
    role: str
    email: str
    phone: str
    shift_start: str = "09:00"
    shift_end: str = "19:00"
    lunch_break_start: str = "13:00"
    lunch_break_end: str = "14:00"
    password: str = "emp123"
    monthly_salary: float = 0.0
    images: List[str]

class UpdateEmployeeRequest(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    lunch_break_start: Optional[str] = None
    lunch_break_end: Optional[str] = None
    monthly_salary: Optional[float] = None

class ChangePasswordRequest(BaseModel):
    username: str
    role: str
    old_password: str
    new_password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ScanRequest(BaseModel):
    image: str

class ManualAttendanceRequest(BaseModel):
    employee_id: str
    type: str
    date: Optional[str] = None

class AttendanceQueryRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    employee_id: Optional[str] = None

# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    # ── Admin / Manager ──
    admin = get_admin(req.username)
    if admin:
        if admin["password"] == hash_password(req.password):
            return {
                "success": True,
                "role": admin.get("role", "admin"),
                "name": admin["name"],
                "email": admin.get("email", ""),
                "username": req.username,
                "token": f"{admin['role']}_{req.username}"
            }
        raise HTTPException(status_code=401, detail="Invalid password")

    # ── Employee — try by employee_id first, then by email ──
    emp = get_employee(req.username)
    if not emp:
        emp = get_employee_by_email(req.username)
    if emp:
        stored_pw = emp.get("password", hash_password("emp123"))
        if stored_pw == hash_password(req.password):
            return {
                "success": True,
                "role": "employee",
                "name": emp["name"],
                "employee_id": emp["id"],
                "department": emp.get("department", ""),
                "email": emp.get("email", ""),
                "shift_start": emp.get("shift_start", "09:00"),
                "shift_end": emp.get("shift_end", "19:00"),
                "token": f"employee_{emp['id']}"
            }
        raise HTTPException(status_code=401, detail="Invalid password")

    raise HTTPException(status_code=401, detail="User not found")

@app.post("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest):
    if req.role in ("admin", "manager"):
        acc = get_admin(req.username)
        if not acc:
            raise HTTPException(status_code=404, detail="User not found")
        if acc["password"] != hash_password(req.old_password):
            raise HTTPException(status_code=401, detail="Old password incorrect")
        set_admin(req.username, {"password": hash_password(req.new_password)})
    elif req.role == "employee":
        emp = get_employee(req.username)
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")
        if emp.get("password", hash_password("emp123")) != hash_password(req.old_password):
            raise HTTPException(status_code=401, detail="Old password incorrect")
        update_employee_fields(req.username, {"password": hash_password(req.new_password)})
    else:
        raise HTTPException(status_code=400, detail="Invalid role")
    return {"success": True, "message": "Password changed successfully"}

# ─────────────────────────────────────────────
# Employee Registration & Management
# ─────────────────────────────────────────────

@app.get("/api/employees/my-attendance/{employee_id}")
async def get_my_attendance(employee_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    records = get_attendance_by_filters(start_date=start_date, end_date=end_date, employee_id=employee_id)
    records.sort(key=lambda r: r.get("date", ""))
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")
    today_rec = [r for r in records if r["date"] == today]
    return {
        "employee_id": employee_id,
        "records": records,
        "total": len(records),
        "today": today_rec[0] if today_rec else None
    }

@app.post("/api/employees/register")
async def register_employee(req: RegisterRequest):
    if get_employee(req.employee_id):
        raise HTTPException(status_code=400, detail="Employee ID already registered")

    embeddings = []
    face_images_saved = []

    for i, b64_img in enumerate(req.images):
        try:
            img = decode_base64_image(b64_img)
            if img is None:
                continue
            faces, gray = detect_faces(img)
            if len(faces) == 0:
                continue
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            emb = extract_face_embedding(gray, largest_face)
            embeddings.append(emb_to_str(emb.tolist()))  # store as JSON string

            face_path = FACES_DIR / f"{req.employee_id}_{i}.jpg"
            x, y, w, h = largest_face
            face_img = img[y:y+h, x:x+w]
            cv2.imwrite(str(face_path), face_img)
            face_images_saved.append(str(face_path))
        except Exception as e:
            logger.error(f"Error processing image {i}: {e}")
            continue

    if len(embeddings) < 1:
        raise HTTPException(status_code=400, detail="No valid face detected. Please retake photos with good lighting.")

    emp_data = {
        "id": req.employee_id,
        "name": req.name,
        "department": req.department,
        "role": req.role,
        "email": req.email,
        "phone": req.phone,
        "shift_start": req.shift_start,
        "shift_end": req.shift_end,
        "lunch_break_start": req.lunch_break_start,
        "lunch_break_end": req.lunch_break_end,
        "monthly_salary": req.monthly_salary,
        "password": hash_password(req.password),
        "embeddings": embeddings,
        "face_images": face_images_saved,
        "registered_at": datetime.now().isoformat(),
        "active": True
    }
    set_employee(req.employee_id, emp_data)
    return {
        "success": True,
        "message": f"Employee {req.name} registered with {len(embeddings)} face samples",
        "employee_id": req.employee_id,
        "portal_password": req.password
    }

@app.get("/api/employees")
async def get_employees():
    all_emps = get_all_employees()
    users = []
    for u in all_emps:
        user_data = {k: v for k, v in u.items() if k not in ("embeddings", "password")}
        users.append(user_data)
    users.sort(key=lambda u: u.get("name", ""))
    return {"employees": users}

@app.get("/api/employees/{employee_id}")
async def get_employee_route(employee_id: str):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {k: v for k, v in emp.items() if k != "embeddings"}

@app.delete("/api/employees/{employee_id}")
async def delete_employee(employee_id: str):
    if not get_employee(employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    delete_employee_doc(employee_id)
    for f in FACES_DIR.glob(f"{employee_id}_*.jpg"):
        f.unlink(missing_ok=True)
    return {"success": True, "message": "Employee deleted"}

@app.patch("/api/employees/{employee_id}")
async def update_employee(employee_id: str, req: UpdateEmployeeRequest):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    fields = {}
    if req.name is not None:             fields["name"] = req.name
    if req.department is not None:       fields["department"] = req.department
    if req.role is not None:             fields["role"] = req.role
    if req.email is not None:            fields["email"] = req.email
    if req.phone is not None:            fields["phone"] = req.phone
    if req.shift_start is not None:      fields["shift_start"] = req.shift_start
    if req.shift_end is not None:        fields["shift_end"] = req.shift_end
    if req.lunch_break_start is not None: fields["lunch_break_start"] = req.lunch_break_start
    if req.lunch_break_end is not None:  fields["lunch_break_end"] = req.lunch_break_end
    if req.monthly_salary is not None:   fields["monthly_salary"] = req.monthly_salary
    if fields:
        update_employee_fields(employee_id, fields)
    return {"success": True, "message": f"Employee {employee_id} updated successfully"}


class ReregisterFaceRequest(BaseModel):
    images: List[str]

@app.post("/api/employees/{employee_id}/reregister-face")
async def reregister_face(employee_id: str, req: ReregisterFaceRequest):
    """
    Re-process face photos for an existing employee using the new LBP algorithm.
    Replaces old v1 (raw pixel) embeddings with new v2 (LBP histogram) ones.
    """
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    embeddings = []
    face_images_saved = []

    for i, b64_img in enumerate(req.images):
        try:
            img = decode_base64_image(b64_img)
            if img is None:
                continue
            faces, gray = detect_faces(img)
            if len(faces) == 0:
                continue
            largest_face = max(faces, key=lambda f: f[2] * f[3])
            emb = extract_face_embedding(gray, largest_face)
            embeddings.append(emb_to_str(emb.tolist()))

            face_path = FACES_DIR / f"{employee_id}_{i}.jpg"
            x, y, w, h = largest_face
            face_img = img[y:y+h, x:x+w]
            cv2.imwrite(str(face_path), face_img)
            face_images_saved.append(str(face_path))
        except Exception as e:
            logger.error(f"Re-register image {i} error: {e}")
            continue

    if len(embeddings) < 1:
        raise HTTPException(status_code=400, detail="No valid face detected in provided photos. Please retake with good lighting.")

    update_employee_fields(employee_id, {
        "embeddings": embeddings,
        "face_images": face_images_saved,
        "reregistered_at": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
    })

    return {
        "success": True,
        "message": f"Face data updated for {emp['name']} with {len(embeddings)} new LBP samples",
        "employee_id": employee_id,
        "samples": len(embeddings)
    }

# ─────────────────────────────────────────────
# Face Scanning / Attendance (4-punch system)
# ─────────────────────────────────────────────

@app.post("/api/attendance/scan")
async def scan_face(req: ScanRequest):
    try:
        img = decode_base64_image(req.image)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")

        faces, gray = detect_faces(img)
        if len(faces) == 0:
            return {"success": False, "message": "No face detected. Please position your face in the camera.", "detected": False}

        IST = timezone(timedelta(hours=5, minutes=30))
        now   = datetime.now(IST)
        today = now.strftime("%Y-%m-%d")
        t     = now.strftime("%H:%M:%S")

        results = []
        for face_rect in faces:
            emb = extract_face_embedding(gray, face_rect)
            matched_id, score = compare_with_all_employees(emb)
            conf = round(score * 100, 1)

            if matched_id:
                emp = get_employee(matched_id)
                today_recs = get_employee_today_records(matched_id, today)
                today_recs.sort(key=lambda r: r.get("timestamp", ""))

                if not today_recs:
                    # Punch 1 — Morning Clock IN
                    rec_id = str(uuid.uuid4())
                    record = {
                        "id":          rec_id,
                        "employee_id": matched_id,
                        "name":        emp["name"],
                        "department":  emp["department"],
                        "date":        today,
                        "check_in":    t,
                        "check_out":   None,
                        "check_in_2":  None,
                        "check_out_2": None,
                        "status":      "present",
                        "confidence":  conf,
                        "timestamp":   now.isoformat()
                    }
                    set_attendance_record(rec_id, record)
                    results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in", "punch": 1, "time": t, "confidence": conf})

                else:
                    rec = today_recs[-1]
                    rec_id = rec["id"]

                    if rec.get("check_out") is None:
                        # Punch 2 — Lunch OUT
                        update_attendance_record(rec_id, {"check_out": t})
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out", "punch": 2, "time": t, "confidence": conf})

                    elif rec.get("check_in_2") is None:
                        # Punch 3 — Afternoon IN
                        update_attendance_record(rec_id, {"check_in_2": t})
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in_2", "punch": 3, "time": t, "confidence": conf})

                    elif rec.get("check_out_2") is None:
                        # Punch 4 — End of Day OUT
                        update_attendance_record(rec_id, {"check_out_2": t})
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out_2", "punch": 4, "time": t, "confidence": conf})

                    else:
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "already_complete", "punch": 0, "message": "All 4 attendance punches complete for today"})
            else:
                results.append({"employee_id": None, "action": "unknown", "message": f"Face not recognized (confidence: {conf}%)"})

        return {"success": True, "detected": True, "results": results, "face_count": len(faces)}

    except Exception as e:
        logger.error(f"Scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/attendance/manual")
async def manual_attendance(req: ManualAttendanceRequest):
    emp = get_employee(req.employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    target_date = req.date or now.strftime("%Y-%m-%d")
    today_recs = get_employee_today_records(req.employee_id, target_date)
    today_recs.sort(key=lambda r: r.get("timestamp", ""))

    if req.type == "check_in":
        if today_recs:
            raise HTTPException(status_code=400, detail="Already checked in today")
        rec_id = str(uuid.uuid4())
        record = {
            "id":          rec_id,
            "employee_id": req.employee_id,
            "name":        emp["name"],
            "department":  emp["department"],
            "date":        target_date,
            "check_in":    now.strftime("%H:%M:%S"),
            "check_out":   None,
            "check_in_2":  None,
            "check_out_2": None,
            "status":      "present",
            "confidence":  100.0,
            "manual":      True,
            "timestamp":   now.isoformat()
        }
        set_attendance_record(rec_id, record)
    elif req.type == "check_out":
        if not today_recs or today_recs[-1].get("check_out"):
            raise HTTPException(status_code=400, detail="No open check-in found")
        update_attendance_record(today_recs[-1]["id"], {"check_out": now.strftime("%H:%M:%S")})

    return {"success": True, "message": f"Manual {req.type} recorded for {emp['name']}"}

@app.get("/api/attendance/today")
async def get_today_attendance():
    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(IST).strftime("%Y-%m-%d")
    records = get_today_records(today)
    records.sort(key=lambda r: r.get("timestamp", ""))
    return {"date": today, "records": records, "total": len(records)}

@app.get("/api/attendance/history")
async def get_attendance_history(start_date: Optional[str] = None, end_date: Optional[str] = None, employee_id: Optional[str] = None):
    records = get_attendance_by_filters(start_date=start_date, end_date=end_date, employee_id=employee_id)
    records.sort(key=lambda r: (r.get("date", ""), r.get("timestamp", "")))
    return {"records": records, "total": len(records)}

@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    all_emps  = get_all_employees()
    IST = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_recs = get_today_records(today_str)

    total_employees = len(all_emps)
    present_today   = len(set(r["employee_id"] for r in today_recs))
    absent_today    = total_employees - present_today

    # Weekly stats
    week_stats = {}
    for i in range(7):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_recs = get_today_records(d)
        week_stats[d] = len(set(r["employee_id"] for r in day_recs))

    return {
        "total_employees":  total_employees,
        "present_today":    present_today,
        "absent_today":     absent_today,
        "attendance_rate":  round((present_today / total_employees * 100) if total_employees > 0 else 0, 1),
        "today_records":    today_recs,
        "weekly_stats":     week_stats
    }

# ─────────────────────────────────────────────
# Payroll
# ─────────────────────────────────────────────

@app.get("/api/payroll/calculate")
async def calculate_payroll(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    employee_id: Optional[str] = None
):
    records = get_attendance_by_filters(start_date=start_date, end_date=end_date, employee_id=employee_id)
    all_emps = {e["id"]: e for e in get_all_employees()}

    emp_records: dict = {}
    for r in records:
        eid = r["employee_id"]
        emp_records.setdefault(eid, []).append(r)

    payroll = []
    for uid, emp_recs in emp_records.items():
        if uid not in all_emps:
            continue
        user         = all_emps[uid]
        monthly_salary = float(user.get("monthly_salary", 0))
        shift_start    = user.get("shift_start", "09:00")
        working_days   = len(emp_recs)
        total_penalty  = 0
        late_days      = 0
        late_details   = []

        for rec in emp_recs:
            check_in = rec.get("check_in")
            if not check_in:
                continue
            try:
                sh, sm = map(int, shift_start.split(":"))
                ci_parts = check_in.split(":")
                ch, cm   = int(ci_parts[0]), int(ci_parts[1])
                minutes_late = (ch * 60 + cm) - (sh * 60 + sm)
                if minutes_late > 10:
                    total_penalty += 100
                    late_days += 1
                    late_details.append({"date": rec["date"], "check_in": check_in, "minutes_late": minutes_late, "penalty": 100})
            except Exception:
                pass

        daily_rate  = monthly_salary / 26 if monthly_salary > 0 else 0
        gross_earned = round(daily_rate * working_days, 2)
        net_salary   = round(gross_earned - total_penalty, 2)

        payroll.append({
            "employee_id":   uid,
            "name":          user["name"],
            "department":    user.get("department", ""),
            "monthly_salary": monthly_salary,
            "daily_rate":    round(daily_rate, 2),
            "working_days":  working_days,
            "gross_earned":  gross_earned,
            "late_days":     late_days,
            "total_penalty": total_penalty,
            "net_salary":    net_salary,
            "late_details":  late_details
        })

    return {"payroll": payroll, "period": {"start": start_date, "end": end_date}}

# ─────────────────────────────────────────────
# Backup Endpoints
# ─────────────────────────────────────────────

@app.get("/api/backup/daily")
async def backup_daily(target_date: Optional[str] = None):
    """Return full attendance records for a given date (default: today)."""
    if not target_date:
        IST = timezone(timedelta(hours=5, minutes=30))
        target_date = datetime.now(IST).strftime("%Y-%m-%d")
    records = get_today_records(target_date)
    records.sort(key=lambda r: (r.get("employee_id", ""), r.get("timestamp", "")))
    all_emps = {e["id"]: e for e in get_all_employees()}

    # Enrich records with employee info
    enriched = []
    for r in records:
        emp = all_emps.get(r.get("employee_id"), {})
        enriched.append({
            "date":           r.get("date", target_date),
            "employee_id":    r.get("employee_id", ""),
            "name":           r.get("name", ""),
            "department":     r.get("department", ""),
            "role":           emp.get("role", ""),
            "email":          emp.get("email", ""),
            "phone":          emp.get("phone", ""),
            "shift_start":    emp.get("shift_start", ""),
            "shift_end":      emp.get("shift_end", ""),
            "clock_in":       r.get("check_in", ""),
            "lunch_out":      r.get("check_out", ""),
            "lunch_in":       r.get("check_in_2", ""),
            "clock_out":      r.get("check_out_2", ""),
            "status":         r.get("status", "present"),
            "confidence":     r.get("confidence", ""),
            "manual":         r.get("manual", False),
        })
    return {"date": target_date, "records": enriched, "total": len(enriched)}

@app.get("/api/backup/range")
async def backup_range(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Return attendance records for a date range with enriched employee data."""
    records = get_attendance_by_filters(start_date=start_date, end_date=end_date)
    records.sort(key=lambda r: (r.get("date", ""), r.get("employee_id", "")))
    all_emps = {e["id"]: e for e in get_all_employees()}
    enriched = []
    for r in records:
        emp = all_emps.get(r.get("employee_id"), {})
        enriched.append({
            "date":        r.get("date", ""),
            "employee_id": r.get("employee_id", ""),
            "name":        r.get("name", ""),
            "department":  r.get("department", ""),
            "role":        emp.get("role", ""),
            "email":       emp.get("email", ""),
            "phone":       emp.get("phone", ""),
            "shift_start": emp.get("shift_start", ""),
            "shift_end":   emp.get("shift_end", ""),
            "clock_in":    r.get("check_in", ""),
            "lunch_out":   r.get("check_out", ""),
            "lunch_in":    r.get("check_in_2", ""),
            "clock_out":   r.get("check_out_2", ""),
            "status":      r.get("status", ""),
            "confidence":  r.get("confidence", ""),
            "manual":      r.get("manual", False),
        })
    return {"start_date": start_date, "end_date": end_date, "records": enriched, "total": len(enriched)}

@app.get("/api/backup/employees")
async def backup_employees():
    """Return full employee directory (excluding embeddings & passwords)."""
    all_emps = get_all_employees()
    safe = []
    for e in all_emps:
        safe.append({k: v for k, v in e.items() if k not in ("embeddings", "password", "face_images")})
    safe.sort(key=lambda e: e.get("name", ""))
    return {"employees": safe, "total": len(safe), "exported_at": datetime.now().isoformat()}

# ─────────────────────────────────────────────
# Static frontend
# ─────────────────────────────────────────────

frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
