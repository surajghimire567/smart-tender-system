# app/main.py
# Entry point: uvicorn app.main:app --reload
# SHARED FILE: edit ONLY your own "slot" lines, never anyone else's.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import check_connection

# ---- router imports ----
# [slot: admin import]

# [slot: vendor import]

# [slot: auction import]

# [slot: audit import]

app = FastAPI(title="Smart Tender System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite (React) dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- router registration ----
# [slot: admin router]

# [slot: vendor router]

# [slot: auction router]

# [slot: audit router]


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/db-check")
def db_check():
    try:
        return {"database": "connected" if check_connection() else "unexpected result"}
    except Exception as e:
        return {"database": "error", "detail": str(e)}