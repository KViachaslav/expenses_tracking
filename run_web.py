"""Точка входа веб-интерфейса: `python run_web.py` (или `uvicorn app.web.routes:app`).

Хост и порт берутся из `WEB_HOST` / `WEB_PORT` (`.env`), см. README.md.
"""

from __future__ import annotations

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run(
        "app.web.routes:app",
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
