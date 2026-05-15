import os
import cv2
import csv
import io
import json
import time
import uuid
import base64
import shutil
import logging
import hashlib
import smtplib
import asyncio
import urllib.request
import urllib.error
import numpy as np
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
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
# Face Recognition — InsightFace ArcFace (v3)
# ─────────────────────────────────────────────
# Professional deep-learning pipeline:
#   Camera → Detection → Alignment → ArcFace embedding → Cosine matching
# Embeddings: 512-dim L2-normalised float32 vectors
# Similarity: cosine similarity, threshold 0.45 (InsightFace scale)
# Matching:   max(cosine_sim(new, stored_i) for stored_i in user_embeddings)
# Auto-update: if score > AUTO_UPDATE_THRESHOLD, new embedding is added
#              and profile is pruned to MAX_EMBEDDINGS_PER_USER
# ─────────────────────────────────────────────

try:
    from deepface import DeepFace as _DeepFace
    import tensorflow as _tf
    _tf.get_logger().setLevel("ERROR")   # silence TF INFO spam
    # Warm-up: trigger model download/load at startup, not on first request
    _DeepFace.build_model("ArcFace")
    DEEPFACE_AVAILABLE = True
    logger.info("DeepFace ArcFace model loaded successfully.")
except Exception as _e:
    DEEPFACE_AVAILABLE = False
    logger.warning(f"DeepFace not available ({_e}). Falling back to LBP.")

# For clarity everywhere below, alias the flag
INSIGHTFACE_AVAILABLE = DEEPFACE_AVAILABLE

# ── Fallback: LBP cascade (used only when InsightFace is unavailable) ──
_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
LBP_EMB_SIZE  = 512
LEGACY_EMB_SIZE = 16384

# ── Thresholds ──
ARCFACE_THRESHOLD     = 0.45   # cosine similarity (InsightFace ArcFace)
ARCFACE_AUTO_UPDATE   = 0.55   # above this → save new embedding to profile
LBP_THRESHOLD         = 0.78   # chi-square similarity (fallback LBP)
LEGACY_THRESHOLD      = 0.90   # cosine similarity (v1 raw-pixel, legacy)
MAX_EMBEDDINGS        = 20     # rolling cap per user


# ── Quality score ──────────────────────────────────────────────────────

def compute_quality_score(img_bgr: np.ndarray, face_box) -> float:
    """
    Returns a quality score 0–1 for a detected face crop.
    Rejects: blurry frames, tiny faces, very dark crops.
    """
    x, y, w, h = int(face_box[0]), int(face_box[1]), int(face_box[2]), int(face_box[3])
    # Face too small
    if w < 60 or h < 60:
        return 0.0
    crop = img_bgr[y:y+h, x:x+w]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    # Blur: Laplacian variance (higher = sharper)
    blur = cv2.Laplacian(gray, cv2.CV_64F).var()
    blur_score = min(blur / 200.0, 1.0)           # normalise; 200 = good sharpness
    # Brightness: reject very dark frames
    brightness = gray.mean() / 255.0
    bright_score = 1.0 if brightness > 0.2 else brightness / 0.2
    return round(blur_score * 0.7 + bright_score * 0.3, 3)


# ── Embedding helpers ──────────────────────────────────────────────────

def emb_to_str(emb: list) -> str:
    return json.dumps([round(float(v), 6) for v in emb])

def str_to_emb(s) -> np.ndarray:
    if isinstance(s, str):
        return np.array(json.loads(s), dtype=np.float32)
    return np.array(s, dtype=np.float32)

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised vectors."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a / na, b / nb))

def chi_square_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Chi-square similarity for LBP histograms."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    if len(a) != len(b):
        return 0.0
    mask = (a + b) > 0
    if not mask.any():
        return 0.0
    chi2 = float(np.sum((a[mask] - b[mask]) ** 2 / (a[mask] + b[mask])))
    return 1.0 / (1.0 + chi2)


# ── Primary: InsightFace ArcFace pipeline ─────────────────────────────

def arcface_process(img_bgr: np.ndarray):
    """
    Detect + align + embed all faces using DeepFace ArcFace.
    Returns list of (embedding_512, quality_score, bbox_xywh).
    bbox_xywh = (x, y, w, h) as integers.
    """
    if not INSIGHTFACE_AVAILABLE:
        return []
    try:
        # CLAHE enhancement before detection
        lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        img_bgr = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

        # DeepFace.represent returns a list of dicts, one per detected face
        # Each dict: {"embedding": [...], "facial_area": {"x","y","w","h"}, ...}
        reps = _DeepFace.represent(
            img_path=img_bgr,
            model_name="ArcFace",
            detector_backend="opencv",   # fast, same cascade we use
            enforce_detection=False,     # return empty if no face rather than raise
            align=True,
        )
        results = []
        for rep in reps:
            raw_emb = rep.get("embedding")
            if raw_emb is None:
                continue
            emb = np.array(raw_emb, dtype=np.float32)
            # L2-normalise to unit sphere
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            fa = rep.get("facial_area", {})
            x, y, w, h = fa.get("x", 0), fa.get("y", 0), fa.get("w", 64), fa.get("h", 64)
            quality = compute_quality_score(img_bgr, (x, y, w, h))
            results.append((emb, quality, (x, y, w, h)))   # bbox as xywh tuple
        return results
    except Exception as e:
        logger.warning(f"arcface_process error: {e}")
        return []


