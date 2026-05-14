from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_settings import router as settings_router
from app.memory.db import init_db
from app.trace.logger import write_log

app = FastAPI(
    title="Sity Backend",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.1.133:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
