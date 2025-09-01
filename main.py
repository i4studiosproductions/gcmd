# Add these imports
import subprocess
import shlex

# Add this class attribute to ReceiverManager
self.command_results: Dict[str, Dict[str, dict]] = {}  # receiver_name -> {command_hash: result}

# Add this method to ReceiverManager
def store_command_result(self, name: str, command: str, success: bool, output: str) -> None:
    """Store the result of a command execution"""
    with self.lock:
        if name not in self.command_results:
            self.command_results[name] = {}
        
        # Create a hash of the command for identification
        cmd_hash = str(hash(command))
        self.command_results[name][cmd_hash] = {
            'success': success,
            'output': output,
            'timestamp': time.time()
        }
        
        # Clean up old results (older than 1 hour)
        for receiver in list(self.command_results.keys()):
            for cmd_hash in list(self.command_results[receiver].keys()):
                if time.time() - self.command_results[receiver][cmd_hash]['timestamp'] > 3600:
                    del self.command_results[receiver][cmd_hash]

def get_command_result(self, name: str, command: str) -> Optional[dict]:
    """Get the result of a command execution"""
    with self.lock:
        cmd_hash = str(hash(command))
        if name in self.command_results and cmd_hash in self.command_results[name]:
            return self.command_results[name][cmd_hash]
        return None

# Add this endpoint to your Flask app
@app.route('/command_result', methods=['POST'])
def get_command_result():
    """Endpoint to get command execution results"""
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
                "status": "completed" if result['success'] else "failed",
                "output": result['output']
            })
        else:
            return jsonify({"status": "pending"}), 202
    
    except Exception as e:
        logger.error(f"Command result error: {e}")
        return jsonify({"error": "Internal server error"}), 500

# Update the receive_commands endpoint to execute commands and store results
@app.route('/receive', methods=['POST'])
def receive_commands():
    """Endpoint for receivers to get their commands and return results"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        name = data.get('name')
        if not name:
            return jsonify({"error": "Name is required"}), 400
        
        # Get commands for this receiver
        commands = receiver_manager.get_commands(name, request.remote_addr)
        
        # Execute commands and store results
        for cmd in commands:
            try:
                # Extract the actual command (remove timestamp)
                if " - " in cmd:
                    actual_cmd = cmd.split(" - ", 1)[1]
                else:
                    actual_cmd = cmd
                
                # Execute the command
                result = subprocess.run(
                    shlex.split(actual_cmd),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Store the result
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
        
        return jsonify({"commands": commands})
    
    except Exception as e:
        logger.error(f"Receive error: {e}")
        return jsonify({"error": "Internal server error"}), 500
