"""Suprajit: automatic local report indexing + secure download portal."""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Boolean, Date, DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.middleware.sessions import SessionMiddleware
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
REPORTS_ROOT = Path(os.getenv("REPORTS_ROOT", "D:/pass")).expanduser()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qube_reports.db")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "30"))
SECRET = os.getenv("SESSION_SECRET", "development-only-change-me")
# Only requests arriving from one of these IPs/CIDR ranges may use the ADMIN
# role, even if the logged-in account has role=ADMIN in the database. This
# keeps the admin console usable only on your laptop (or your VPN/LAN),
# while everyone else who signs in - including someone who somehow knew the
# admin password - is treated as an ordinary approved user.
ADMIN_ALLOWED_HOSTS = [h.strip() for h in os.getenv("ADMIN_ALLOWED_HOSTS", "127.0.0.1,::1").split(",") if h.strip()]
# Set to "true" only if FastAPI sits behind a reverse proxy that sets
# X-Forwarded-For with the real client IP. Leave "false" for direct/VPN use.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() == "true"
engine_args = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class LoginRequired(Exception):
    """Raised when a protected page is opened without an approved session."""

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(160), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(20), default="USER")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(800), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(300), index=True)
    recipe: Mapped[str] = mapped_column(String(150), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    report_time: Mapped[str] = mapped_column(String(20))
    serial: Mapped[str] = mapped_column(String(50), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(String(20), default="")
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

FILENAME = re.compile(r"^(?P<recipe>.+?)_(?P<day>\d{2}-\d{2}-\d{4})_(?P<time>\d{2}\.\d{2}\.\d{2})_(?P<serial>[^_]+)\.xlsx$", re.I)

def detect_result(file_path: Path) -> str:
    """Look for a pass/fail folder anywhere in the file's full path (covers the
    case where REPORTS_ROOT itself is one of those folders, e.g. D:\\pass)."""
    for part in file_path.resolve().parts:
        lowered = part.strip().lower()
        if lowered == "pass":
            return "Pass"
        if lowered == "fail":
            return "Fail"
    return "Unknown"

def hash_password(password: str) -> str:
    """Hash passwords with salted scrypt from Python's standard library."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(digest).decode())

def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, encoded_salt, encoded_digest = stored.split("$", 2)
        if algorithm != "scrypt": return False
        expected = base64.b64decode(encoded_digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(encoded_salt), n=2**14, r=8, p=1)
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def get_db():
    with SessionLocal() as db:
        yield db

def client_ip(request: Request) -> str | None:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None

def is_admin_network(request: Request) -> bool:
    """True only if this request's source IP is on the admin allow-list."""
    raw_ip = client_ip(request)
    if not raw_ip:
        return False
    try:
        addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    for entry in ADMIN_ALLOWED_HOSTS:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False

def scan_report_library() -> int:
    """Upsert reports below REPORTS_ROOT. Safe to call repeatedly or from Watchdog."""
    if not REPORTS_ROOT.is_dir():
        return 0
    scanned = 0
    with SessionLocal() as db:
        for file_path in REPORTS_ROOT.rglob("*.xlsx"):
            match = FILENAME.match(file_path.name)
            if not match:
                continue
            try:
                report_day = datetime.strptime(match["day"], "%d-%m-%Y").date()
                stat = file_path.stat()
            except (OSError, ValueError):
                continue
            full_path = str(file_path.resolve())
            report = db.scalar(select(Report).where(Report.path == full_path))
            state = "Generating" if report_day >= date.today() else "Completed"
            values = dict(filename=file_path.name, recipe=match["recipe"], report_date=report_day,
                          report_time=match["time"].replace(".", ":"), serial=match["serial"],
                          size_bytes=stat.st_size, status=state, result=detect_result(file_path),
                          last_seen=datetime.utcnow())
            if report:
                for key, value in values.items(): setattr(report, key, value)
            else:
                db.add(Report(path=full_path, **values))
            scanned += 1
        db.commit()
    return scanned

def seed_admin() -> None:
    with SessionLocal() as db:
        username = os.getenv("ADMIN_USERNAME", "admin")
        email = os.getenv("ADMIN_EMAIL", "admin@local").strip().lower()
        admin_user = db.scalar(select(User).where(User.username == username))
        if not admin_user:
            db.add(User(username=username, email=email, company="Suprajit", password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "ChangeMe123!")), role="ADMIN", status="APPROVED"))
            db.commit()
        elif admin_user.role == "ADMIN" and admin_user.email != email:
            email_owner = db.scalar(select(User).where(User.email == email))
            if not email_owner:
                admin_user.email = email
                db.commit()

class ReportFolderHandler(FileSystemEventHandler):
    def __init__(self): super().__init__(); self.last_run = 0.0
    def on_any_event(self, event):
        if event.is_directory or not str(event.src_path).lower().endswith(".xlsx"): return
        if time.monotonic() - self.last_run < 2: return
        self.last_run = time.monotonic(); scan_report_library()

