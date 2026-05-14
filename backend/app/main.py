from fastapi import FastAPI

from app.api.routes_settings import router as settings_router
from app.memory.db import init_db
from app.trace.logger import write_log

app = FastAPI(
    title="Sity Backend",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    init_db()
    write_log(
        level="INFO",
        module="backend",
        event="startup",
        payload={"service": "sity-backend", "version": "0.1.0"},
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "sity-backend",
        "version": "0.1.0",
    }


app.include_router(settings_router)
