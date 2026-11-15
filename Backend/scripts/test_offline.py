"""Run the complete suite with real socket connections and DNS disabled."""
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))


def deny_network(*args, **kwargs):
    raise AssertionError("Unexpected real network operation in offline tests")


# Windows implements socketpair using an internal loopback connection. Allow
# only that narrowly scoped operation so asyncio/TestClient can create a loop.
_local = threading.local()
_socketpair = socket.socketpair
_connect = socket.socket.connect


def internal_socketpair(*args, **kwargs):
    _local.socketpair = True
    try:
        return _socketpair(*args, **kwargs)
    finally:
        _local.socketpair = False


def guarded_connect(sock, address):
    if getattr(_local, "socketpair", False) and address[0] in ("127.0.0.1", "::1"):
        return _connect(sock, address)
    return deny_network()


if __name__ == "__main__":
    with patch.object(socket, "socketpair", internal_socketpair), patch.object(socket.socket, "connect", guarded_connect), patch.object(socket.socket, "connect_ex", deny_network), patch.object(socket, "getaddrinfo", deny_network):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(root / "tests")))
    sys.exit(not result.wasSuccessful())
