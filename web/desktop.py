"""Desktop pet ala AIRI: PyQt6 + QtWebEngine.
Frameless, transparan per-pixel (WA_TranslucentBackground), always-on-top.
- Drag: JS navigasi ke yui://drag (dicegat -> startSystemMove)
- Click-through: yui://toggle atau hotkey F10 (WA_TransparentForMouseEvents)
Server ditunggu siap dulu supaya tidak muncul 'can't reach this page'.
"""
import sys
import time

import httpx
from PyQt6.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QSizeGrip


def wait_for_server(url: str, timeout: float = 90.0) -> None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        try:
            if httpx.get(url, timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise TimeoutError(f"server {url} tidak siap dalam {timeout}s")


class _PetPage(QWebEnginePage):
    """Cegat navigasi scheme yui:// sebagai perintah dari JS."""

    def __init__(self, pet: "Pet"):
        super().__init__()
        self._pet = pet

    def acceptNavigationRequest(self, url: QUrl, navtype, ismain) -> bool:
        if url.scheme() == "yui":
            if url.host() == "drag":
                self._pet.drag()
            elif url.host() == "toggle":
                self._pet.toggle_clickthrough()
            return False
        return super().acceptNavigationRequest(url, navtype, ismain)


class Pet(QObject):
    _toggle_sig = pyqtSignal()
    _debug_sig = pyqtSignal()

    def __init__(self, url: str, title: str = "Yui", width: int = 320, height: int = 420):
        super().__init__()
        self._url, self._title, self._w, self._h = url, title, width, height
        self._click_through = False
        self._win: QMainWindow | None = None
        self._view: QWebEngineView | None = None
        self._toggle_sig.connect(self._apply_toggle)  # queued -> aman antar thread
        self._debug_sig.connect(self._apply_debug)

    def start(self) -> None:
        """Blocking — panggil di main thread."""
        wait_for_server(self._url)
        app = QApplication(sys.argv)  # argv kosong = QtWebEngine crash
        win = QMainWindow()
        win.setWindowTitle(self._title)
        win.setWindowFlags(Qt.WindowType.FramelessWindowHint
                           | Qt.WindowType.WindowStaysOnTopHint
                           | Qt.WindowType.Tool)
        win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        win.setStyleSheet("background: transparent;")
        win.resize(self._w, self._h)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        win.move(screen.right() - self._w - 40, screen.bottom() - self._h - 40)

        view = QWebEngineView()
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        view.setStyleSheet("background: transparent;")
        page = _PetPage(self)
        page.setBackgroundColor(Qt.GlobalColor.transparent)
        view.setPage(page)
        view.setUrl(QUrl(self._url))
        win.setCentralWidget(view)
        # frameless -> resize manual via grip pojok kanan bawah (karakter auto-refit via JS 'resize')
        grip = QSizeGrip(win)
        _orig_resize = win.resizeEvent
        def _resize(ev):
            grip.move(win.width() - grip.width(), win.height() - grip.height())
            _orig_resize(ev)
        win.resizeEvent = _resize
        win.show()
        self._win, self._view = win, view
        app.exec()

    def drag(self) -> None:
        if self._win and self._win.windowHandle():
            self._win.windowHandle().startSystemMove()

    def toggle_clickthrough(self) -> None:
        self._toggle_sig.emit()

    def toggle_debug(self) -> None:
        self._debug_sig.emit()

    @pyqtSlot()
    def _apply_debug(self) -> None:
        if self._view:
            self._view.page().runJavaScript("window.__toggleBounds && window.__toggleBounds();")

    @pyqtSlot()
    def _apply_toggle(self) -> None:
        self._click_through = not self._click_through
        if self._win:
            self._win.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                                   self._click_through)
            self._win.show()  # attribute baru berlaku setelah re-show
        if self._view:
            teks = "Yui — click-through (F10 balik)" if self._click_through else "Yui"
            self._view.page().runJavaScript(
                f"var e=document.getElementById('label'); if(e) e.textContent='{teks}';")
