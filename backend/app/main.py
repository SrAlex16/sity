from fastapi import FastAPI

app = FastAPI(
    title="Sity Backend",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "sity-backend",
        "version": "0.1.0",
    }
