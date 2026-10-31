"""Основное приложение: веб-интерфейсы (пользователь, сотрудник, админ)."""
import os
from datetime import datetime, date

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import (verify_password, hash_password, create_session,
                      destroy_session, get_session, require_role)
from app.database import get_db, init_db
from app.api import admin_router, employee_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Прокат лыж", version="1.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app.include_router(admin_router)
app.include_router(employee_router)


@app.on_event("startup")
def startup():
    init_db()


def ctx(request: Request, **extra):
    """Общий контекст для шаблонов."""
    session = get_session(request)
    data = {"request": request, "session": session}
    data.update(extra)
    return data


def render(request: Request, template_name: str, status_code: int = 200, **context):
    """Рендер шаблона в формате, совместимом со Starlette >= 0.36
    (new-style: name первым, request отдельным параметром)."""
    return templates.TemplateResponse(request, template_name,
                                      ctx(request, **context), status_code=status_code)


# ==================== ГЛАВНАЯ / РЕГИСТРАЦИЯ / ВХОД ====================


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with get_db() as db:
        items = db.execute(
            "SELECT * FROM equipment WHERE status='ok' ORDER BY type, size").fetchall()
    return render(request, "index.html", items=[dict(i) for i in items])


@app.post("/register")
def register(request: Request, username: str = Form(...), password: str = Form(...),
             full_name: str = Form(""), phone: str = Form("")):
    error = None
    if len(username) < 3 or len(password) < 4:
        error = "Имя пользователя — минимум 3 символа, пароль — минимум 4."
    else:
        with get_db() as db:
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                error = "Пользователь с таким именем уже существует."
            else:
                db.execute(
                    "INSERT INTO users (username, password_hash, full_name, phone, role)"
                    " VALUES (?, ?, ?, ?, 'user')",
                    (username, hash_password(password), full_name, phone))
                error = ""
    if error:
        return render(request, "register.html", status_code=400, error=error)
    return RedirectResponse("/login?registered=1", status_code=302)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "register.html", error=None)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return render(request, "login.html", status_code=401,
                      error="Неверный логин или пароль")
    token = create_session({"user_id": user["id"], "username": user["username"],
                            "role": user["role"], "full_name": user["full_name"]})
    resp = RedirectResponse(get_home_by_role(user["role"]), status_code=302)
    resp.set_cookie("session_token", token, httponly=True, samesite="lax")
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, registered: int = 0):
    msg = "Регистрация успешна. Войдите в систему." if registered else None
    return render(request, "login.html", error=None, success=msg)


@app.get("/logout")
def logout(request: Request):
    destroy_session(request.cookies.get("session_token"))
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie("session_token")
    return resp


def get_home_by_role(role: str) -> str:
    return {"admin": "/admin", "employee": "/employee"}.get(role, "/cabinet")


# ==================== ЛИЧНЫЙ КАБИНЕТ ПОЛЬЗОВАТЕЛЯ ====================


@app.get("/cabinet", response_class=HTMLResponse)
def cabinet(request: Request):
    try:
        session = require_role(request, "user", "admin", "employee")
    except Exception:
        return RedirectResponse("/login", status_code=302)
    with get_db() as db:
        rows = db.execute(
            "SELECT b.*, e.name AS equipment_name FROM bookings b "
            "LEFT JOIN equipment e ON e.id=b.equipment_id "
            "WHERE b.user_id=? ORDER BY b.date DESC, b.start_time",
            (session["user_id"],)).fetchall()
    return render(request, "cabinet.html", bookings=[dict(r) for r in rows])


@app.post("/cabinet/book")
def book(request: Request, equipment_id: int = Form(...), booking_date: str = Form(...),
         start_time: str = Form(...), duration_hours: int = Form(1)):
    try:
        session = require_role(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)

    error = None
    try:
        date.fromisoformat(booking_date)
    except ValueError:
        error = "Некорректная дата."

    if not error:
        with get_db() as db:
            eq = db.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
            if not eq or eq["status"] != "ok":
                error = "Инвентарь недоступен."
            elif db.execute(
                    "SELECT 1 FROM bookings WHERE equipment_id=? AND date=? AND start_time=?",
                    (equipment_id, booking_date, start_time)).fetchone():
                error = "Выбранный инвентарь уже занят на это время."
            else:
                db.execute(
                    "INSERT INTO bookings (user_id, equipment_id, date, start_time,"
                    " duration_hours, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                    (session["user_id"], equipment_id, booking_date, start_time,
                     duration_hours, datetime.now().isoformat(timespec="seconds")))
    if error:
        with get_db() as db:
            items = [dict(i) for i in db.execute(
                "SELECT * FROM equipment WHERE status='ok' ORDER BY type").fetchall()]
        return render(request, "book.html", status_code=400, items=items, error=error)
    return RedirectResponse("/cabinet?booked=1", status_code=302)


