from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from korni_bot.admin_web.routes import router

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def register_admin(app: FastAPI) -> None:
    if STATIC_DIR.exists():
        app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="admin_static")
    app.include_router(router, prefix="/admin")
    app.state.templates = templates
