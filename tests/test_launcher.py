from __future__ import annotations

import socket

from mns.launcher import build_streamlit_env, can_bind_port, find_available_port, is_port_open


def test_is_port_open_and_find_available_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    host, used_port = sock.getsockname()

    try:
        assert is_port_open(host, used_port) is True
        assert can_bind_port(host, used_port) is False
        candidate = find_available_port(host, used_port, max_tries=5)
        assert candidate != used_port
        assert candidate >= used_port + 1
    finally:
        sock.close()


def test_build_streamlit_env_sets_utf8_defaults_and_preserves_existing():
    env = build_streamlit_env({"PATH": "X", "PYTHONUTF8": "0"})

    assert env["PATH"] == "X"
    assert env["PYTHONUTF8"] == "0"
    assert env["PYTHONIOENCODING"] == "utf-8"
