from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.ui.routes import router as ui_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="NH3 Lifetime Monitor")

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

# UI
app.include_router(ui_router, prefix="/ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui")