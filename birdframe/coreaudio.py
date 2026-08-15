"""Small CoreAudio control seam used to keep the dedicated input unmuted.

Some inexpensive USB microphones expose a standard USB feature-unit mute but
no visible physical switch. macOS persists that hidden control across device
re-enumeration, so an input can stream plausible ADC noise while all acoustic
signal remains muted. This module intentionally touches only that one control.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Protocol


def _fourcc(value: str) -> int:
    return int.from_bytes(value.encode("ascii"), "big")


class CoreAudioControl(Protocol):
    def devices(self) -> list[int]: ...
    def default_input_device(self) -> int | None: ...
    def name(self, device: int) -> str: ...
    def input_muted(self, device: int) -> bool | None: ...
    def set_input_muted(self, device: int, muted: bool) -> None: ...


class _PropertyAddress(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


class _DarwinCoreAudio:
    SYSTEM_OBJECT = 1
    GLOBAL = _fourcc("glob")
    INPUT = _fourcc("inpt")
    MAIN = 0

    def __init__(self) -> None:
        self.audio = ctypes.CDLL(
            "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        self.cf = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        address = ctypes.POINTER(_PropertyAddress)
        self.audio.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, address, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self.audio.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        self.audio.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, address, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
        ]
        self.audio.AudioObjectGetPropertyData.restype = ctypes.c_int32
        self.audio.AudioObjectSetPropertyData.argtypes = [
            ctypes.c_uint32, address, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_void_p,
        ]
        self.audio.AudioObjectSetPropertyData.restype = ctypes.c_int32
        self.audio.AudioObjectHasProperty.argtypes = [ctypes.c_uint32, address]
        self.audio.AudioObjectHasProperty.restype = ctypes.c_ubyte
        self.cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32]
        self.cf.CFStringGetCString.restype = ctypes.c_ubyte
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

    @classmethod
    def _address(cls, selector: str, scope: int | None = None) -> _PropertyAddress:
        resolved_scope = cls.GLOBAL if scope is None else scope
        return _PropertyAddress(_fourcc(selector), resolved_scope, cls.MAIN)

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status:
            raise OSError(status, f"CoreAudio {operation} failed")

    def devices(self) -> list[int]:
        address = self._address("dev#")
        size = ctypes.c_uint32()
        self._check(self.audio.AudioObjectGetPropertyDataSize(
            self.SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size)),
            "device-list size")
        count = size.value // ctypes.sizeof(ctypes.c_uint32)
        values = (ctypes.c_uint32 * count)()
        self._check(self.audio.AudioObjectGetPropertyData(
            self.SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size),
            ctypes.byref(values)), "device list")
        return list(values)

    def default_input_device(self) -> int | None:
        address = self._address("dIn ")
        value = ctypes.c_uint32()
        size = ctypes.c_uint32(ctypes.sizeof(value))
        self._check(self.audio.AudioObjectGetPropertyData(
            self.SYSTEM_OBJECT, ctypes.byref(address), 0, None, ctypes.byref(size),
            ctypes.byref(value)), "default input")
        return value.value or None

    def name(self, device: int) -> str:
        address = self._address("lnam")
        value = ctypes.c_void_p()
        size = ctypes.c_uint32(ctypes.sizeof(value))
        self._check(self.audio.AudioObjectGetPropertyData(
            device, ctypes.byref(address), 0, None, ctypes.byref(size),
            ctypes.byref(value)), "device name")
        if not value.value:
            return ""
        try:
            buffer = ctypes.create_string_buffer(1024)
            ok = self.cf.CFStringGetCString(
                value, buffer, len(buffer), 0x08000100)  # kCFStringEncodingUTF8
            return buffer.value.decode("utf-8") if ok else ""
        finally:
            self.cf.CFRelease(value)

    def input_muted(self, device: int) -> bool | None:
        address = self._address("mute", self.INPUT)
        if not self.audio.AudioObjectHasProperty(device, ctypes.byref(address)):
            return None
        value = ctypes.c_uint32()
        size = ctypes.c_uint32(ctypes.sizeof(value))
        self._check(self.audio.AudioObjectGetPropertyData(
            device, ctypes.byref(address), 0, None, ctypes.byref(size),
            ctypes.byref(value)), "input mute read")
        return bool(value.value)

    def set_input_muted(self, device: int, muted: bool) -> None:
        address = self._address("mute", self.INPUT)
        value = ctypes.c_uint32(1 if muted else 0)
        self._check(self.audio.AudioObjectSetPropertyData(
            device, ctypes.byref(address), 0, None, ctypes.sizeof(value),
            ctypes.byref(value)), "input mute write")


def ensure_input_unmuted(device_name: str | None,
                         sdk: CoreAudioControl | None = None) -> bool:
    """Clear a configured/default input's hidden CoreAudio mute when present.

    Returns True only when a mute was actually cleared. Unsupported platforms,
    absent devices, and devices without a mute feature are harmless no-ops.
    """
    if sdk is None:
        if sys.platform != "darwin":
            return False
        sdk = _DarwinCoreAudio()
    if device_name:
        wanted = device_name.casefold()
        device = next((d for d in sdk.devices()
                       if sdk.name(d).casefold() == wanted), None)
    else:
        device = sdk.default_input_device()
    if device is None or sdk.input_muted(device) is not True:
        return False
    sdk.set_input_muted(device, False)
    return True
