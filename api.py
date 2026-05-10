import asyncio
import logging
from typing import Dict, Any, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import our operator core
from main import AntigravityOperator
from configs.settings import LOGS_DIR

app = FastAPI(title="Antigravity Control Plane API")

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Types ──────────────────────────────────────────────────────────────────
class GoalRequest(BaseModel):
    goal: str

# ─── State Management ────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        """Send JSON data to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                pass

manager = ConnectionManager()
active_operator = None
is_running = False
main_loop = None # Will be set on startup

# ─── Custom Logger for WebSocket Streaming ──────────────────────────────────
class WebSocketLogHandler(logging.Handler):
    def __init__(self, manager: ConnectionManager):
        super().__init__()
        self.manager = manager

    def emit(self, record):
        if main_loop is None: return
        try:
            msg = self.format(record)
            payload = {"type": "log", "content": msg, "level": record.levelname}
            asyncio.run_coroutine_threadsafe(self.manager.broadcast(payload), main_loop)
        except Exception:
            self.handleError(record)

# Setup root logger
ws_handler = WebSocketLogHandler(manager)
ws_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
ws_handler.setFormatter(formatter)
logging.getLogger("antigravity").addHandler(ws_handler)

# ─── API Routes ──────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()

@app.post("/api/start")
async def start_operator(request: GoalRequest, background_tasks: BackgroundTasks):
    global active_operator, is_running
    if is_running:
        return {"status": "error", "message": "An operator is already running."}
    
    def _run_operator():
        global is_running, active_operator
        is_running = True
        try:
            # Broadcast status change
            if main_loop:
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": "status", "content": "Initializing..."}), 
                    main_loop
                )
            
            def broadcast_metadata(data):
                if main_loop:
                    asyncio.run_coroutine_threadsafe(manager.broadcast(data), main_loop)

            active_operator = AntigravityOperator(on_metadata=broadcast_metadata)
            active_operator.run(request.goal)
            
        except Exception as e:
            logging.getLogger("antigravity").error(f"Operator crashed: {e}")
        finally:
            is_running = False
            if main_loop:
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": "status", "content": "Idle"}), 
                    main_loop
                )

    background_tasks.add_task(_run_operator)
    return {"status": "started", "goal": request.goal}

@app.post("/api/stop")
async def stop_operator():
    global is_running
    if not is_running:
        return {"status": "error", "message": "No operator is running."}
    
    # Force kill for now (we'll make it cleaner later)
    # Since it's in a background thread, we might need a flag in AntigravityOperator
    return {"status": "stopping", "message": "Stop command sent (Note: hard stop not yet fully implemented in core loop)"}

@app.get("/api/status")
async def get_status():
    return {"is_running": is_running}

@app.get("/api/config")
async def get_config():
    from configs.settings import USE_DOCKER_SANDBOX
    return {"use_sandbox": USE_DOCKER_SANDBOX}

@app.post("/api/config/toggle-sandbox")
async def toggle_sandbox():
    from configs.settings import USE_DOCKER_SANDBOX, SETTINGS_PATH
    from utils.config_manager import update_setting
    new_val = not USE_DOCKER_SANDBOX
    update_setting(SETTINGS_PATH, "USE_DOCKER_SANDBOX", new_val)
    return {"status": "success", "new_value": new_val, "message": "Settings updated. Server will reload."}

@app.get("/api/files")
async def get_files():
    from tools.project_scanner import ProjectScanner
    from configs.settings import PROJECT_ROOT
    scanner = ProjectScanner(str(PROJECT_ROOT / "workspace"))
    tree = scanner.scan_json()
    return {"tree": tree}

@app.get("/api/files/content")
async def get_file_content(path: str):
    from tools.file_tool import FileTool
    from configs.settings import PROJECT_ROOT
    tool = FileTool(base_dir=str(PROJECT_ROOT / "workspace"))
    res = tool.read(path)
    if res.success:
        return {"content": res.content}
    else:
        return {"error": res.message}

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
