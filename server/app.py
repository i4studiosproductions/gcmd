import os
import json
import logging
import asyncio
import secrets
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

# Set up logging
logging.basicConfig(level=logging.INFO)
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

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Security
security = HTTPBasic()

# Configuration from environment variables
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PORT", 8000))
CLIENT_CONNECTION_KEY = os.getenv("CLIENT_CONNECTION_KEY", "default-connection-key")

# Store connected clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, client_name: str):
        await websocket.accept()
        self.active_connections[client_name] = websocket
        self.client_info[client_name] = {
            "name": client_name,
            "connected_at": asyncio.get_event_loop().time(),
            "last_command_result": None
        }
        logger.info(f"Client connected: {client_name}")

    def disconnect(self, client_name: str):
        if client_name in self.active_connections:
            del self.active_connections[client_name]
            if client_name in self.client_info:
                del self.client_info[client_name]
            logger.info(f"Client disconnected: {client_name}")

    async def send_personal_message(self, message: dict, client_name: str):
        if client_name in self.active_connections:
            try:
                await self.active_connections[client_name].send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_name}: {e}")
                self.disconnect(client_name)

    async def broadcast(self, message: dict):
        disconnected = []
        for client_name, connection in self.active_connections.items():
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_name}: {e}")
                disconnected.append(client_name)
        
        for client_name in disconnected:
            self.disconnect(client_name)

manager = ConnectionManager()

# Authentication
def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Models
class CommandRequest(BaseModel):
    command: str
    target: str = "all"

# WebSocket endpoint for clients - now requires connection key
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
            data = await websocket.receive_text()
            message = json.loads(data)
            if message["type"] == "command_result":
                # Store command result in client info
                if client_name in manager.client_info:
                    manager.client_info[client_name]["last_command_result"] = message["result"]
                    logger.info(f"Command result from {client_name}: {message['result']}")
    except WebSocketDisconnect:
        manager.disconnect(client_name)

# API endpoints
@app.get("/clients")
async def get_clients(username: str = Depends(authenticate)):
    return manager.client_info

@app.post("/send-command")
async def send_command(request: CommandRequest, username: str = Depends(authenticate)):
    command = request.command
    target = request.target
    
    if target == "all":
        # Send to all clients
        await manager.broadcast({
            "type": "command",
            "command": command,
            "from": username
        })
        return {"status": "success", "message": f"Command sent to all clients: {command}"}
    else:
        # Send to specific client
        if target in manager.active_connections:
            await manager.send_personal_message({
                "type": "command",
                "command": command,
                "from": username
            }, target)
            return {"status": "success", "message": f"Command sent to {target}: {command}"}
        else:
            return {"status": "error", "message": f"Client {target} not found"}

@app.get("/command-history/{client_name}")
async def get_command_history(client_name: str, username: str = Depends(authenticate)):
    if client_name in manager.client_info:
        return {"history": manager.client_info[client_name].get("last_command_result")}
    return {"history": None}

# UI endpoints
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, username: str = Depends(authenticate)):
    return templates.TemplateResponse("index.html", {"request": request, "username": username})

@app.get("/admin", response_class=HTMLResponse)
async def admin_ui(request: Request, username: str = Depends(authenticate)):
    return templates.TemplateResponse("index.html", {"request": request, "username": username})

if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
