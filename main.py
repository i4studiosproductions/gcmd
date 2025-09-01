from flask import Flask, request, jsonify
from threading import Lock
import time
import logging
import os
import subprocess
from typing import Dict, List, Optional

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Server configuration from environment variables
SERVER_KEY = os.environ.get("SERVER_KEY", "mysecretkey")
RECEIVER_TIMEOUT = int(os.environ.get("RECEIVER_TIMEOUT", "30"))
PORT = int(os.environ.get("PORT", "5000"))
HOST = os.environ.get("HOST", "0.0.0.0")

class ReceiverManager:
    def __init__(self):
        self.receivers: Dict[str, dict] = {}
        self.commands: Dict[str, List[dict]] = {}
        self.command_results: Dict[str, Dict[str, dict]] = {}
        self.lock = Lock()
    
    def register_receiver(self, name: str, ip: str) -> bool:
        with self.lock:
            current_time = time.time()
            
            if name in self.receivers:
                self.receivers[name]['last_seen'] = current_time
                self.receivers[name]['ip'] = ip
                logger.info(f"Receiver {name} updated from {ip}")
            else:
                self.receivers[name] = {
                    'last_seen': current_time,
                    'ip': ip,
                    'registered_at': current_time
                }
                self.commands[name] = []
                logger.info(f"New receiver {name} registered from {ip}")
            
            return True
    
    def get_online_receivers(self) -> List[str]:
        with self.lock:
            current_time = time.time()
            online = []
            
            for name, data in self.receivers.items():
                if current_time - data['last_seen'] < RECEIVER_TIMEOUT:
                    online.append(name)
                else:
                    if name in self.commands:
                        del self.commands[name]
                    if name in self.command_results:
                        del self.command_results[name]
            
            offline_receivers = [name for name, data in self.receivers.items() 
                               if current_time - data['last_seen'] >= RECEIVER_TIMEOUT]
            for name in offline_receivers:
                del self.receivers[name]
                if name in self.commands:
                    del self.commands[name]
                if name in self.command_results:
                    del self.command_results[name]
            
            return online
    
    def add_command(self, target: Optional[str], cmd: str, sender_ip: str) -> bool:
        with self.lock:
            current_time = time.time()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            
            if target:
                if target in self.receivers and current_time - self.receivers[target]['last_seen'] < RECEIVER_TIMEOUT:
                    self.commands[target].append({
                        'command': cmd,
                        'timestamp': timestamp,
                        'sender_ip': sender_ip
                    })
                    logger.info(f"Command '{cmd}' queued for {target} from {sender_ip}")
                    return True
                else:
                    logger.warning(f"Target {target} not found or offline")
                    return False
            else:
                online_receivers = self.get_online_receivers()
                for receiver in online_receivers:
                    self.commands[receiver].append({
                        'command': cmd,
                        'timestamp': timestamp,
                        'sender_ip': sender_ip
                    })
                logger.info(f"Command '{cmd}' broadcast to {len(online_receivers)} receivers from {sender_ip}")
                return True
    
    def get_commands(self, name: str, ip: str) -> List[str]:
        with self.lock:
            current_time = time.time()
            
            if name in self.receivers:
                self.receivers[name]['last_seen'] = current_time
                self.receivers[name]['ip'] = ip
            else:
                self.register_receiver(name, ip)
            
            if name in self.commands and self.commands[name]:
                commands = [f"{cmd['timestamp']} - {cmd['command']}" for cmd in self.commands[name]]
                self.commands[name] = []
                logger.info(f"Retrieved {len(commands)} commands for {name}")
                return commands
            return []
    
    def store_command_result(self, name: str, command: str, success: bool, output: str) -> None:
        with self.lock:
            if name not in self.command_results:
                self.command_results[name] = {}
            
            cmd_hash = str(hash(command))
            self.command_results[name][cmd_hash] = {
                'success': success,
                'output': output,
                'timestamp': time.time(),
                'command': command
            }
            
            current_time = time.time()
            for receiver in list(self.command_results.keys()):
                for cmd_hash in list(self.command_results[receiver].keys()):
                    if current_time - self.command_results[receiver][cmd_hash]['timestamp'] > 3600:
                        del self.command_results[receiver][cmd_hash]

    def get_command_result(self, name: str, command: str) -> Optional[dict]:
        with self.lock:
            cmd_hash = str(hash(command))
            if name in self.command_results and cmd_hash in self.command_results[name]:
                return self.command_results[name][cmd_hash]
            return None