# ── Fallback: LBP histogram pipeline ──────────────────────────────────

def _lbp_detect(img_bgr: np.ndarray):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    faces = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80)
    )
    return faces, gray

def _lbp_embed(gray: np.ndarray, face_rect) -> np.ndarray:
    x, y, w, h = face_rect
    face_resized = cv2.resize(gray[y:y+h, x:x+w], (64, 64))
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    face_eq = clahe.apply(face_resized)
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


# ── Unified decode helper ──────────────────────────────────────────────

def decode_base64_image(b64_str: str) -> np.ndarray:
    if "," in b64_str:
        b64_str = b64_str.split(",")[1]
    img_bytes = base64.b64decode(b64_str)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)


# ── Core matching ──────────────────────────────────────────────────────

def _is_arcface_emb(arr: np.ndarray) -> bool:
    return len(arr) == 512 and (abs(np.linalg.norm(arr) - 1.0) < 0.05)

def compare_with_all_employees(embedding: np.ndarray, use_arcface: bool = False):
    """
    Match embedding against every employee's stored embeddings.

    Strategy (per employee):
      score = max(similarity(new_emb, stored_i) for stored_i in stored_embeddings)

    This is the recommended professional approach — best-sample wins.
    Ambiguity guard: reject if gap between top-2 employees < 0.04.

    Returns (matched_employee_id | None, best_score, top_candidates)
    """
    employees = get_all_employees()
    best_match_id   = None
    best_score      = 0.0
    all_candidates  = []   # [(score, name, id)]

    for emp in employees:
        stored_list = emp.get("embeddings", [])
        if not stored_list:
            continue

        emp_best = 0.0
        for raw in stored_list:
            stored = str_to_emb(raw)
            if use_arcface and _is_arcface_emb(stored):
                score = cosine_sim(embedding, stored)
            elif not use_arcface and len(stored) == LBP_EMB_SIZE:
                score = chi_square_sim(embedding, stored)
            elif not use_arcface and len(stored) == LEGACY_EMB_SIZE:
                score = cosine_sim(embedding, stored)
            else:
                continue
            if score > emp_best:
                emp_best = score

        if emp_best > 0:
            all_candidates.append((emp_best, emp.get("name", ""), emp.get("id", "")))
            if emp_best > best_score:
                best_score    = emp_best
                best_match_id = emp.get("id")

    all_candidates.sort(reverse=True)

    threshold = ARCFACE_THRESHOLD if use_arcface else LBP_THRESHOLD

    # Ambiguity guard
    if len(all_candidates) >= 2:
        gap = all_candidates[0][0] - all_candidates[1][0]
        if best_score >= threshold and gap < 0.04:
            logger.warning(
                f"Ambiguous: {all_candidates[0][1]}={all_candidates[0][0]:.3f} "
                f"vs {all_candidates[1][1]}={all_candidates[1][0]:.3f}, gap={gap:.3f}"
            )
            return None, best_score, all_candidates[:3]

    if best_score >= threshold:
        return best_match_id, best_score, all_candidates[:3]
    return None, best_score, all_candidates[:3]


