import sys
import re
import time
import traceback
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.audio_recorder import (
    AudioSource,
    listen_for_question,
    list_audio_sources,
    record_question,
)
from app.config import AUTO_COOLDOWN_SECONDS, RECORDINGS_DIR
from app.config import AUTO_FRAGMENT_MIN_SCORE
from app.global_hotkey import GlobalHotkey
from app.qa_loader import load_questions
from app.search_engine import format_answer_html, search
from app.session_logs import log_analysis, log_question
from app.speech_to_text import (
    get_model,
    transcribe_audio,
    transcribe_audio_samples,
    transcribe_auto_audio_details,
)


class ModelWarmupWorker(QObject):
    finished = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            get_model()
            self.finished.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())


class RecognitionWorker(QObject):
    partial_text = Signal(str)
    finished = Signal(str, list, dict)
    failed = Signal(str)

    def __init__(
        self,
        items: list[dict[str, Any]],
        audio_source_id: str | None,
    ) -> None:
        super().__init__()
        self.items = items
        self.audio_source_id = audio_source_id
        self.latest_partial_text = ""

    def run(self) -> None:
        partial_queue: Queue[tuple[Any, int]] = Queue(maxsize=1)
        stop_partial = Event()
        partial_thread = Thread(
            target=self._run_partial_transcription,
            args=(partial_queue, stop_partial),
        )
        partial_thread.start()

        try:
            total_started_at = time.perf_counter()
            record_started_at = time.perf_counter()
            audio_path = record_question(
                audio_source_id=self.audio_source_id,
                partial_audio_callback=lambda audio, sample_rate: self._queue_partial_audio(
                    partial_queue,
                    audio,
                    sample_rate,
                ),
            )
            stop_partial.set()
            partial_thread.join()
            transcribe_started_at = time.perf_counter()
            recognized_text = transcribe_audio(audio_path)
            used_partial_fallback = False
            if not recognized_text:
                recognized_text = self.latest_partial_text
                used_partial_fallback = bool(recognized_text)
            search_started_at = time.perf_counter()
            results = search(recognized_text, self.items)
            finished_at = time.perf_counter()
            metrics = {
                "audio_source_id": self.audio_source_id or "",
                "record_seconds": transcribe_started_at - record_started_at,
                "transcribe_seconds": search_started_at - transcribe_started_at,
                "search_seconds": finished_at - search_started_at,
                "total_seconds": finished_at - total_started_at,
                "used_partial_fallback": used_partial_fallback,
            }
            self.finished.emit(recognized_text, results, metrics)
        except Exception:
            stop_partial.set()
            partial_thread.join()
            self.failed.emit(traceback.format_exc())

    def _queue_partial_audio(
        self,
        partial_queue: Queue[tuple[Any, int]],
        audio: Any,
        sample_rate: int,
    ) -> None:
        try:
            if partial_queue.full():
                partial_queue.get_nowait()
            partial_queue.put_nowait((audio, sample_rate))
        except (Empty, Full):
            return

    def _run_partial_transcription(
        self,
        partial_queue: Queue[tuple[Any, int]],
        stop_partial: Event,
    ) -> None:
        last_text = ""

        while not stop_partial.is_set():
            try:
                audio, sample_rate = partial_queue.get(timeout=0.2)
            except Empty:
                continue

            try:
                partial_path = RECORDINGS_DIR / "partial_question.wav"
                text = transcribe_audio_samples(audio, sample_rate, partial_path)
            except Exception:
                continue

            if text and text != last_text:
                last_text = text
                self.latest_partial_text = text
                self.partial_text.emit(text)