@app.get("/cabinet/book", response_class=HTMLResponse)
def book_page(request: Request):
    try:
        require_role(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    with get_db() as db:
        items = [dict(i) for i in db.execute(
            "SELECT * FROM equipment WHERE status='ok' ORDER BY type, size").fetchall()]
    return render(request, "book.html", items=items, error=None)


@app.post("/cabinet/bookings/{booking_id}/change")
def change_booking(booking_id: int, request: Request, booking_date: str = Form(...),
                   start_time: str = Form(...), duration_hours: int = Form(1),
                   equipment_id: int = Form(...)):
    """Пользователь меняет время проката своей активной брони."""
    try:
        session = require_role(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)

    error = None
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=? AND user_id=?",
                             (booking_id, session["user_id"])).fetchone()
        if not booking:
            return JSONResponse({"detail": "Бронирование не найдено"}, status_code=404)
        if booking["status"] != "active":
            error = "Изменять можно только активные бронирования."
        else:
            eq = db.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
            if not eq or eq["status"] != "ok":
                error = "Инвентарь недоступен."
            elif db.execute(
                    "SELECT 1 FROM bookings WHERE equipment_id=? AND date=? AND start_time=? AND id!=?",
                    (equipment_id, booking_date, start_time, booking_id)).fetchone():
                error = "Инвентарь занят на выбранное время."
            else:
                db.execute(
                    "UPDATE bookings SET date=?, start_time=?, duration_hours=?, equipment_id=?"
                    " WHERE id=?",
                    (booking_date, start_time, duration_hours, equipment_id, booking_id))
    if error:
        return RedirectResponse(f"/cabinet/edit/{booking_id}?error=1", status_code=302)
    return RedirectResponse("/cabinet?changed=1", status_code=302)


@app.get("/cabinet/edit/{booking_id}", response_class=HTMLResponse)
def edit_booking_page(booking_id: int, request: Request, error: int = 0):
    try:
        session = require_role(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    with get_db() as db:
        booking = db.execute(
            "SELECT b.*, e.name AS equipment_name FROM bookings b "
            "LEFT JOIN equipment e ON e.id=b.equipment_id "
            "WHERE b.id=? AND b.user_id=?", (booking_id, session["user_id"])).fetchone()
        if not booking:
            return RedirectResponse("/cabinet", status_code=302)
        items = [dict(i) for i in db.execute(
            "SELECT * FROM equipment WHERE status='ok' ORDER BY type, size").fetchall()]
    return render(request, "edit_booking.html", booking=dict(booking), items=items,
                  error="Не удалось изменить бронь: инвентарь занят или недоступен." if error else None)


@app.post("/cabinet/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, request: Request):
    try:
        session = require_role(request)
    except Exception:
        return RedirectResponse("/login", status_code=302)
    with get_db() as db:
        db.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND user_id=?",
                   (booking_id, session["user_id"]))
    return RedirectResponse("/cabinet", status_code=302)


# ==================== ИНТЕРФЕЙС СОТРУДНИКА ====================


@app.get("/employee", response_class=HTMLResponse)
def employee_panel(request: Request, day: str | None = None):
    try:
        require_role(request, "employee", "admin")
    except Exception:
        return RedirectResponse("/login", status_code=302)
    day = day or date.today().isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT b.*, u.username, u.full_name, u.phone, e.name AS equipment_name "
            "FROM bookings b JOIN users u ON u.id=b.user_id "
            "LEFT JOIN equipment e ON e.id=b.equipment_id "
            "WHERE b.date=? ORDER BY b.start_time", (day,)).fetchall()
    return render(request, "employee.html", day=day, bookings=[dict(r) for r in rows])


# ==================== ИНТЕРФЕЙС АДМИНИСТРАТОРА ====================


@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    try:
        require_role(request, "admin")
    except Exception:
        return RedirectResponse("/login", status_code=302)
    with get_db() as db:
        users = [dict(r) for r in db.execute(
            "SELECT id, username, full_name, phone, role FROM users ORDER BY id").fetchall()]
        equipment = [dict(r) for r in db.execute(
            "SELECT * FROM equipment ORDER BY id").fetchall()]
    return render(request, "admin.html", users=users, equipment=equipment)


@app.exception_handler(403)
def forbidden_handler(request: Request, exc):
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": str(exc.detail)}, status_code=403)
    return RedirectResponse("/login", status_code=302)
