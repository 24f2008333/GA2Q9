from fastapi import FastAPI, Header, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uuid
import time
import base64

app = FastAPI()

# ----------------------------
# Configuration
# ----------------------------
TOTAL_ORDERS = 50
RATE_LIMIT = 20
WINDOW = 10  # seconds

# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# In-memory storage
# ----------------------------
idempotency_store = {}
rate_buckets = {}

# ----------------------------
# Models
# ----------------------------
class OrderCreate(BaseModel):
    item: Optional[str] = None
    quantity: Optional[int] = 1

# ----------------------------
# Cursor helpers
# ----------------------------
def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()

def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    return int(base64.urlsafe_b64decode(cursor.encode()).decode())

# ----------------------------
# Rate Limiting Middleware
# ----------------------------
@app.middleware("http")
async def rate_limit(request: Request, call_next):

    # Allow CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()

    bucket = rate_buckets.setdefault(client, [])

    # Remove expired timestamps
    bucket[:] = [t for t in bucket if now - t < WINDOW]

    if len(bucket) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - bucket[0])))
        response = Response(status_code=429)
        response.headers["Retry-After"] = str(retry)
        return response

    bucket.append(now)

    return await call_next(request)

# ----------------------------
# Root
# ----------------------------
@app.get("/")
def root():
    return {"status": "ok"}

# ----------------------------
# Idempotent Order Creation
# ----------------------------
@app.post("/orders", status_code=201)
def create_order(
    body: OrderCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4()),
        "item": body.item,
        "quantity": body.quantity,
    }

    idempotency_store[idempotency_key] = order

    return order

# ----------------------------
# Cursor Pagination
# ----------------------------
@app.get("/orders")
def get_orders(limit: int = 10, cursor: Optional[str] = None):

    if limit < 1:
        limit = 1

    start = decode_cursor(cursor)

    end = min(start + limit, TOTAL_ORDERS)

    items = [{"id": i} for i in range(start + 1, end + 1)]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor
    }
