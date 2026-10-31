"""Точка входа: запуск веб-приложения проката лыж.

Использование:
    python run.py            # http://127.0.0.1:8000
Документация API: http://127.0.0.1:8000/docs
"""
import uvicorn

from app.main import app  # noqa: F401

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