def periodic_scan(stop: threading.Event):
    while not stop.wait(SCAN_INTERVAL): scan_report_library()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine); seed_admin(); scan_report_library()
    stop = threading.Event(); worker = threading.Thread(target=periodic_scan, args=(stop,), daemon=True); worker.start()
    observer = None
    if REPORTS_ROOT.is_dir():
        observer = Observer(); observer.schedule(ReportFolderHandler(), str(REPORTS_ROOT), recursive=True); observer.start()
    yield
    stop.set()
    if observer: observer.stop(); observer.join(timeout=3)

app = FastAPI(title="Suprajit", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET, https_only=False, same_site="lax")
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "app" / "templates")
templates.env.globals["today"] = date.today

@app.exception_handler(LoginRequired)
async def redirect_to_login(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)

def current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise LoginRequired()
    user = db.get(User, user_id)
    if not user or user.status != "APPROVED":
        request.session.clear()
        raise LoginRequired()
    return user

def render(request: Request, name: str, **context):
    """Compatibility wrapper for Starlette's request-first TemplateResponse API."""
    return templates.TemplateResponse(request=request, name=name, context=context)

@app.get("/")
def home(request: Request): return RedirectResponse("/dashboard" if request.session.get("user_id") else "/login", status_code=303)

@app.get("/login")
def login_page(request: Request): return render(request, "login.html")

@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        return render(request, "login.html", error="Invalid email address or password.")
    if user.status == "PENDING": return render(request, "login.html", error="Your account is waiting for administrator approval.")
    if user.status != "APPROVED": return render(request, "login.html", error="Your account is not permitted to log in.")
    request.session["user_id"] = user.id
    grant_admin = user.role == "ADMIN" and is_admin_network(request)
    return RedirectResponse("/admin" if grant_admin else "/dashboard", status_code=303)

@app.get("/request-access")
def access_page(request: Request): return render(request, "request_access.html")

@app.post("/request-access")
def request_access(request: Request, username: str = Form(...), email: str = Form(...), company: str = Form(""), password: str = Form(...), db: Session = Depends(get_db)):
    if db.scalar(select(User).where((User.username == username.strip()) | (User.email == email.strip().lower()))):
        return render(request, "request_access.html", error="That username or email is already registered.")
    db.add(User(username=username.strip(), email=email.strip().lower(), company=company.strip(), password_hash=hash_password(password), status="PENDING")); db.commit()
    return render(request, "request_access.html", success="Request received. An administrator must approve your access before you can log in.")

@app.post("/logout")
def logout(request: Request): request.session.clear(); return RedirectResponse("/login", status_code=303)

@app.get("/dashboard")
def dashboard(request: Request, recipe: str = "", report_date: str = "", serial: str = "", db: Session = Depends(get_db)):
    user = current_user(request, db)
    latest_available_date = date.today() - timedelta(days=1)
    selected_date = latest_available_date
    if report_date:
        try:
            requested_date = datetime.strptime(report_date, "%Y-%m-%d").date()
            if requested_date <= latest_available_date:
                selected_date = requested_date
        except ValueError:
            pass
    query = select(Report).where(Report.report_date == selected_date).order_by(Report.report_time.desc(), Report.serial.asc())
    if recipe: query = query.where(Report.recipe == recipe)
    if serial: query = query.where(Report.serial == serial.strip())
    reports = list(db.scalars(query.limit(100)))
    recipes = list(db.scalars(select(Report.recipe).where(Report.report_date <= latest_available_date).distinct().order_by(Report.recipe)))
    is_admin_here = user.role == "ADMIN" and is_admin_network(request)
    return render(
        request,
        "dashboard.html",
        user=user,
        reports=reports,
        recipes=recipes,
        filters={"recipe": recipe, "report_date": selected_date.isoformat(), "serial": serial.strip()},
        selected_date=selected_date,
        latest_available_date=latest_available_date,
        is_admin_here=is_admin_here,
    )

@app.get("/download/{report_id}")
def download(report_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db); report = db.get(Report, report_id)
    if not report: raise HTTPException(404, "Report not found")
    if report.report_date >= date.today(): raise HTTPException(403, "Today's reports cannot be downloaded.")
    file_path = Path(report.path)
    try: file_path.resolve().relative_to(REPORTS_ROOT.resolve())
    except ValueError: raise HTTPException(403, "Invalid report location")
    if not file_path.is_file(): raise HTTPException(404, "The source file is currently unavailable.")
    return FileResponse(file_path, filename=report.filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/admin")
def admin(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user.role != "ADMIN" or not is_admin_network(request):
        return RedirectResponse("/dashboard", status_code=303)
    users = list(db.scalars(select(User).where(User.role != "ADMIN").order_by(User.created_at.desc())))
    return render(request, "admin.html", user=user, users=users)

@app.post("/admin/users/{user_id}/{action}")
def change_user(user_id: int, action: str, request: Request, db: Session = Depends(get_db)):
    admin_user = current_user(request, db)
    if admin_user.role != "ADMIN" or not is_admin_network(request):
        raise HTTPException(403, "Administrator access is restricted to the approved machine/network.")
    target = db.get(User, user_id)
    if not target or target.role == "ADMIN": raise HTTPException(404)
    states = {"approve":"APPROVED", "reject":"REJECTED", "disable":"DISABLED"}
    if action not in states: raise HTTPException(400)
    target.status = states[action]; db.commit(); return RedirectResponse("/admin", status_code=303)