class AutoRecognitionWorker(QObject):
    result_ready = Signal(str, list, dict)
    status_changed = Signal(str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        items: list[dict[str, Any]],
        audio_source_id: str | None,
        audio_source_label: str,
    ) -> None:
        super().__init__()
        self.items = items
        self.audio_source_id = audio_source_id
        self.audio_source_label = audio_source_label
        self.stop_event = Event()
        self.speech_started_at: float | None = None

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                self.status_changed.emit("Авто: жду речь...")

                total_started_at = time.perf_counter()
                listen_started_at = time.perf_counter()
                self.speech_started_at = None
                audio_path = listen_for_question(
                    audio_source_id=self.audio_source_id,
                    partial_audio_callback=None,
                    stop_callback=self.stop_event.is_set,
                    speech_started_callback=self._on_speech_started,
                )

                if self.stop_event.is_set():
                    break

                if audio_path is None:
                    self.status_changed.emit("Авто: шум пропущен. Жду речь...")
                    skipped_at = time.perf_counter()
                    timing_metrics = self._audio_timing_metrics(
                        listen_started_at,
                        skipped_at,
                    )
                    log_analysis(
                        event="AUTO: шум пропущен до распознавания",
                        mode="auto",
                        audio_source=self.audio_source_label,
                        metrics={
                            **timing_metrics,
                            "total_seconds": skipped_at - total_started_at,
                        },
                    )
                    continue

                self.status_changed.emit("Авто: распознаю вопрос...")
                transcribe_started_at = time.perf_counter()
                timing_metrics = self._audio_timing_metrics(
                    listen_started_at,
                    transcribe_started_at,
                )
                transcribe_details = transcribe_auto_audio_details(audio_path)
                raw_recognized_text = transcribe_details["raw_text"]
                recognized_text = transcribe_details["text"]

                if not recognized_text:
                    self.status_changed.emit("Авто: не похоже на вопрос. Жду дальше...")
                    ignored_at = time.perf_counter()
                    log_analysis(
                        event="AUTO: распознанный фрагмент отброшен",
                        mode="auto",
                        audio_source=self.audio_source_label,
                        recognized_text=raw_recognized_text,
                        metrics={
                            **timing_metrics,
                            "transcribe_seconds": ignored_at - transcribe_started_at,
                            "total_seconds": ignored_at - total_started_at,
                            "raw_recognized_text": raw_recognized_text or "нет",
                            "reject_reason": transcribe_details["reject_reason"],
                        },
                        details="VAD/text-фильтр решил, что это шум или слишком короткая фраза.",
                    )
                    self.stop_event.wait(AUTO_COOLDOWN_SECONDS)
                    continue

                search_started_at = time.perf_counter()
                results = search(recognized_text, self.items)
                finished_at = time.perf_counter()
                reject_reason = _auto_fragment_reject_reason(recognized_text, results)
                metrics = {
                    "audio_source_id": self.audio_source_id or "",
                    **timing_metrics,
                    "transcribe_seconds": search_started_at - transcribe_started_at,
                    "search_seconds": finished_at - search_started_at,
                    "total_seconds": finished_at - total_started_at,
                }

                if reject_reason:
                    self.status_changed.emit("Авто: короткий фрагмент пропущен. Жду дальше...")
                    log_analysis(
                        event="AUTO: короткий обрывок отброшен после поиска",
                        mode="auto",
                        audio_source=self.audio_source_label,
                        recognized_text=recognized_text,
                        results=results,
                        metrics={
                            **metrics,
                            "raw_recognized_text": raw_recognized_text,
                            "reject_reason": reject_reason,
                        },
                        details="Похоже на хвост предыдущей фразы, а не на отдельный вопрос.",
                    )
                    self.stop_event.wait(AUTO_COOLDOWN_SECONDS)
                    continue

                self.result_ready.emit(recognized_text, results, metrics)
                self.stop_event.wait(AUTO_COOLDOWN_SECONDS)

            self.stopped.emit()
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _on_speech_started(self) -> None:
        if self.speech_started_at is None:
            self.speech_started_at = time.perf_counter()
        self.status_changed.emit("Авто: слышу вопрос...")

    def _audio_timing_metrics(
        self,
        listen_started_at: float,
        finished_at: float,
    ) -> dict[str, float]:
        if self.speech_started_at is None:
            return {
                "waiting_seconds": finished_at - listen_started_at,
                "record_seconds": 0.0,
            }

        return {
            "waiting_seconds": max(0.0, self.speech_started_at - listen_started_at),
            "record_seconds": max(0.0, finished_at - self.speech_started_at),
        }


def _auto_fragment_reject_reason(
    recognized_text: str,
    results: list[dict[str, Any]],
) -> str:
    best_score = int(results[0].get("score", 0)) if results else 0
    words = _text_words(recognized_text)

    if best_score >= AUTO_FRAGMENT_MIN_SCORE:
        return ""

    if _has_question_intent(words):
        return ""

    if len(words) <= 5:
        return f"short_fragment_low_score_{best_score}"

    return ""


