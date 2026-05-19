from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

from app.api.routes_captures import router as captures_router
from app.api.routes_chat import router as chat_router
from app.api.routes_debug import router as debug_router
from app.api.routes_events import router as events_router
from app.api.routes_settings import router as settings_router
from app.core.realtime_events import set_event_loop
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
async def on_startup():
    import asyncio
    set_event_loop(asyncio.get_running_loop())
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
app.include_router(debug_router)
app.include_router(chat_router)
app.include_router(captures_router)
app.include_router(events_router)
