from __future__ import annotations

import ctypes
import platform
from threading import Event, Thread

from PySide6.QtCore import QObject, Signal


class GlobalHotkey(QObject):
    activated = Signal()
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._system = platform.system().lower()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._windows_thread_id = 0
        self._mac_hotkey_ref = None
        self._mac_handler_ref = None
        self._mac_callback = None

    def start(self) -> None:
        if self._system == "windows":
            self._start_windows_hotkey()
            return

        if self._system == "darwin":
            self._start_macos_hotkey()
            return

        self.failed.emit("Глобальная горячая клавиша поддерживается только на Windows и macOS.")

    def stop(self) -> None:
        self._stop_event.set()

        if self._system == "windows":
            self._stop_windows_hotkey()
            return

        if self._system == "darwin":
            self._stop_macos_hotkey()

    def _start_windows_hotkey(self) -> None:
        self._thread = Thread(target=self._windows_message_loop, daemon=True)
        self._thread.start()

    def _stop_windows_hotkey(self) -> None:
        if not self._windows_thread_id:
            return

        user32 = ctypes.windll.user32
        wm_quit = 0x0012
        user32.PostThreadMessageW(self._windows_thread_id, wm_quit, 0, 0)

    def _windows_message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hotkey_id = 1001
        mod_alt = 0x0001
        mod_shift = 0x0004
        mod_norepeat = 0x4000
        vk_1 = 0x31
        wm_hotkey = 0x0312

        self._windows_thread_id = kernel32.GetCurrentThreadId()
        modifiers = mod_alt | mod_shift | mod_norepeat

        if not user32.RegisterHotKey(None, hotkey_id, modifiers, vk_1):
            self.failed.emit("Не удалось зарегистрировать Shift+Alt+1.")
            return

        try:
            msg = _WindowsMsg()
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    self.failed.emit("Ошибка чтения Windows hotkey-сообщения.")
                    break
                if msg.message == wm_hotkey and msg.wParam == hotkey_id:
                    self.activated.emit()
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    def _start_macos_hotkey(self) -> None:
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        except OSError as error:
            self.failed.emit(f"Не удалось открыть Carbon.framework: {error}")
            return

        event_class_keyboard = _four_char_code("keyb")
        event_hotkey_pressed = 5
        shift_key = 1 << 9
        control_key = 1 << 12
        keycode_1 = 18

        event_type = _MacEventTypeSpec(event_class_keyboard, event_hotkey_pressed)
        hotkey_id = _MacEventHotKeyID(_four_char_code("IAHK"), 1)

        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def _callback(_next_handler, _event, _user_data) -> int:
            self.activated.emit()
            return 0

        self._mac_callback = callback_type(_callback)

        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        app_target = carbon.GetApplicationEventTarget()

        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_MacEventTypeSpec),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._mac_handler_ref = ctypes.c_void_p()
        install_status = carbon.InstallEventHandler(
            app_target,
            self._mac_callback,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(self._mac_handler_ref),
        )
        if install_status != 0:
            self.failed.emit(f"Не удалось установить macOS hotkey handler: {install_status}")
            return

        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            _MacEventHotKeyID,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._mac_hotkey_ref = ctypes.c_void_p()
        register_status = carbon.RegisterEventHotKey(
            keycode_1,
            shift_key | control_key,
            hotkey_id,
            app_target,
            0,
            ctypes.byref(self._mac_hotkey_ref),
        )
        if register_status != 0:
            self.failed.emit(f"Не удалось зарегистрировать Shift+Control+1: {register_status}")

    def _stop_macos_hotkey(self) -> None:
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        except OSError:
            return

        if self._mac_hotkey_ref:
            carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            carbon.UnregisterEventHotKey(self._mac_hotkey_ref)
            self._mac_hotkey_ref = None

        if self._mac_handler_ref:
            carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
            carbon.RemoveEventHandler(self._mac_handler_ref)
            self._mac_handler_ref = None


class _WindowsPoint(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class _WindowsMsg(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt", _WindowsPoint),
    ]


class _MacEventTypeSpec(ctypes.Structure):
    _fields_ = [
        ("eventClass", ctypes.c_uint32),
        ("eventKind", ctypes.c_uint32),
    ]


class _MacEventHotKeyID(ctypes.Structure):
    _fields_ = [
        ("signature", ctypes.c_uint32),
        ("id", ctypes.c_uint32),
    ]


def _four_char_code(value: str) -> int:
    return int.from_bytes(value.encode("macroman"), "big")
