"""Length-prefixed TCP protocol for Ableton MCP communication.

Protocol format:
- Send: 4-byte length prefix (big-endian/network byte order) + JSON UTF-8 payload
- Receive: Read 4-byte length, then read exact payload bytes

This replaces the fragile JSON-parsing-as-framing approach with deterministic
message boundaries.
"""

import json
import socket
from typing import Any


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes from socket, handling partial reads.

    Args:
        sock: Connected socket to read from
        n: Exact number of bytes to read

    Returns:
        Exactly n bytes of data

    Raises:
        ConnectionError: If socket closes before n bytes received
    """
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Socket closed before receiving expected data")
        data += chunk
    return data


def send_message(sock: socket.socket, data: Any) -> None:
    """Send a length-prefixed JSON message over socket.

    Args:
        sock: Connected socket to send on
        data: JSON-serializable data to send

    Raises:
        ConnectionError: If send fails
        TypeError: If data is not JSON-serializable
    """
    msg = json.dumps(data).encode('utf-8')
    length_prefix = len(msg).to_bytes(4, 'big')
    sock.sendall(length_prefix + msg)


def recv_message(sock: socket.socket) -> Any:
    """Receive a length-prefixed JSON message from socket.

    Args:
        sock: Connected socket to receive from

    Returns:
        Parsed JSON data

    Raises:
        ConnectionError: If socket closes unexpectedly
        json.JSONDecodeError: If payload is not valid JSON
    """
    length_bytes = recv_exact(sock, 4)
    length = int.from_bytes(length_bytes, 'big')
    payload = recv_exact(sock, length)
    return json.loads(payload.decode('utf-8'))
