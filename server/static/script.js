// Authentication handling
let authHeader = null;

// Check if we have credentials stored
function getStoredCredentials() {
    const username = localStorage.getItem('rcon_username');
    const password = localStorage.getItem('rcon_password');
    return username && password ? { username, password } : null;
}

// Store credentials
function storeCredentials(username, password) {
    localStorage.setItem('rcon_username', username);
    localStorage.setItem('rcon_password', password);
}

// Clear stored credentials
function clearCredentials() {
    localStorage.removeItem('rcon_username');
    localStorage.removeItem('rcon_password');
    authHeader = null;
}

// Create auth header
function createAuthHeader(username, password) {
    return 'Basic ' + btoa(`${username}:${password}`);
}

// Show login modal
function showLoginModal() {
    const modal = document.createElement('div');
    modal.id = 'login-modal';
    modal.style.position = 'fixed';
    modal.style.top = '0';
    modal.style.left = '0';
    modal.style.width = '100%';
    modal.style.height = '100%';
    modal.style.backgroundColor = 'rgba(0,0,0,0.7)';
    modal.style.display = 'flex';
    modal.style.justifyContent = 'center';
    modal.style.alignItems = 'center';
    modal.style.zIndex = '1000';
    
    modal.innerHTML = `
        <div style="background: white; padding: 20px; border-radius: 5px; width: 300px;">
            <h2>Login Required</h2>
            <form id="login-form">
                <div style="margin-bottom: 15px;">
                    <label for="login-username">Username:</label>
                    <input type="text" id="login-username" required style="width: 100%; padding: 5px;">
                </div>
                <div style="margin-bottom: 15px;">
                    <label for="login-password">Password:</label>
                    <input type="password" id="login-password" required style="width: 100%; padding: 5px;">
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <button type="submit">Login</button>
                    <button type="button" onclick="document.getElementById('login-modal').remove()">Cancel</button>
                </div>
            </form>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    document.getElementById('login-form').addEventListener('submit', function(e) {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        
        if (username && password) {
            storeCredentials(username, password);
            authHeader = createAuthHeader(username, password);
            modal.remove();
            refreshClients();
        }
    });
}

// Check authentication and prompt if needed
function ensureAuthenticated() {
    const credentials = getStoredCredentials();
    if (credentials) {
        authHeader = createAuthHeader(credentials.username, credentials.password);
        return true;
    } else {
        showLoginModal();
        return false;
    }
}

// Logout function
function logout() {
    if (confirm('Are you sure you want to logout?')) {
        clearCredentials();
        window.location.reload();
    }
}

// Handle API responses
async function handleApiResponse(response) {
    if (response.status === 401) {
        clearCredentials();
        showLoginModal();
        throw new Error('Authentication required');
    }
    
    if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
    }
    
    return response.json();
}

// Refresh clients list
async function refreshClients() {
    if (!ensureAuthenticated()) return;
    
    try {
        const response = await fetch('/clients', {
            headers: {
                'Authorization': authHeader
            }
        });
        
        const clients = await handleApiResponse(response);
        const clientsList = document.getElementById('clients-list');
        const clientSelect = document.getElementById('client-select');
        
        clientsList.innerHTML = '';
        clientSelect.innerHTML = '<option value="">Select a client</option>';
        
        if (Object.keys(clients).length === 0) {
            clientsList.innerHTML = '<p>No clients connected</p>';
            return;
        }
        
        for (const [name, info] of Object.entries(clients)) {
            // Add to clients list
            const clientItem = document.createElement('div');
            clientItem.className = 'client-item';
            clientItem.innerHTML = `
                <strong>${name}</strong>
                <div>Connected: ${Math.floor(info.connected_at)} seconds ago</div>
            `;
            clientsList.appendChild(clientItem);
            
            // Add to client select dropdown
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            clientSelect.appendChild(option);
        }
    } catch (error) {
        console.error('Error fetching clients:', error);
        document.getElementById('clients-list').innerHTML = '<p>Error loading clients</p>';
    }
}

// Handle target selection change
document.querySelectorAll('input[name="target"]').forEach(radio => {
    radio.addEventListener('change', function() {
        document.getElementById('client-select').disabled = this.value !== 'specific';
    });
});

// Send command to clients
async function sendCommand() {
    if (!ensureAuthenticated()) return;
    
    const command = document.getElementById('command').value.trim();
    if (!command) {
        alert('Please enter a command');
        return;
    }
    
    const targetType = document.querySelector('input[name="target"]:checked').value;
    let target = 'all';
    
    if (targetType === 'specific') {
        target = document.getElementById('client-select').value;
        if (!target) {
            alert('Please select a client');
            return;
        }
    }
    
    try {
        const response = await fetch('/send-command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': authHeader
            },
            body: JSON.stringify({
                command: command,
                target: target
            })
        });
        
        const result = await handleApiResponse(response);
        
        // Display result
        const outputArea = document.getElementById('output');
        const resultDiv = document.createElement('div');
        resultDiv.className = `command-result ${result.status === 'success' ? 'success' : 'error'}`;
        resultDiv.innerHTML = `
            <h4>Command: ${command}</h4>
            <p>Target: ${target}</p>
            <p>Status: ${result.status}</p>
            <p>Message: ${result.message}</p>
        `;
        outputArea.appendChild(resultDiv);
        outputArea.scrollTop = outputArea.scrollHeight;
        
        // Clear command input
        document.getElementById('command').value = '';
        
        // Refresh clients to get updated status
        setTimeout(refreshClients, 1000);
    } catch (error) {
        console.error('Error sending command:', error);
        alert('Error sending command: ' + error.message);
    }
}

// Quick command buttons
function quickCommand(command) {
    document.getElementById('command').value = command;
}

// Auto-refresh clients every 10 seconds
setInterval(refreshClients, 10000);

// Initial load
document.addEventListener('DOMContentLoaded', function() {
    // Try to use stored credentials first
    const credentials = getStoredCredentials();
    if (credentials) {
        authHeader = createAuthHeader(credentials.username, credentials.password);
        refreshClients();
    } else {
        showLoginModal();
    }
});
