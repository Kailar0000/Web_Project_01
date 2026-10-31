"""API-модули для интерфейсов администратора и сотрудника."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_role
from app.database import get_db

# ==================== СХЕМЫ ====================


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=4)
    full_name: str = ""
    phone: str = ""
    role: str = Field(default="user", pattern="^(user|employee|admin)$")


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role: str | None = Field(default=None, pattern="^(user|employee|admin)$")
    password: str | None = None


class EquipmentCreate(BaseModel):
    name: str
    type: str = "ski"
    size: str = ""
    status: str = Field(default="ok", pattern="^(ok|maintenance)$")


class EquipmentUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    size: str | None = None
    status: str | None = Field(default=None, pattern="^(ok|maintenance)$")


class BookingChange(BaseModel):
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    duration_hours: int | None = Field(default=None, ge=1, le=8)
    equipment_id: int | None = None
    status: str | None = Field(default=None, pattern="^(active|done|cancelled)$")


# ==================== API АДМИНИСТРАТОРА ====================

admin_router = APIRouter(prefix="/api/admin", tags=["Admin API"])


@admin_router.get("/users")
def admin_list_users(request: Request):
    require_role(request, "admin")
    with get_db() as db:
        rows = db.execute(
            "SELECT id, username, full_name, phone, role FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


@admin_router.post("/users", status_code=201)
def admin_create_user(data: UserCreate, request: Request):
    require_role(request, "admin")
    from app.auth import hash_password

    with get_db() as db:
        exists = db.execute("SELECT 1 FROM users WHERE username=?",
                            (data.username,)).fetchone()
        if exists:
            raise HTTPException(400, "Пользователь с таким именем уже существует")
        cur = db.execute(
            "INSERT INTO users (username, password_hash, full_name, phone, role)"
            " VALUES (?, ?, ?, ?, ?)",
            (data.username, hash_password(data.password), data.full_name,
             data.phone, data.role),
        )
    return {"id": cur.lastrowid}


@admin_router.put("/users/{user_id}")
def admin_update_user(user_id: int, data: UserUpdate, request: Request):
    require_role(request, "admin")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "Пользователь не найден")
        if data.full_name is not None:
            db.execute("UPDATE users SET full_name=? WHERE id=?", (data.full_name, user_id))
        if data.phone is not None:
            db.execute("UPDATE users SET phone=? WHERE id=?", (data.phone, user_id))
        if data.role is not None:
            db.execute("UPDATE users SET role=? WHERE id=?", (data.role, user_id))
        if data.password:
            from app.auth import hash_password
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_password(data.password), user_id))
    return {"ok": True}


@admin_router.delete("/users/{user_id}")
def admin_delete_user(user_id: int, request: Request):
    session = require_role(request, "admin")
    if session["user_id"] == user_id:
        raise HTTPException(400, "Нельзя удалить собственный аккаунт")
    with get_db() as db:
        db.execute("DELETE FROM bookings WHERE user_id=?", (user_id,))
        cur = db.execute("DELETE FROM users WHERE id=?", (user_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Пользователь не найден")
    return {"ok": True}


@admin_router.get("/equipment")
def admin_list_equipment(request: Request):
    require_role(request, "admin", "employee")
    with get_db() as db:
        rows = db.execute("SELECT * FROM equipment ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@admin_router.post("/equipment", status_code=201)
def admin_create_equipment(data: EquipmentCreate, request: Request):
    require_role(request, "admin")
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO equipment (name, type, size, status) VALUES (?, ?, ?, ?)",
            (data.name, data.type, data.size, data.status),
        )
    return {"id": cur.lastrowid}


@admin_router.put("/equipment/{eq_id}")
def admin_update_equipment(eq_id: int, data: EquipmentUpdate, request: Request):
    require_role(request, "admin")
    with get_db() as db:
        fields, values = [], []
        for k, v in data.model_dump(exclude_none=True).items():
            fields.append(f"{k}=?")
            values.append(v)
        if not fields:
            raise HTTPException(400, "Нет данных для обновления")
        values.append(eq_id)
        cur = db.execute(f"UPDATE equipment SET {', '.join(fields)} WHERE id=?", values)
        if cur.rowcount == 0:
            raise HTTPException(404, "Единица инвентаря не найдена")
    return {"ok": True}


@admin_router.delete("/equipment/{eq_id}")
def admin_delete_equipment(eq_id: int, request: Request):
    require_role(request, "admin")
    with get_db() as db:
        busy = db.execute(
            "SELECT 1 FROM bookings WHERE equipment_id=? AND status='active'",
            (eq_id,)).fetchone()
        if busy:
            raise HTTPException(400, "Инвентарь занят, удаление невозможно")
        cur = db.execute("DELETE FROM equipment WHERE id=?", (eq_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Единица инвентаря не найдена")
    return {"ok": True}


@admin_router.get("/stats")
def admin_stats(request: Request):
    require_role(request, "admin")
    with get_db() as db:
        users = db.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()["c"]
        bookings = db.execute("SELECT COUNT(*) c FROM bookings").fetchone()["c"]
        active = db.execute("SELECT COUNT(*) c FROM bookings WHERE status='active'").fetchone()["c"]
        equipment = db.execute("SELECT COUNT(*) c FROM equipment").fetchone()["c"]
    return {"users": users, "bookings": bookings, "active_bookings": active,
            "equipment": equipment}


# ==================== API СОТРУДНИКА ====================

employee_router = APIRouter(prefix="/api/employee", tags=["Employee API"])


@employee_router.get("/bookings")
def employee_list_bookings(request: Request, date: str | None = None,
                           status_filter: str | None = None):
    require_role(request, "employee", "admin")
    query = (
        "SELECT b.*, u.username, u.full_name, u.phone, e.name AS equipment_name "
        "FROM bookings b JOIN users u ON u.id=b.user_id "
        "LEFT JOIN equipment e ON e.id=b.equipment_id "
    )
    conds, params = [], []
    if date:
        conds.append("b.date=?")
        params.append(date)
    st = request.query_params.get("status")
    if st:
        conds.append("b.status=?")
        params.append(st)
    if conds:
        query += "WHERE " + " AND ".join(conds) + " "
    query += "ORDER BY b.date DESC, b.start_time"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@employee_router.put("/bookings/{booking_id}")
def employee_update_booking(booking_id: int, data: BookingChange, request: Request):
    """Сотрудник может менять время/инвентарь/статус любой брони."""
    require_role(request, "employee", "admin")
    with get_db() as db:
        booking = db.execute("SELECT * FROM bookings WHERE id=?",
                             (booking_id,)).fetchone()
        if not booking:
            raise HTTPException(404, "Бронирование не найдено")

        new_date = data.date or booking["date"]
        new_time = data.start_time or booking["start_time"]
        new_dur = data.duration_hours or booking["duration_hours"]
        new_eq = data.equipment_id if data.equipment_id is not None else booking["equipment_id"]

        if new_eq is not None:
            eq = db.execute("SELECT * FROM equipment WHERE id=?", (new_eq,)).fetchone()
            if not eq:
                raise HTTPException(404, "Инвентарь не найден")
            if eq["status"] != "ok":
                raise HTTPException(400, f"Инвентарь «{eq['name']}» на обслуживании")
            conflict = db.execute(
                "SELECT 1 FROM bookings WHERE equipment_id=? AND date=? AND start_time=? AND id!=?",
                (new_eq, new_date, new_time, booking_id)).fetchone()
            if conflict:
                raise HTTPException(409, "Этот инвентарь уже забронирован на выбранное время")

        db.execute(
            "UPDATE bookings SET date=?, start_time=?, duration_hours=?, equipment_id=?, status=?"
            " WHERE id=?",
            (new_date, new_time, new_dur, new_eq,
             data.status or booking["status"], booking_id),
        )
    return {"ok": True}


@employee_router.post("/bookings/{booking_id}/complete")
def employee_complete_booking(booking_id: int, request: Request):
    require_role(request, "employee", "admin")
    with get_db() as db:
        cur = db.execute("UPDATE bookings SET status='done' WHERE id=?", (booking_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Бронирование не найдено")
    return {"ok": True}


@employee_router.get("/free-equipment")
def employee_free_equipment(request: Request, date: str, start_time: str):
    """Свободный инвентарь на указанную дату и время."""
    require_role(request, "employee", "admin")
    with get_db() as db:
        rows = db.execute(
            "SELECT e.* FROM equipment e WHERE e.status='ok' AND e.id NOT IN ("
            "  SELECT equipment_id FROM bookings WHERE date=? AND start_time=? AND status='active')"
            " ORDER BY e.id",
            (date, start_time),
        ).fetchall()
    return [dict(r) for r in rows]
