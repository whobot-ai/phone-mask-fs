from contextlib import asynccontextmanager
from fastapi import FastAPI
from .database import startup, shutdown
from .main import app

@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield
    await shutdown()

app.router.lifespan_context = lifespan
