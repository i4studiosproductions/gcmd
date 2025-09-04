import os
import json
import logging
import asyncio
import secrets
import time
import signal
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, Cookie, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import uvicorn
import uuid
import threading

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("RCON-Server")

# Initialize FastAPI app
app = FastAPI(title="RCON Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create directories if they don't exist
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Configuration from environment variables
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PORT", 8000))
CLIENT_CONNECTION_KEY = os.getenv("CLIENT_CONNECTION_KEY", "default-connection-key")

# Session management
sessions = {}

# Store connected clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, dict] = {}
        self.connection_lock = asyncio.Lock()
        self.heartbeat_task = None

    async def connect(self, websocket: WebSocket, client_name: str):
        async with self.connection_lock:
            await websocket.accept()
            self.active_connections[client_name] = websocket
            self.client_info[client_name] = {
                "name": client_name,
                "connected_at": time.time(),
                "last_activity": time.time(),
                "last_command_result": None,
                "connection_count": self.client_info.get(client_name, {}).get("connection_count", 0) + 1
            }
            logger.info(f"Client connected: {client_name} (Total connections: {len(self.active_connections)})")

    def disconnect(self, client_name: str):
        async with self.connection_lock:
            if client_name in self.active_connections:
                del self.active_connections[client_name]
                logger.info(f"Client disconnected: {client_name} (Remaining connections: {len(self.active_connections)})")

    async def send_personal_message(self, message: dict, client_name: str):
        if client_name in self.active_connections:
            try:
                await self.active_connections[client_name].send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error sending message to {client_name}: {e}")
                self.disconnect(client_name)
                return False
        return False

    async def broadcast(self, message: dict):
        disconnected = []
        for client_name, connection in list(self.active_connections.items()):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_name}: {e}")
                disconnected.append(client_name)
        
        for client_name in disconnected:
            self.disconnect(client_name)

    def update_activity(self, client_name: str):
        if client_name in self.client_info:
            self.client_info[client_name]["last_activity"] = time.time()

    async def start_heartbeat(self):
        """Send periodic heartbeats to all clients"""
        while True:
            try:
                current_time = time.time()
                disconnected_clients = []
                
                for client_name, websocket in list(self.active_connections.items()):
                    try:
                        await websocket.send_json({
                            "type": "heartbeat",
                            "timestamp": current_time,
                            "server_time": current_time
                        })
                        # Update last activity time
                        if client_name in self.client_info:
                            self.client_info[client_name]["last_activity"] = current_time
                    except Exception as e:
                        logger.error(f"Error sending heartbeat to {client_name}: {e}")
                        disconnected_clients.append(client_name)
                
                # Remove disconnected clients
                for client_name in disconnected_clients:
                    self.disconnect(client_name)
                
                await asyncio.sleep(15)  # Send heartbeat every 15 seconds
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                await asyncio.sleep(5)

manager = ConnectionManager()

# Authentication functions
def authenticate_ui(session_id: str = Cookie(None)):
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return sessions[session_id]

# Models
class CommandRequest(BaseModel):
    command: str
    target: str = "all"

class LoginRequest(BaseModel):
    username: str
    password: str

# WebSocket endpoint for clients
@app.websocket("/ws/{client_name}")
async def websocket_endpoint(
    websocket: WebSocket, 
    client_name: str,
    key: str = Query(..., description="Connection key required for WebSocket connection")
):
    # Validate the connection key
    if not secrets.compare_digest(key, CLIENT_CONNECTION_KEY):
        await websocket.close(code=1008, reason="Invalid connection key")
        logger.warning(f"Client {client_name} attempted to connect with invalid key")
        return
    
    await manager.connect(websocket, client_name)
    
    try:
        while True:
            try:
                # Set timeout to prevent hanging
                data = await asyncio.wait_for(websocket.receive_text(), timeout=300.0)  # 5 minute timeout
                message = json.loads(data)
                manager.update_activity(client_name)
                
                if message["type"] == "command_result":
                    # Store command result in client info
                    if client_name in manager.client_info:
                        manager.client_info[client_name]["last_command_result"] = message["result"]
                        logger.info(f"Command result from {client_name}")
                elif message["type"] == "heartbeat_response":
                    # Update activity on heartbeat response
                    manager.update_activity(client_name)
                    
            except asyncio.TimeoutError:
                # Just continue, heartbeat will keep connection alive
                continue
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket error for {client_name}: {e}")
                # Don't break on error, try to continue
                await asyncio.sleep(1)
                
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        manager.disconnect(client_name)

# API endpoints
@app.get("/clients")
async def get_clients(username: str = Depends(authenticate_ui)):
    # Filter out clients that haven't been active recently
    current_time = time.time()
    active_clients = {}
    
    for client_name, info in manager.client_info.items():
        # Show client if active within last 5 minutes or currently connected
        if (current_time - info.get("last_activity", 0) < 300 or 
            client_name in manager.active_connections):
            active_clients[client_name] = info
    
    return active_clients

@app.post("/send-command")
async def send_command(request: CommandRequest, username: str = Depends(authenticate_ui)):
    command = request.command
    target = request.target
    
    if target == "all":
        # Send to all clients
        await manager.broadcast({
            "type": "command",
            "command": command,
            "from": username,
            "timestamp": time.time()
        })
        return {"status": "success", "message": f"Command sent to all clients: {command}"}
    else:
        # Send to specific client
        success = await manager.send_personal_message({
            "type": "command",
            "command": command,
            "from": username,
            "timestamp": time.time()
        }, target)
        
        if success:
            return {"status": "success", "message": f"Command sent to {target}: {command}"}
        else:
            return {"status": "error", "message": f"Client {target} not found or disconnected"}

@app.get("/server-status")
async def server_status():
    return {
        "status": "running",
        "uptime": time.time() - start_time,
        "connected_clients": len(manager.active_connections),
        "total_clients": len(manager.client_info)
    }

# Login endpoint
@app.post("/login")
async def login(response: Response, request: LoginRequest):
    correct_username = secrets.compare_digest(request.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(request.password, ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        return {"status": "error", "message": "Invalid credentials"}
    
    # Create session
    session_id = str(uuid.uuid4())
    sessions[session_id] = request.username
    
    # Set session cookie
    response.set_cookie(key="session_id", value=session_id, httponly=True, max_age=3600*24*30)  # 30 days
    return {"status": "success", "message": "Login successful"}

@app.post("/logout")
async def logout(response: Response, session_id: str = Cookie(None)):
    if session_id in sessions:
        del sessions[session_id]
    response.delete_cookie(key="session_id")
    return {"status": "success", "message": "Logout successful"}

# UI endpoints
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/admin", response_class=HTMLResponse)
async def admin_ui(request: Request, username: str = Depends(authenticate_ui)):
    return templates.TemplateResponse("index.html", {"request": request, "username": username})

# Global start time
start_time = time.time()

@app.on_event("startup")
async def startup_event():
    # Start heartbeat task
    asyncio.create_task(manager.start_heartbeat())
    logger.info("RCON Server started with heartbeat system")

# Signal handling for graceful shutdown
def handle_exit(signum, frame):
    logger.info("Received shutdown signal, but ignoring to keep server running")

# Ignore termination signals
signal.signal(signal.SIGTERM, handle_exit)
signal.signal(signal.SIGINT, handle_exit)

if __name__ == "__main__":
    # Run with increased timeout and keep-alive settings
    uvicorn.run(
        app, 
        host=SERVER_HOST, 
        port=SERVER_PORT,
        timeout_keep_alive=300,
        ws_ping_interval=20,
        ws_ping_timeout=30
    )