# Global receiver manager
receiver_manager = ReceiverManager()

@app.route('/')
def home():
    return jsonify({"status": "online", "message": "Command relay server is running"})

@app.route('/register', methods=['POST'])
def register_receiver():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        name = data.get('name')
        ip = request.remote_addr
        
        if not name:
            return jsonify({"error": "Name is required"}), 400
        
        receiver_manager.register_receiver(name, ip)
        return jsonify({"status": "registered", "name": name})
    
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/who', methods=['POST'])
def list_receivers():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        key = data.get('key')
        if key != SERVER_KEY:
            return jsonify({"error": "Invalid key"}), 401
        
        receivers = receiver_manager.get_online_receivers()
        return jsonify({"receivers": receivers})
    
    except Exception as e:
        logger.error(f"Who error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/send', methods=['POST'])
def send_command():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        key = data.get('key')
        if key != SERVER_KEY:
            return jsonify({"error": "Invalid key"}), 401
        
        target = data.get('target')
        cmd = data.get('cmd')
        
        if not cmd:
            return jsonify({"error": "Command is required"}), 400
        
        success = receiver_manager.add_command(target, cmd, request.remote_addr)
        
        if success:
            return jsonify({"status": "sent", "target": target or "all"})
        else:
            return jsonify({"error": "Target not found or offline"}), 404
    
    except Exception as e:
        logger.error(f"Send error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/receive', methods=['POST'])
def receive_commands():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        name = data.get('name')
        if not name:
            return jsonify({"error": "Name is required"}), 400
        
        commands = receiver_manager.get_commands(name, request.remote_addr)
        
        executed_commands = []
        for cmd in commands:
            try:
                if " - " in cmd:
                    actual_cmd = cmd.split(" - ", 1)[1]
                else:
                    actual_cmd = cmd
                
                executed_commands.append(actual_cmd)
                
                result = subprocess.run(
                    actual_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                receiver_manager.store_command_result(
                    name, 
                    actual_cmd, 
                    result.returncode == 0,
                    result.stdout if result.returncode == 0 else result.stderr
                )
                
            except subprocess.TimeoutExpired:
                receiver_manager.store_command_result(
                    name, 
                    actual_cmd, 
                    False,
                    "Command timed out after 30 seconds"
                )
            except Exception as e:
                receiver_manager.store_command_result(
                    name, 
                    actual_cmd, 
                    False,
                    f"Command execution error: {str(e)}"
                )
        
        return jsonify({"commands": commands, "executed": executed_commands})
    
    except Exception as e:
        logger.error(f"Receive error: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/command_result', methods=['POST'])
def get_command_result():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        key = data.get('key')
        if key != SERVER_KEY:
            return jsonify({"error": "Invalid key"}), 401
        
        target = data.get('target')
        command = data.get('command')
        
        if not target or not command:
            return jsonify({"error": "Target and command are required"}), 400
        
        result = receiver_manager.get_command_result(target, command)
        
        if result:
            return jsonify({
                "status": "completed",
                "success": result['success'],
                "output": result['output']
            })
        else:
            return jsonify({"status": "pending"}), 202
    
    except Exception as e:
        logger.error(f"Command result error: {e}")
        return jsonify({"error": "Internal server error"}), 500

# This allows both python main.py and gunicorn main:app to work
if __name__ == '__main__':
    logger.info(f"Starting server on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT)
else:
    # This runs when imported by Gunicorn
    logger.info("Initializing application for Gunicorn")
