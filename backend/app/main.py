# app/main.py
# Entry point: uvicorn app.main:app --reload
# SHARED FILE: edit ONLY your own "slot" lines, never anyone else's.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import check_connection
from app.audit.middleware import AuditMiddleware

# ---- router imports ----
from app.admin.router import router as admin_router

# [slot: vendor import]

# [slot: auction import]
from app.auction.router import router as auction_router

# [slot: audit import]
from app.audit.router import router as audit_router

app = FastAPI(title="Smart Tender System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite (React) dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

# ---- router registration ----
app.include_router(admin_router)

# [slot: vendor router]

app.include_router(auction_router)

# [slot: audit router]
app.include_router(audit_router)


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/db-check")
def db_check():
    try:
        return {"database": "connected" if check_connection() else "unexpected result"}
    except Exception as e:
        return {"database": "error", "detail": str(e)}
