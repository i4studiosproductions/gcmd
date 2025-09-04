// API call helper
async function apiCall(url, options = {}) {
    const response = await fetch(url, {
        credentials: 'include', // Include cookies
        ...options
    });
    
    if (response.status === 401 || response.status === 303) {
        // Session expired, redirect to login
        window.location.href = '/login';
        throw new Error('Authentication required');
    }
    
    if (!response.ok) {
        throw new Error(`API error: ${response.status} ${response.statusText}`);
    }
    
    return response.json();
}

// Logout function
function logout() {
    if (confirm('Are you sure you want to logout?')) {
        fetch('/logout', {
            method: 'POST',
            credentials: 'include'
        }).then(() => {
            window.location.href = '/login';
        });
    }
}

// Refresh clients list
async function refreshClients() {
    try {
        const clients = await apiCall('/clients');
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
                <div>Connected: ${Math.floor(asyncio.get_event_loop().time() - info.connected_at)} seconds ago</div>
                <div>Last activity: ${Math.floor(asyncio.get_event_loop().time() - info.last_heartbeat)} seconds ago</div>
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
        const result = await apiCall('/send-command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                command: command,
                target: target
            })
        });
        
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

// Auto-refresh clients every 5 seconds
setInterval(refreshClients, 5000);

// Initial load
document.addEventListener('DOMContentLoaded', function() {
    refreshClients();
});