def _has_question_intent(words: list[str]) -> bool:
    markers = {
        "как",
        "какой",
        "какая",
        "какие",
        "каким",
        "что",
        "чем",
        "зачем",
        "почему",
        "когда",
        "где",
        "сколько",
        "ли",
        "можно",
        "можешь",
        "можете",
        "расскажи",
        "расскажите",
        "опиши",
        "объясни",
        "приходилось",
        "code",
        "review",
        "jira",
        "trello",
        "weeek",
    }
    return any(word in markers for word in words)


def _text_words(text: str) -> list[str]:
    return re.findall(r"[a-zа-яё#]+", text.lower(), flags=re.IGNORECASE)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.items = load_questions()
        self.thread: QThread | None = None
        self.worker: RecognitionWorker | None = None
        self.auto_thread: QThread | None = None
        self.auto_worker: AutoRecognitionWorker | None = None
        self.model_thread: QThread | None = None
        self.model_worker: ModelWarmupWorker | None = None
        self.global_hotkey: GlobalHotkey | None = None
        self.last_results: list[dict[str, Any]] = []
        self.audio_sources: list[AudioSource] = []
        self.model_ready = False

        self.setWindowTitle("Interview Assistant - Unity / C#")
        self.resize(1100, 700)

        self.audio_source_box = QComboBox()
        self.refresh_devices_button = QPushButton("Обновить")
        self.refresh_devices_button.clicked.connect(self.refresh_audio_sources)

        self.record_button = QPushButton("●")
        self.record_button.setFixedSize(58, 58)
        self.record_button.setToolTip("Записать вопрос")
        self.record_button.setStyleSheet(
            """
            QPushButton {
                color: #b91c1c;
                font-size: 24px;
                font-weight: 700;
                border: 2px solid #7f858c;
                border-radius: 29px;
                background: qradialgradient(
                    cx: 0.42, cy: 0.35, radius: 0.75,
                    fx: 0.32, fy: 0.26,
                    stop: 0 #f4f6f8,
                    stop: 0.45 #c7ccd1,
                    stop: 0.72 #8d949b,
                    stop: 1 #e8eaed
                );
            }
            QPushButton:hover {
                border-color: #5f6872;
            }
            QPushButton:pressed {
                background: qradialgradient(
                    cx: 0.45, cy: 0.40, radius: 0.75,
                    fx: 0.35, fy: 0.32,
                    stop: 0 #d7dade,
                    stop: 0.55 #969da5,
                    stop: 1 #f0f1f3
                );
            }
            QPushButton:disabled {
                color: #ef4444;
                border-color: #9ca3af;
                background: #d1d5db;
            }
            """
        )
        self.record_button.clicked.connect(self.start_recognition)

        self.auto_button = QPushButton("AUTO")
        self.auto_button.setCheckable(True)
        self.auto_button.setFixedHeight(34)
        self.auto_button.setToolTip("Автоматически слушать вопросы")
        self.auto_button.setStyleSheet(
            """
            QPushButton {
                color: #dbeafe;
                font-weight: 700;
                border: 1px solid #2563eb;
                border-radius: 17px;
                padding: 0 14px;
                background: #1e3a8a;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:checked {
                color: #052e16;
                border-color: #22c55e;
                background: #4ade80;
            }
            QPushButton:disabled {
                color: #9ca3af;
                border-color: #4b5563;
                background: #374151;
            }
            """
        )
        self.auto_button.clicked.connect(self.toggle_auto_recognition)

        self.status_label = QLabel(f"Загружено вопросов: {len(self.items)}")
        self.refresh_audio_sources()

        self.recognized_text = QPlainTextEdit()
        self.recognized_text.setPlaceholderText("Здесь появится распознанный текст...")
        self.recognized_text.setReadOnly(False)

        self.quick_search_input = QLineEdit()
        self.quick_search_input.setPlaceholderText(
            "Быстрый поиск по ключевым словам: jira, задачи, состав команды..."
        )
        self.quick_search_input.returnPressed.connect(self.search_quick_text)

        self.quick_search_button = QPushButton("Найти")
        self.quick_search_button.clicked.connect(self.search_quick_text)

        self.answer_text = QTextEdit()
        self.answer_text.setPlaceholderText("Здесь появится ответ...")
        self.answer_text.setReadOnly(True)

        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.show_selected_result)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Распознанный вопрос"))
        left_layout.addWidget(self.recognized_text)
        left_layout.addWidget(QLabel("Похожие вопросы"))
        left_layout.addWidget(self.results_list)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Ответ"))
        right_layout.addWidget(self.answer_text)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 650])

        central = QWidget()
        main_layout = QVBoxLayout(central)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Источник звука"))
        top_layout.addWidget(self.audio_source_box, 1)
        top_layout.addWidget(self.refresh_devices_button)
        top_layout.addWidget(self.record_button)
        top_layout.addWidget(self.auto_button)
        top_layout.addWidget(self.status_label)

        main_layout.addLayout(top_layout)

        quick_search_layout = QHBoxLayout()
        quick_search_layout.addWidget(QLabel("Быстрый поиск"))
        quick_search_layout.addWidget(self.quick_search_input, 1)
        quick_search_layout.addWidget(self.quick_search_button)

        main_layout.addLayout(quick_search_layout)
        main_layout.addWidget(splitter)

        self.setCentralWidget(central)
        self.start_global_hotkey()
        self.start_model_warmup()

    def closeEvent(self, event: Any) -> None:
        if self.global_hotkey is not None:
            self.global_hotkey.stop()
        if self.auto_worker is not None:
            self.auto_worker.stop()
        if self.auto_thread is not None:
            self.auto_thread.quit()
            self.auto_thread.wait(2000)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)
        super().closeEvent(event)

    def start_global_hotkey(self) -> None:
        self.global_hotkey = GlobalHotkey()
        self.global_hotkey.activated.connect(self.toggle_window_visibility)
        self.global_hotkey.failed.connect(self.on_global_hotkey_failed)
        self.global_hotkey.start()

    def toggle_window_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
            log_analysis(
                event="Окно скрыто горячей клавишей",
                mode="hotkey",
                details="Windows: Shift+Alt+1; macOS: Shift+Control+1",
            )
            return

        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        log_analysis(
            event="Окно показано горячей клавишей",
            mode="hotkey",
            details="Windows: Shift+Alt+1; macOS: Shift+Control+1",
        )

    def on_global_hotkey_failed(self, error: str) -> None:
        self.status_label.setText(error)
        log_analysis(
            event="Ошибка глобальной горячей клавиши",
            mode="hotkey",
            details=error,
        )

    def start_model_warmup(self) -> None:
        self.status_label.setText(f"Загружено вопросов: {len(self.items)}. Загружаю модель...")
        log_analysis(
            event="Запуск прогрева модели",
            mode="startup",
            details=f"Загружено вопросов: {len(self.items)}",
        )

        self.model_thread = QThread()
        self.model_worker = ModelWarmupWorker()
        self.model_worker.moveToThread(self.model_thread)

        self.model_thread.started.connect(self.model_worker.run)
        self.model_worker.finished.connect(self.on_model_warmup_finished)
        self.model_worker.failed.connect(self.on_model_warmup_failed)
        self.model_worker.finished.connect(self.model_thread.quit)
        self.model_worker.failed.connect(self.model_thread.quit)
        self.model_thread.finished.connect(self.cleanup_model_thread)

        self.model_thread.start()

    def on_model_warmup_finished(self) -> None:
        self.model_ready = True
        self.record_button.setEnabled(bool(self.audio_sources))
        self.auto_button.setEnabled(bool(self.audio_sources))
        self.status_label.setText(f"Загружено вопросов: {len(self.items)}. Модель готова.")
        log_analysis(
            event="Модель готова",
            mode="startup",
            details=f"Доступно аудио-источников: {len(self.audio_sources)}",
        )

    def on_model_warmup_failed(self, error: str) -> None:
        self.model_ready = False
        self.record_button.setEnabled(False)
        self.auto_button.setEnabled(False)
        self.status_label.setText("Модель не загрузилась.")
        self.answer_text.setPlainText(error)
        log_analysis(
            event="Ошибка загрузки модели",
            mode="startup",
            details=error,
        )

    def start_recognition(self) -> None:
        if not self.model_ready:
            self.status_label.setText("Подожди, модель еще загружается...")
            return

        if self.auto_worker is not None:
            self.status_label.setText("Сначала выключи AUTO.")
            return

        audio_source_id = self.audio_source_box.currentData()
        self.record_button.setEnabled(False)
        self.auto_button.setEnabled(False)
        self.audio_source_box.setEnabled(False)
        self.refresh_devices_button.setEnabled(False)
        self.status_label.setText("Слушаю вопрос... остановлюсь после паузы.")
        self.recognized_text.clear()

        self.thread = QThread()
        self.worker = RecognitionWorker(self.items, audio_source_id)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.partial_text.connect(self.on_partial_recognition)
        self.worker.finished.connect(self.on_recognition_finished)
        self.worker.failed.connect(self.on_recognition_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_thread)

        self.thread.start()

    def on_partial_recognition(self, text: str) -> None:
        self.recognized_text.setPlainText(text)

    def on_recognition_finished(
        self,
        recognized_text: str,
        results: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        self.recognized_text.setPlainText(recognized_text)
        self.show_results(results)
        audio_source = self.current_audio_source_label()
        log_question(
            mode="manual",
            recognized_text=recognized_text,
            results=results,
            audio_source=audio_source,
            metrics=metrics,
        )
        log_analysis(
            event="Ручное распознавание завершено",
            mode="manual",
            audio_source=audio_source,
            recognized_text=recognized_text,
            results=results,
            metrics=metrics,
        )
        self.record_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.auto_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.audio_source_box.setEnabled(True)
        self.refresh_devices_button.setEnabled(True)

        if recognized_text:
            self.status_label.setText("Готово.")
        else:
            self.status_label.setText("Речь не распознана. Попробуй еще раз.")

    def on_recognition_failed(self, error: str) -> None:
        self.record_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.auto_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.audio_source_box.setEnabled(True)
        self.refresh_devices_button.setEnabled(True)
        self.status_label.setText("Ошибка.")
        self.answer_text.setPlainText(error)
        log_analysis(
            event="Ошибка ручного распознавания",
            mode="manual",
            audio_source=self.current_audio_source_label(),
            details=error,
        )

    def toggle_auto_recognition(self) -> None:
        if self.auto_worker is None:
            self.start_auto_recognition()
        else:
            self.stop_auto_recognition()

    def start_auto_recognition(self) -> None:
        if not self.model_ready:
            self.status_label.setText("Подожди, модель еще загружается...")
            self.auto_button.setChecked(False)
            return

        audio_source_id = self.audio_source_box.currentData()
        audio_source_label = self.current_audio_source_label()
        self.record_button.setEnabled(False)
        self.audio_source_box.setEnabled(False)
        self.refresh_devices_button.setEnabled(False)
        self.auto_button.setChecked(True)
        self.auto_button.setText("AUTO ON")
        self.recognized_text.clear()

        self.auto_thread = QThread()
        self.auto_worker = AutoRecognitionWorker(
            self.items,
            audio_source_id,
            audio_source_label,
        )
        self.auto_worker.moveToThread(self.auto_thread)

        self.auto_thread.started.connect(self.auto_worker.run)
        self.auto_worker.result_ready.connect(self.on_auto_result_ready)
        self.auto_worker.status_changed.connect(self.status_label.setText)
        self.auto_worker.failed.connect(self.on_auto_failed)
        self.auto_worker.stopped.connect(self.auto_thread.quit)
        self.auto_worker.failed.connect(self.auto_thread.quit)
        self.auto_thread.finished.connect(self.cleanup_auto_thread)

        self.auto_thread.start()

    def stop_auto_recognition(self) -> None:
        if self.auto_worker is None:
            return

        self.status_label.setText("Авто: останавливаю...")
        self.auto_button.setEnabled(False)
        self.auto_worker.stop()

    def on_auto_result_ready(
        self,
        recognized_text: str,
        results: list[dict[str, Any]],
        metrics: dict[str, Any],
    ) -> None:
        self.recognized_text.setPlainText(recognized_text)
        self.show_results(results)
        audio_source = self.current_audio_source_label()
        log_question(
            mode="auto",
            recognized_text=recognized_text,
            results=results,
            audio_source=audio_source,
            metrics=metrics,
        )
        log_analysis(
            event="AUTO: вопрос распознан и найден ответ",
            mode="auto",
            audio_source=audio_source,
            recognized_text=recognized_text,
            results=results,
            metrics=metrics,
        )
        self.status_label.setText("Авто: ответ найден. Жду следующий вопрос...")

    def on_auto_failed(self, error: str) -> None:
        self.auto_button.setChecked(False)
        self.auto_button.setText("AUTO")
        self.auto_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.record_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.audio_source_box.setEnabled(True)
        self.refresh_devices_button.setEnabled(True)
        self.status_label.setText("Ошибка AUTO.")
        self.answer_text.setPlainText(error)
        log_analysis(
            event="Ошибка AUTO",
            mode="auto",
            audio_source=self.current_audio_source_label(),
            details=error,
        )

    def refresh_audio_sources(self) -> None:
        self.audio_sources = list_audio_sources()
        self.audio_source_box.clear()

        for source in self.audio_sources:
            self.audio_source_box.addItem(source.label, source.id)

        loopback_index = next(
            (
                index
                for index, source in enumerate(self.audio_sources)
                if source.kind == "loopback"
            ),
            -1,
        )
        if loopback_index >= 0:
            self.audio_source_box.setCurrentIndex(loopback_index)
        else:
            virtual_input_index = next(
                (
                    index
                    for index, source in enumerate(self.audio_sources)
                    if source.label.startswith("Системный звук / Meet")
                ),
                -1,
            )
            if virtual_input_index >= 0:
                self.audio_source_box.setCurrentIndex(virtual_input_index)

        has_sources = bool(self.audio_sources)
        self.record_button.setEnabled(has_sources and self.model_ready)
        self.auto_button.setEnabled(has_sources and self.model_ready)
        self.audio_source_box.setEnabled(has_sources)
        self.refresh_devices_button.setEnabled(True)

        if not has_sources:
            self.status_label.setText("Аудио-устройства не найдены.")

    def cleanup_thread(self) -> None:
        self.worker = None
        self.thread = None
        self.audio_source_box.setEnabled(bool(self.audio_sources))
        self.refresh_devices_button.setEnabled(True)

    def cleanup_auto_thread(self) -> None:
        self.auto_worker = None
        self.auto_thread = None
        self.auto_button.setChecked(False)
        self.auto_button.setText("AUTO")
        self.auto_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.record_button.setEnabled(self.model_ready and bool(self.audio_sources))
        self.audio_source_box.setEnabled(bool(self.audio_sources))
        self.refresh_devices_button.setEnabled(True)
        self.status_label.setText("Авто выключено.")

    def cleanup_model_thread(self) -> None:
        self.model_worker = None
        self.model_thread = None

    def search_manual_text(self) -> None:
        query = self.recognized_text.toPlainText()
        results = search(query, self.items)
        self.show_results(results)

    def search_quick_text(self) -> None:
        query = self.quick_search_input.text().strip()
        if not query:
            return

        started_at = time.perf_counter()
        self.recognized_text.setPlainText(query)
        results = search(query, self.items)
        finished_at = time.perf_counter()
        metrics = {
            "search_seconds": finished_at - started_at,
            "total_seconds": finished_at - started_at,
        }
        self.show_results(results)
        log_question(
            mode="quick-search",
            recognized_text=query,
            results=results,
            audio_source="ручной ввод",
            metrics=metrics,
        )
        log_analysis(
            event="Быстрый поиск по тексту",
            mode="quick-search",
            audio_source="ручной ввод",
            recognized_text=query,
            results=results,
            metrics=metrics,
        )
        self.status_label.setText("Найдено по быстрому поиску.")

    def current_audio_source_label(self) -> str:
        return self.audio_source_box.currentText()

    def show_results(self, results: list[dict[str, Any]]) -> None:
        self.last_results = results
        self.results_list.clear()

        if not results:
            self.answer_text.setPlainText("Ничего похожего не найдено.")
            return

        for index, result in enumerate(results):
            title = result.get("question", "")
            score = result.get("score", 0)
            item = QListWidgetItem(f"{score}% — {title}")
            item.setData(1000, index)
            self.results_list.addItem(item)

        self.results_list.setCurrentRow(0)
        self.answer_text.setHtml(format_answer_html(results[0]))

    def show_selected_result(self, item: QListWidgetItem) -> None:
        index = item.data(1000)
        if index is None:
            return

        result = self.last_results[index]
        self.answer_text.setHtml(format_answer_html(result))


def run_app() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
