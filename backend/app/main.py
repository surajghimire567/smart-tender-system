# app/main.py
# Entry point: uvicorn app.main:app --reload
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import check_connection
from app.auction.router import router as auction_router

app = FastAPI(title="Smart Tender System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite (React) dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auction_router)


@app.get("/")
def health():
    return {"status": "ok", "module": "auction-engine"}


@app.get("/db-check")
def db_check():
    try:
        return {"database": "connected" if check_connection() else "unexpected result"}
    except Exception as e:
        return {"database": "error", "detail": str(e)}