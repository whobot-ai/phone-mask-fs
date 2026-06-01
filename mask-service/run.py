"""
启动入口
开发：python run.py
生产：uvicorn run:app --host 0.0.0.0 --port 8080 --workers 4
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.database import startup, shutdown
from app.main import app


@asynccontextmanager
async def lifespan(application: FastAPI):
    await startup()
    yield
    await shutdown()


app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run:app", host="0.0.0.0", port=8080, reload=True)
