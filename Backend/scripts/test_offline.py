"""Run the complete suite with real socket connections and DNS disabled."""
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))


def deny_network(*args, **kwargs):
    raise AssertionError("Unexpected real network operation in offline tests")


if __name__ == "__main__":
    with patch.object(socket.socket, "connect", deny_network), patch.object(socket, "getaddrinfo", deny_network):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(root / "tests")))
    sys.exit(not result.wasSuccessful())
