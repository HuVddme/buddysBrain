import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import resources, search, passage_admin, ingestion

app = FastAPI()


@app.get("/health")
def health():
    # Liveness only; do not claim database or AI readiness or expose credentials.
    return {"status": "ok"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-Error-Code"],
)

# Include routes
app.include_router(resources.router)
app.include_router(search.router)
app.include_router(passage_admin.router)
app.include_router(ingestion.router)
app.include_router(ingestion.admin_router)
