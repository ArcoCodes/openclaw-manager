import logging
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from app.config import settings  # noqa: E402
from app.dependencies import renewal_scheduler  # noqa: E402
from app.routers import cron, health, routes, sandbox, webhook  # noqa: E402

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    renewal_scheduler.start()
    yield
    renewal_scheduler.stop()


app = FastAPI(
    title="openclaw-manager",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(sandbox.router)
app.include_router(routes.router)
app.include_router(webhook.router)
app.include_router(cron.router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.http_port, reload=True)