def auto_update_face_profile(employee_id: str, new_emb: np.ndarray, score: float):
    """
    If score > ARCFACE_AUTO_UPDATE, add the new embedding to the employee's
    rolling profile (max MAX_EMBEDDINGS). Oldest embeddings are pruned first.
    This prevents the need for manual re-registration.
    """
    if score < ARCFACE_AUTO_UPDATE:
        return
    emp = get_employee(employee_id)
    if not emp:
        return
    stored = list(emp.get("embeddings", []))
    stored.append(emb_to_str(new_emb.tolist()))
    # Prune: keep the most recent MAX_EMBEDDINGS
    if len(stored) > MAX_EMBEDDINGS:
        stored = stored[-MAX_EMBEDDINGS:]
    update_employee_fields(employee_id, {
        "embeddings": stored,
        "profile_updated_at": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
    })
    logger.info(f"Auto-updated face profile for {employee_id} (score={score:.3f}, total={len(stored)})")


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
    break_start: str = "16:30"
    break_end: str = "17:00"
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
    break_start: Optional[str] = None
    break_end: Optional[str] = None
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
    rejected = 0

    for i, b64_img in enumerate(req.images):
        try:
            img = decode_base64_image(b64_img)
            if img is None:
                continue

            if INSIGHTFACE_AVAILABLE:
                # ── ArcFace path ──
                faces = arcface_process(img)
                for emb, quality, bbox in faces:
                    if quality < 0.15:
                        rejected += 1
                        logger.info(f"Reg image {i}: rejected low quality ({quality:.2f})")
                        continue
                    embeddings.append(emb_to_str(emb.tolist()))
                    x,y,w,h = bbox
                    face_crop = img[y:y+h, x:x+w]
                    face_path = FACES_DIR / f"{req.employee_id}_{i}.jpg"
                    cv2.imwrite(str(face_path), face_crop)
                    face_images_saved.append(str(face_path))
                    break  # one face per photo
            else:
                # ── LBP fallback ──
                faces, gray = _lbp_detect(img)
                if len(faces) == 0:
                    continue
                largest = max(faces, key=lambda f: f[2]*f[3])
                emb = _lbp_embed(gray, largest)
                embeddings.append(emb_to_str(emb.tolist()))
                x,y,w,h = largest
                face_path = FACES_DIR / f"{req.employee_id}_{i}.jpg"
                cv2.imwrite(str(face_path), img[y:y+h, x:x+w])
                face_images_saved.append(str(face_path))

        except Exception as e:
            logger.error(f"Error processing image {i}: {e}")
            continue

    if len(embeddings) < 1:
        raise HTTPException(
            status_code=400,
            detail=f"No valid face detected ({rejected} rejected for low quality). "
                   "Please retake photos in good lighting, facing the camera."
        )

    method = "ArcFace" if INSIGHTFACE_AVAILABLE else "LBP"
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
        "break_start": req.break_start,
        "break_end": req.break_end,
        "monthly_salary": req.monthly_salary,
        "password": hash_password(req.password),
        "embeddings": embeddings,
        "face_images": face_images_saved,
        "embedding_method": method,
        "registered_at": datetime.now().isoformat(),
        "active": True
    }
    set_employee(req.employee_id, emp_data)
    return {
        "success": True,
        "message": f"Employee {req.name} registered with {len(embeddings)} {method} face embeddings",
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
    if req.break_start is not None:      fields["break_start"] = req.break_start
    if req.break_end is not None:        fields["break_end"] = req.break_end
    if req.monthly_salary is not None:   fields["monthly_salary"] = req.monthly_salary
    if fields:
        update_employee_fields(employee_id, fields)
    return {"success": True, "message": f"Employee {employee_id} updated successfully"}


class ReregisterFaceRequest(BaseModel):
    images: List[str]

@app.post("/api/employees/{employee_id}/reregister-face")
async def reregister_face(employee_id: str, req: ReregisterFaceRequest):
    """
    Re-process face photos for an existing employee.
    Uses ArcFace when available, otherwise LBP fallback.
    Completely replaces the stored embedding profile.
    """
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    embeddings = []
    face_images_saved = []
    rejected = 0

    for i, b64_img in enumerate(req.images):
        try:
            img = decode_base64_image(b64_img)
            if img is None:
                continue

            if INSIGHTFACE_AVAILABLE:
                faces = arcface_process(img)
                for emb, quality, bbox in faces:
                    if quality < 0.15:
                        rejected += 1
                        continue
                    embeddings.append(emb_to_str(emb.tolist()))
                    x,y,w,h = bbox
                    face_path = FACES_DIR / f"{employee_id}_{i}.jpg"
                    cv2.imwrite(str(face_path), img[y:y+h, x:x+w])
                    face_images_saved.append(str(face_path))
                    break
            else:
                faces, gray = _lbp_detect(img)
                if len(faces) == 0:
                    continue
                largest = max(faces, key=lambda f: f[2]*f[3])
                emb = _lbp_embed(gray, largest)
                embeddings.append(emb_to_str(emb.tolist()))
                x,y,w,h = largest
                face_path = FACES_DIR / f"{employee_id}_{i}.jpg"
                cv2.imwrite(str(face_path), img[y:y+h, x:x+w])
                face_images_saved.append(str(face_path))

        except Exception as e:
            logger.error(f"Re-register image {i} error: {e}")
            continue

    if len(embeddings) < 1:
        raise HTTPException(
            status_code=400,
            detail=f"No valid face detected ({rejected} rejected for quality). Retake in better lighting."
        )

    method = "ArcFace" if INSIGHTFACE_AVAILABLE else "LBP"
    update_employee_fields(employee_id, {
        "embeddings": embeddings,
        "face_images": face_images_saved,
        "embedding_method": method,
        "reregistered_at": datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat()
    })
    return {
        "success": True,
        "message": f"Face data updated for {emp['name']} — {len(embeddings)} {method} embeddings stored",
        "employee_id": employee_id,
        "samples": len(embeddings),
        "method": method
    }

# ─────────────────────────────────────────────
# Face Scanning / Attendance (6-punch system)
# ─────────────────────────────────────────────

@app.post("/api/attendance/scan")
async def scan_face(req: ScanRequest):
    try:
        img = decode_base64_image(req.image)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")

        IST   = timezone(timedelta(hours=5, minutes=30))
        now   = datetime.now(IST)
        today = now.strftime("%Y-%m-%d")
        t     = now.strftime("%H:%M:%S")
        results = []

        if INSIGHTFACE_AVAILABLE:
            # ══ ArcFace path ══
            arc_faces = arcface_process(img)
            if not arc_faces:
                return {"success": False, "message": "No face detected. Please position your face in the camera.", "detected": False}

            for emb, quality, bbox in arc_faces:
                if quality < 0.10:
                    results.append({"action": "low_quality", "message": "Image too blurry or dark — please improve lighting.", "confidence": 0})
                    continue

                matched_id, score, candidates = compare_with_all_employees(emb, use_arcface=True)
                # Display confidence as 0-100%, scaled from ArcFace cosine range (0.3-0.7 typical)
                conf = round(min(score / ARCFACE_THRESHOLD, 1.0) * 100, 1)

                if matched_id:
                    emp = get_employee(matched_id)
                    today_recs = get_employee_today_records(matched_id, today)
                    today_recs.sort(key=lambda r: r.get("timestamp", ""))

                    # Auto-update rolling face profile
                    auto_update_face_profile(matched_id, emb, score)

                    # Record punch
                    if not today_recs:
                        rec_id = str(uuid.uuid4())
                        set_attendance_record(rec_id, {
                            "id": rec_id, "employee_id": matched_id, "name": emp["name"],
                            "department": emp["department"], "date": today,
                            "check_in": t, "check_out": None, "check_in_2": None,
                            "check_out_3": None, "check_in_3": None, "check_out_2": None,
                            "status": "present", "confidence": conf, "timestamp": now.isoformat()
                        })
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in", "punch": 1, "time": t, "confidence": conf})
                    else:
                        rec = today_recs[-1]
                        rid = rec["id"]
                        if   rec.get("check_out")  is None: update_attendance_record(rid, {"check_out":  t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out",  "punch": 2, "time": t, "confidence": conf})
                        elif rec.get("check_in_2") is None: update_attendance_record(rid, {"check_in_2": t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in_2", "punch": 3, "time": t, "confidence": conf})
                        elif rec.get("check_out_3")is None: update_attendance_record(rid, {"check_out_3":t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out_3","punch": 4, "time": t, "confidence": conf})
                        elif rec.get("check_in_3") is None: update_attendance_record(rid, {"check_in_3": t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in_3", "punch": 5, "time": t, "confidence": conf})
                        elif rec.get("check_out_2")is None: update_attendance_record(rid, {"check_out_2":t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out_2","punch": 6, "time": t, "confidence": conf})
                        else: results.append({"employee_id": matched_id, "name": emp["name"], "action": "already_complete", "punch": 0, "message": "All 6 punches complete for today", "confidence": conf})
                else:
                    top = candidates[0] if candidates else None
                    results.append({"employee_id": None, "action": "unknown", "confidence": conf,
                                    "message": f"Face not recognized (best: {top[1] if top else 'none'} @ {round(top[0],3) if top else 0} — need ≥{ARCFACE_THRESHOLD})"})
                break  # process only the largest/first face per scan

        else:
            # ══ LBP fallback path ══
            faces, gray = _lbp_detect(img)
            if len(faces) == 0:
                return {"success": False, "message": "No face detected. Please position your face in the camera.", "detected": False}

            for face_rect in faces:
                emb = _lbp_embed(gray, face_rect)
                matched_id, score, candidates = compare_with_all_employees(emb, use_arcface=False)
                conf = round(score * 100, 1)

                if matched_id:
                    emp = get_employee(matched_id)
                    today_recs = get_employee_today_records(matched_id, today)
                    today_recs.sort(key=lambda r: r.get("timestamp", ""))

                    if not today_recs:
                        rec_id = str(uuid.uuid4())
                        set_attendance_record(rec_id, {
                            "id": rec_id, "employee_id": matched_id, "name": emp["name"],
                            "department": emp["department"], "date": today,
                            "check_in": t, "check_out": None, "check_in_2": None,
                            "check_out_3": None, "check_in_3": None, "check_out_2": None,
                            "status": "present", "confidence": conf, "timestamp": now.isoformat()
                        })
                        results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in", "punch": 1, "time": t, "confidence": conf})
                    else:
                        rec = today_recs[-1]
                        rid = rec["id"]
                        if   rec.get("check_out")  is None: update_attendance_record(rid, {"check_out":  t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out",  "punch": 2, "time": t, "confidence": conf})
                        elif rec.get("check_in_2") is None: update_attendance_record(rid, {"check_in_2": t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in_2", "punch": 3, "time": t, "confidence": conf})
                        elif rec.get("check_out_3")is None: update_attendance_record(rid, {"check_out_3":t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out_3","punch": 4, "time": t, "confidence": conf})
                        elif rec.get("check_in_3") is None: update_attendance_record(rid, {"check_in_3": t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_in_3", "punch": 5, "time": t, "confidence": conf})
                        elif rec.get("check_out_2")is None: update_attendance_record(rid, {"check_out_2":t}); results.append({"employee_id": matched_id, "name": emp["name"], "action": "check_out_2","punch": 6, "time": t, "confidence": conf})
                        else: results.append({"employee_id": matched_id, "name": emp["name"], "action": "already_complete", "punch": 0, "message": "All 6 punches complete for today", "confidence": conf})
                else:
                    top = candidates[0] if candidates else None
                    results.append({"employee_id": None, "action": "unknown", "confidence": conf,
                                    "message": f"Face not recognized (best: {top[1] if top else 'none'} @ {round(top[0]*100,1) if top else 0}% — need ≥{round(LBP_THRESHOLD*100)}%)"})

        return {"success": True, "detected": True, "results": results, "face_count": 1}

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
            "id":           rec_id,
            "employee_id":  req.employee_id,
            "name":         emp["name"],
            "department":   emp["department"],
            "date":         target_date,
            "check_in":     now.strftime("%H:%M:%S"),
            "check_out":    None,
            "check_in_2":   None,
            "check_out_3":  None,
            "check_in_3":   None,
            "check_out_2":  None,
            "status":       "present",
            "confidence":   100.0,
            "manual":       True,
            "timestamp":    now.isoformat()
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

@app.delete("/api/attendance/clear")
async def clear_attendance(
    date: Optional[str] = None,
    employee_id: Optional[str] = None
):
    """
    Delete attendance records from Firestore.
    - No params       -> delete ALL records
    - date=YYYY-MM-DD -> delete all records for that date
    - employee_id=X   -> delete records for that employee
    - both            -> delete records matching both filters
    """
    try:
        query = ATTENDANCE_COL
        if employee_id:
            query = query.where("employee_id", "==", employee_id)
        if date:
            query = query.where("date", "==", date)

        docs = list(query.stream())
        deleted = 0
        BATCH_SIZE = 400
        for i in range(0, len(docs), BATCH_SIZE):
            batch = db_fs.batch()
            for doc in docs[i:i + BATCH_SIZE]:
                batch.delete(doc.reference)
            batch.commit()
            deleted += len(docs[i:i + BATCH_SIZE])

        scope_parts = []
        if date:        scope_parts.append(f"date={date}")
        if employee_id: scope_parts.append(f"employee={employee_id}")
        scope_str = ", ".join(scope_parts) if scope_parts else "ALL records"

        logger.info(f"Cleared {deleted} attendance records ({scope_str})")
        return {"success": True, "deleted": deleted, "scope": scope_str}

    except Exception as e:
        logger.error(f"Clear attendance error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dashboard/stats")
async def get_dashboard_stats():
    try:
        IST = timezone(timedelta(hours=5, minutes=30))
        today_str = datetime.now(IST).strftime("%Y-%m-%d")

        all_emps   = get_all_employees()
        today_recs = get_today_records(today_str)

        # Filter out any malformed records missing required fields
        safe_today = [r for r in today_recs if r.get("employee_id") and r.get("date")]

        total_employees = len(all_emps)
        present_today   = len(set(r["employee_id"] for r in safe_today))
        absent_today    = max(0, total_employees - present_today)

        # Weekly stats — use IST dates
        week_stats = {}
        for i in range(7):
            d = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
            day_recs = get_today_records(d)
            safe_day = [r for r in day_recs if r.get("employee_id")]
            week_stats[d] = len(set(r["employee_id"] for r in safe_day))

        # Build safe today_records list for the frontend
        today_out = []
        for r in safe_today:
            today_out.append({
                "employee_id": r.get("employee_id", ""),
                "name":        r.get("name", "Unknown"),
                "department":  r.get("department", ""),
                "date":        r.get("date", today_str),
                "check_in":    r.get("check_in") or "—",
                "check_out":   r.get("check_out"),
                "check_in_2":  r.get("check_in_2"),
                "check_out_3": r.get("check_out_3"),
                "check_in_3":  r.get("check_in_3"),
                "check_out_2": r.get("check_out_2"),
                "status":      r.get("status", "present"),
                "confidence":  r.get("confidence", 0),
            })

        return {
            "total_employees":  total_employees,
            "present_today":    present_today,
            "absent_today":     absent_today,
            "attendance_rate":  round((present_today / total_employees * 100) if total_employees > 0 else 0, 1),
            "today_records":    today_out,
            "weekly_stats":     week_stats
        }
    except Exception as e:
        logger.error(f"Dashboard stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Dashboard error: {str(e)}")

# ─────────────────────────────────────────────
# Payroll
# ─────────────────────────────────────────────

@app.get("/api/payroll/calculate")
async def calculate_payroll(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    employee_id: Optional[str] = None
):
    try:
        # ── Fetch records (avoid composite-index requirement) ──
        try:
            records = get_attendance_by_filters(
                start_date=start_date,
                end_date=end_date,
                employee_id=employee_id
            )
        except Exception as qe:
            # Fallback: stream all then filter in Python (handles missing Firestore composite index)
            logger.warning(f"Payroll compound query failed ({qe}), falling back to in-memory filter")
            all_docs = list(ATTENDANCE_COL.stream())
            records = [d.to_dict() for d in all_docs]
            if employee_id:
                records = [r for r in records if r.get("employee_id") == employee_id]
            if start_date:
                records = [r for r in records if r.get("date", "") >= start_date]
            if end_date:
                records = [r for r in records if r.get("date", "") <= end_date]

        all_emps = {e["id"]: e for e in get_all_employees()}

        emp_records: dict = {}
        for r in records:
            eid = r.get("employee_id", "")
            if eid:
                emp_records.setdefault(eid, []).append(r)

        payroll = []
        for uid, emp_recs in emp_records.items():
            if uid not in all_emps:
                continue
            user           = all_emps[uid]
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
                        late_details.append({
                            "date": rec.get("date", ""),
                            "check_in": check_in,
                            "minutes_late": minutes_late,
                            "penalty": 100
                        })
                except Exception:
                    pass

            daily_rate   = monthly_salary / 26 if monthly_salary > 0 else 0
            gross_earned = round(daily_rate * working_days, 2)
            net_salary   = round(gross_earned - total_penalty, 2)

            payroll.append({
                "employee_id":    uid,
                "name":           user.get("name", uid),
                "department":     user.get("department", ""),
                "monthly_salary": monthly_salary,
                "daily_rate":     round(daily_rate, 2),
                "working_days":   working_days,
                "gross_earned":   gross_earned,
                "late_days":      late_days,
                "total_penalty":  total_penalty,
                "net_salary":     net_salary,
                "late_details":   late_details
            })

        return {"payroll": payroll, "period": {"start": start_date, "end": end_date}}

    except Exception as e:
        logger.error(f"Payroll calculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Payroll error: {str(e)}")


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
            "clock_in":      r.get("check_in", ""),
            "lunch_out":     r.get("check_out", ""),
            "lunch_in":      r.get("check_in_2", ""),
            "break_out":     r.get("check_out_3", ""),
            "break_in":      r.get("check_in_3", ""),
            "clock_out":     r.get("check_out_2", ""),
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

@app.get("/api/debug/test")
async def debug_test():
    """Diagnostic endpoint — tests Firestore and returns any error."""
    result = {}
    try:
        emps = get_all_employees()
        result["employees_count"] = len(emps)
    except Exception as e:
        result["employees_error"] = str(e)

    try:
        IST = timezone(timedelta(hours=5, minutes=30))
        today = datetime.now(IST).strftime("%Y-%m-%d")
        recs = get_today_records(today)
        result["today_records_count"] = len(recs)
        result["today"] = today
        if recs:
            result["sample_record_keys"] = list(recs[0].keys())
    except Exception as e:
        result["attendance_error"] = str(e)

    return result

# ─────────────────────────────────────────────
# Email Backup
# ─────────────────────────────────────────────

SETTINGS_COL = db_fs.collection("settings")

class BackupEmailRequest(BaseModel):
    recipient: Optional[str] = None

# ── Resend API helper (HTTPS — works on all cloud providers) ──
def _send_via_resend(api_key: str, to_email: str, subject: str, body: str,
                     csv_bytes: bytes = None, csv_filename: str = None) -> dict:
    """
    Send email via Resend HTTP API (https://resend.com).
    Uses HTTPS port 443 — never blocked by cloud providers.
    """
    payload = {
        "from": "BioAttend Backup <onboarding@resend.dev>",
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if csv_bytes and csv_filename:
        payload["attachments"] = [{
            "filename": csv_filename,
            "content": base64.b64encode(csv_bytes).decode("utf-8")
        }]

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

class SmtpSettingsRequest(BaseModel):
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    resend_api_key: Optional[str] = None

@app.post("/api/settings/smtp")
async def save_smtp_settings(req: SmtpSettingsRequest):
    """Save email credentials to Firestore."""
    data_to_save = {}
    if req.resend_api_key:
        data_to_save["resend_api_key"] = req.resend_api_key
    if req.smtp_user:
        if "@" not in req.smtp_user:
            raise HTTPException(status_code=400, detail="Invalid Gmail address")
        data_to_save["smtp_user"] = req.smtp_user
    if req.smtp_pass:
        data_to_save["smtp_pass"] = req.smtp_pass
        data_to_save["smtp_host"] = req.smtp_host or "smtp.gmail.com"
        data_to_save["smtp_port"] = req.smtp_port or 587
    if not data_to_save:
        raise HTTPException(status_code=400, detail="No credentials provided")
    SETTINGS_COL.document("smtp").set(data_to_save, merge=True)
    return {"success": True, "message": "Email settings saved"}

@app.get("/api/settings/smtp")
async def get_smtp_settings():
    doc = SETTINGS_COL.document("smtp").get()
    if doc.exists:
        d = doc.to_dict()
        return {
            "configured": True,
            "smtp_user": d.get("smtp_user", ""),
            "smtp_host": d.get("smtp_host", "smtp.gmail.com"),
            "smtp_port": d.get("smtp_port", 587),
            "resend_configured": bool(d.get("resend_api_key", "")),
        }
    return {"configured": False, "smtp_user": "", "smtp_host": "smtp.gmail.com", "smtp_port": 587, "resend_configured": False}

@app.post("/api/settings/backup-email")
async def save_backup_email(req: BackupEmailRequest):
    """Save the backup recipient email to Firestore settings."""
    if not req.recipient or "@" not in req.recipient:
        raise HTTPException(status_code=400, detail="Invalid email address")
    SETTINGS_COL.document("backup").set({"email": req.recipient}, merge=True)
    return {"success": True, "email": req.recipient}

@app.get("/api/settings/backup-email")
async def get_backup_email():
    doc = SETTINGS_COL.document("backup").get()
    if doc.exists:
        return {"email": doc.to_dict().get("email", "")}
    return {"email": ""}

# ─────────────────────────────────────────────
# Direct CSV Download (no email needed)
# ─────────────────────────────────────────────
from fastapi.responses import StreamingResponse

@app.get("/api/backup/download")
async def download_backup_csv():
    """
    Stream the full attendance + employee CSV directly to the browser.
    No SMTP, no third-party — just a direct download. Works everywhere.
    """
    IST      = timezone(timedelta(hours=5, minutes=30))
    today    = datetime.now(IST).strftime("%Y-%m-%d")
    now_str  = datetime.now(IST).strftime("%Y-%m-%d_%H-%M")

    all_emps  = get_all_employees()
    emp_map   = {e["id"]: e for e in all_emps}
    all_recs  = list(ATTENDANCE_COL.stream())
    records   = [r.to_dict() for r in all_recs]
    records.sort(key=lambda r: (r.get("date", ""), r.get("name", "")))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Employee Name", "Employee ID", "Department",
        "Clock In (AM)", "Clock Out (Lunch)", "Clock In (PM)", "Clock Out (Day)",
        "Status", "Punches", "Confidence %"
    ])
    for rec in records:
        emp  = emp_map.get(rec.get("employee_id", ""), {})
        dept = emp.get("department", rec.get("department", ""))
        p1   = rec.get("check_in")    or ""
        p2   = rec.get("check_out")   or ""
        p3   = rec.get("check_in_2")  or ""
        p4   = rec.get("check_out_2") or ""
        punches = sum(1 for v in [p1, p2, p3, p4] if v)
        writer.writerow([
            rec.get("date", ""), rec.get("name", ""), rec.get("employee_id", ""),
            dept, p1, p2, p3, p4,
            rec.get("status", ""), f"{punches}/4", rec.get("confidence", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    filename  = f"bioattend_backup_{now_str}.csv"

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.post("/api/backup/send-email")
async def send_backup_email(req: BackupEmailRequest):

    """
    Collect all attendance records + employee info and email a CSV to the
    configured (or override) recipient using Gmail SMTP credentials stored
    in environment variables SMTP_USER and SMTP_PASS.
    """
    # ── Determine recipient ──
    recipient = req.recipient
    if not recipient:
        doc = SETTINGS_COL.document("backup").get()
        recipient = doc.to_dict().get("email", "") if doc.exists else ""
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=400, detail="No backup email configured. Please save one in Settings first.")

    # ── Load credentials from env vars then Firestore ──
    resend_key  = os.environ.get("RESEND_API_KEY", "")
    smtp_user   = os.environ.get("SMTP_USER", "")
    smtp_pass   = os.environ.get("SMTP_PASS", "")
    smtp_host   = os.environ.get("SMTP_HOST", "")
    smtp_port_s = os.environ.get("SMTP_PORT", "")

    smtp_doc = SETTINGS_COL.document("smtp").get()
    if smtp_doc.exists:
        sd = smtp_doc.to_dict()
        resend_key  = resend_key  or sd.get("resend_api_key", "")
        smtp_user   = smtp_user   or sd.get("smtp_user", "")
        smtp_pass   = smtp_pass   or sd.get("smtp_pass", "")
        smtp_host   = smtp_host   or sd.get("smtp_host", "smtp.gmail.com")
        smtp_port_s = smtp_port_s or str(sd.get("smtp_port", 587))

    smtp_host = smtp_host or "smtp.gmail.com"
    smtp_port = int(smtp_port_s) if smtp_port_s else 587

    if not resend_key and not (smtp_user and smtp_pass):
        raise HTTPException(
            status_code=500,
            detail="No email method configured. Please add a Resend API key in Settings → Email Backup → SMTP Setup."
        )

    IST     = timezone(timedelta(hours=5, minutes=30))
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    today   = datetime.now(IST).strftime("%Y-%m-%d")

    # ── Fetch data ──
    all_emps  = get_all_employees()
    emp_map   = {e["id"]: e for e in all_emps}
    all_recs  = list(ATTENDANCE_COL.stream())
    records   = [r.to_dict() for r in all_recs]
    records.sort(key=lambda r: (r.get("date", ""), r.get("name", "")))

    # ── Build CSV ──
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Employee Name", "Employee ID", "Department",
        "Clock In (AM)", "Clock Out (Lunch)", "Clock In (PM)", "Clock Out (Day)",
        "Status", "Punches", "Confidence %"
    ])
    for rec in records:
        emp  = emp_map.get(rec.get("employee_id", ""), {})
        dept = emp.get("department", rec.get("department", ""))
        p1   = rec.get("check_in")    or "—"
        p2   = rec.get("check_out")   or "—"
        p3   = rec.get("check_in_2")  or "—"
        p4   = rec.get("check_out_2") or "—"
        punches = sum(1 for v in [p1, p2, p3, p4] if v != "—")
        writer.writerow([
            rec.get("date", ""), rec.get("name", ""), rec.get("employee_id", ""),
            dept, p1, p2, p3, p4,
            rec.get("status", ""), f"{punches}/4", rec.get("confidence", ""),
        ])
    csv_bytes = output.getvalue().encode("utf-8")

    subject = f"BioAttend Backup — {today} (generated {now_str} IST)"
    body    = (
        f"Hi,\n\nPlease find attached the full BioAttend attendance backup generated on {now_str} IST.\n\n"
        f"Summary:\n"
        f"  • Total employees       : {len(all_emps)}\n"
        f"  • Total attendance records : {len(records)}\n\n"
        f"The CSV contains all clock-in and clock-out punches for every employee.\n\n"
        f"— Robinbosky BioAttend"
    )
    csv_filename = f"bioattend_backup_{today}.csv"

    # ── Send: Resend (HTTPS) first, SMTP fallback ──
    if resend_key:
        try:
            await asyncio.to_thread(
                _send_via_resend, resend_key, recipient, subject, body, csv_bytes, csv_filename
            )
            logger.info(f"Backup sent via Resend to {recipient} ({len(records)} records)")
            return {"success": True, "message": f"Backup sent to {recipient}", "method": "resend",
                    "records": len(records), "employees": len(all_emps)}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if hasattr(e, 'read') else str(e)
            raise HTTPException(status_code=500, detail=f"Resend API error: {err_body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Resend failed: {str(e)}")

    # SMTP fallback
    smtp_pass_clean = smtp_pass.replace(" ", "")
    msg = MIMEMultipart()
    msg["From"]    = smtp_user
    msg["To"]      = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    part = MIMEBase("application", "octet-stream")
    part.set_payload(csv_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{csv_filename}"')
    msg.attach(part)

    def _smtp_send():
        last_err = None
        for host, port, mode in [(smtp_host, 587, "STARTTLS"), (smtp_host, 465, "SSL")]:
            try:
                if mode == "SSL":
                    import ssl as _ssl
                    ctx = _ssl.create_default_context()
                    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
                        s.login(smtp_user, smtp_pass_clean)
                        s.sendmail(smtp_user, recipient, msg.as_string())
                else:
                    with smtplib.SMTP(host, port, timeout=20) as s:
                        s.ehlo(); s.starttls(); s.ehlo()
                        s.login(smtp_user, smtp_pass_clean)
                        s.sendmail(smtp_user, recipient, msg.as_string())
                return
            except Exception as ex:
                last_err = ex
                logger.warning(f"SMTP {mode}:{port} failed: {ex}")
        raise last_err


    try:
        await asyncio.to_thread(_smtp_send)
    except smtplib.SMTPAuthenticationError as e:
        raise HTTPException(status_code=500, detail=f"Gmail auth failed: {str(e)}. Use a Gmail App Password, not your login password.")
    except Exception as e:
        logger.error(f"Email backup error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    logger.info(f"Backup email sent to {recipient} ({len(records)} records)")
    return {
        "success": True,
        "message": f"Backup sent to {recipient}",
        "method": "smtp",
        "records": len(records),
        "employees": len(all_emps)
    }


@app.post("/api/backup/test-email")
async def test_email(req: BackupEmailRequest):
    """
    Send a tiny test email to diagnose SMTP connectivity.
    Returns detailed error messages to help the user fix configuration.
    """
    # Get recipient
    recipient = req.recipient
    if not recipient:
        doc = SETTINGS_COL.document("backup").get()
        recipient = doc.to_dict().get("email", "") if doc.exists else ""
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=400, detail="No recipient email configured.")

    # Get SMTP credentials
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        smtp_doc = SETTINGS_COL.document("smtp").get()
        if smtp_doc.exists:
            sd = smtp_doc.to_dict()
            smtp_user = smtp_user or sd.get("smtp_user", "")
            smtp_pass = smtp_pass or sd.get("smtp_pass", "")

    if not smtp_user or not smtp_pass:
        raise HTTPException(status_code=500, detail="SMTP credentials not saved. Go to Settings → SMTP Setup first.")

    smtp_pass_clean = smtp_pass.replace(" ", "")
    IST = timezone(timedelta(hours=5, minutes=30))
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    msg = MIMEText(
        f"Hello!\n\nThis is a test email from BioAttend sent at {now_str}.\n\n"
        f"If you see this, your email backup is working correctly!\n\n"
        f"— Robinbosky BioAttend",
        "plain"
    )
    msg["From"]    = smtp_user
    msg["To"]      = recipient
    msg["Subject"] = f"BioAttend Test Email — {now_str}"

    diag = {"attempts": []}

    def _try_send():
        attempts = [
            ("smtp.gmail.com", 587, "STARTTLS"),
            ("smtp.gmail.com", 465, "SSL"),
        ]
        for host, port, mode in attempts:
            try:
                if mode == "SSL":
                    import ssl as _ssl
                    ctx = _ssl.create_default_context()
                    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as server:
                        server.login(smtp_user, smtp_pass_clean)
                        server.sendmail(smtp_user, recipient, msg.as_string())
                else:
                    with smtplib.SMTP(host, port, timeout=20) as server:
                        server.ehlo()
                        server.starttls()
                        server.ehlo()
                        server.login(smtp_user, smtp_pass_clean)
                        server.sendmail(smtp_user, recipient, msg.as_string())
                diag["attempts"].append({"mode": mode, "port": port, "result": "SUCCESS"})
                return True
            except smtplib.SMTPAuthenticationError as ae:
                diag["attempts"].append({"mode": mode, "port": port, "result": f"AUTH FAIL: {ae}"})
            except Exception as ex:
                diag["attempts"].append({"mode": mode, "port": port, "result": f"ERROR: {ex}"})
        return False

    success = await asyncio.to_thread(_try_send)
    if success:
        return {"success": True, "message": f"Test email sent to {recipient}!", "diagnostics": diag}
    else:
        raise HTTPException(
            status_code=500,
            detail=f"All SMTP attempts failed. Diagnostics: {diag['attempts']}"
        )

frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
