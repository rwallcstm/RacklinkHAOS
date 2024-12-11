import asyncio
import socket

async def send_command(ip, command, retries=3, delay=10):
    """Send a command with retry logic."""
    for attempt in range(retries):
        try:
            with socket.create_connection((ip, 60000), timeout=10) as sock:
                sock.sendall(command.encode())
                return sock.recv(1024).decode()
        except (socket.timeout, socket.error):
            if attempt < retries - 1:
                await asyncio.sleep(delay)
            else:
                raise ConnectionError("Failed to connect to PDU.")

async def test_connection(ip):
    """Test connection to the PDU."""
    return await send_command(ip, "ping")

async def get_status(ip, status_type):
    """Get status from PDU."""
    command = f"status:{status_type}"
    return await send_command(ip, command)
