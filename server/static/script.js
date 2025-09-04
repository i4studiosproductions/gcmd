let authHeader = 'Basic ' + btoa('admin:password'); // This will be set by the server

// Update auth header with actual credentials
function updateAuthHeader() {
    const username = prompt('Enter username:') || 'admin';
    const password = prompt('Enter password:') || 'password';
    authHeader = 'Basic ' + btoa(`${username}:${password}`);
    refreshClients();
}

// Logout function
function logout() {
    if (confirm('Are you sure you want to logout?')) {
        window.location.href = '/';
    }
}

// Refresh clients list
async function refreshClients() {
    try {
        const response = await fetch('/clients', {
            headers: {
                'Authorization': authHeader
            }
        });
        
        if (response.status === 401) {
            updateAuthHeader();
            return;
        }
        
        const clients = await response.json();
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
        
        if (response.status === 401) {
            updateAuthHeader();
            return;
        }
        
        const result = await response.json();
        
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
    refreshClients();
});
