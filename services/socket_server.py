import asyncio
import json
import os

import redis.asyncio as redis
import socketio
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# --------------------------
# Environment Variables
# --------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379")
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "current_metal_prices")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))

# --------------------------
# FastAPI & Socket.IO Setup
# --------------------------
app = FastAPI()
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
socket_app = socketio.ASGIApp(sio, app)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# Redis Client Setup
# --------------------------
# Create an asynchronous Redis client with automatic decoding.
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


# --------------------------
# Redis Listener
# --------------------------
async def redis_listener():
    """Listen to Redis Pub/Sub and emit updates via Socket.IO"""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(REDIS_CHANNEL)

    # Listen indefinitely for messages on the channel.
    async for message in pubsub.listen():
        if message.get("type") == "message":
            data = json.loads(message["data"])
            await sio.emit("get_metals_live_price", data)


# --------------------------
# Socket.IO Event Handlers
# --------------------------
@sio.on("connect")
async def connect(sid, environ):
    """Handle new client connections."""
    await redis_client.sadd("connected_clients", sid)
    await sio.emit("hello", {"message": "Hello from server!"}, room=sid)


@sio.on("disconnect")
async def disconnect(sid):
    """Handle client disconnections."""
    await redis_client.srem("connected_clients", sid)


# --------------------------
# FastAPI Startup & Shutdown Events
# --------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(redis_listener())


@app.on_event("shutdown")
async def shutdown_event():
    # Close the Redis client gracefully on shutdown.
    await redis_client.close()


# --------------------------
# Run the ASGI Application
# --------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(socket_app, host=HOST, port=PORT)
