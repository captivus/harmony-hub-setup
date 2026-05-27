"""Bluetooth RFCOMM socket abstraction.

Tries native socket.AF_BLUETOOTH first (available when CPython was compiled
with Bluetooth headers). Falls back to a ctypes implementation that calls
libc directly (works on any Linux with BlueZ installed).
"""

from __future__ import annotations

import socket as _socket


def RFCOMMSocket():
    """Create an RFCOMM socket using the best available method."""
    if hasattr(_socket, "AF_BLUETOOTH"):
        return _NativeRFCOMMSocket()
    return _CtypesRFCOMMSocket()


class _NativeRFCOMMSocket:
    """RFCOMM socket using Python's native Bluetooth support."""

    def __init__(self):
        self._sock = _socket.socket(
            _socket.AF_BLUETOOTH,
            _socket.SOCK_STREAM,
            _socket.BTPROTO_RFCOMM,
        )

    def connect(self, address: str, channel: int = 1):
        self._sock.connect((address, channel))

    def settimeout(self, seconds: float):
        self._sock.settimeout(seconds)

    def send(self, data: bytes) -> int:
        return self._sock.send(data)

    def recv(self, bufsize: int = 4096) -> bytes:
        return self._sock.recv(bufsize)

    def close(self):
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _CtypesRFCOMMSocket:
    """RFCOMM socket using ctypes (for Pythons without AF_BLUETOOTH)."""

    def __init__(self):
        import ctypes

        self._ctypes = ctypes
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)

        AF_BLUETOOTH = 31
        SOCK_STREAM = 1
        BTPROTO_RFCOMM = 3

        self._fd = self._libc.socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM)
        if self._fd < 0:
            import os
            err = ctypes.get_errno()
            raise OSError(err, f"socket(): {os.strerror(err)}")

    def connect(self, address: str, channel: int = 1):
        import os
        ctypes = self._ctypes

        class _SockaddrRC(ctypes.Structure):
            _fields_ = [
                ("rc_family", ctypes.c_ushort),
                ("rc_bdaddr", ctypes.c_uint8 * 6),
                ("rc_channel", ctypes.c_uint8),
            ]

        parts = address.split(":")
        if len(parts) != 6:
            raise ValueError(f"Invalid Bluetooth address: {address}")
        bdaddr = (ctypes.c_uint8 * 6)()
        for i, part in enumerate(reversed(parts)):
            bdaddr[i] = int(part, 16)

        addr = _SockaddrRC()
        addr.rc_family = 31
        addr.rc_bdaddr = bdaddr
        addr.rc_channel = channel

        result = self._libc.connect(
            self._fd, ctypes.byref(addr), ctypes.sizeof(addr),
        )
        if result < 0:
            err = ctypes.get_errno()
            raise OSError(err, f"connect({address}, ch={channel}): {os.strerror(err)}")

    def settimeout(self, seconds: float):
        import struct
        ctypes = self._ctypes

        tv_sec = int(seconds)
        tv_usec = int((seconds - tv_sec) * 1_000_000)
        timeval = struct.pack("ll", tv_sec, tv_usec)
        timeval_buf = ctypes.create_string_buffer(timeval)

        SOL_SOCKET = 1
        SO_RCVTIMEO = 20
        SO_SNDTIMEO = 21

        for opt in (SO_RCVTIMEO, SO_SNDTIMEO):
            self._libc.setsockopt(
                self._fd, SOL_SOCKET, opt,
                timeval_buf, len(timeval),
            )

    def send(self, data: bytes) -> int:
        import os
        ctypes = self._ctypes
        buf = ctypes.create_string_buffer(data)
        n = self._libc.send(self._fd, buf, len(data), 0)
        if n < 0:
            err = ctypes.get_errno()
            raise OSError(err, f"send(): {os.strerror(err)}")
        return n

    def recv(self, bufsize: int = 4096) -> bytes:
        import errno
        import os
        ctypes = self._ctypes
        buf = ctypes.create_string_buffer(bufsize)
        n = self._libc.recv(self._fd, buf, bufsize, 0)
        if n < 0:
            err = ctypes.get_errno()
            if err in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise TimeoutError("recv timed out")
            raise OSError(err, f"recv(): {os.strerror(err)}")
        return buf.raw[:n]

    def close(self):
        if self._fd >= 0:
            self._libc.close(self._fd)
            self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
