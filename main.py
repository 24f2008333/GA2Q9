from fastapi import FastAPI, Header, HTTPException, Response
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# In-memory stores
# ----------------------------
idempotency_store = {}
rate_buckets = {}


class OrderCreate(BaseModel):
    item: Optional[str] = None
    quantity: Optional[int] = 1


def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@app.middleware("http")
async def rate_limit(request, call_next):
    client = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()

    bucket = rate_buckets.setdefault(client, [])

    bucket[:] = [t for t in bucket if now - t < WINDOW]

    if len(bucket) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - bucket[0])))
        return Response(
            status_code=429,
            headers={"Retry-After": str(retry)},
        )

    bucket.append(now)
    return await call_next(request)


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


@app.get("/orders")
def list_orders(limit: int = 10, cursor: Optional[str] = None):
    start = decode_cursor(cursor)

    if start >= TOTAL_ORDERS:
        return {
            "items": [],
            "next_cursor": None,
        }

    end = min(start + limit, TOTAL_ORDERS)

    items = [{"id": i} for i in range(start + 1, end + 1)]

    next_cursor = encode_cursor(end) if end < TOTAL_ORDERS else None

    return {
        "items": items,
        "next_cursor": next_cursor,
    }
