import sys
import traceback
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.audio_recorder import record_question
from app.qa_loader import load_questions
from app.search_engine import format_answer, search
from app.speech_to_text import transcribe_audio


class RecognitionWorker(QObject):
    finished = Signal(str, list)
    failed = Signal(str)

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__()
        self.items = items

    def run(self) -> None:
        try:
            audio_path = record_question()
            recognized_text = transcribe_audio(audio_path)
            results = search(recognized_text, self.items)
            self.finished.emit(recognized_text, results)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.items = load_questions()
        self.thread: QThread | None = None
        self.worker: RecognitionWorker | None = None
        self.last_results: list[dict[str, Any]] = []

        self.setWindowTitle("Interview Assistant - Unity / C#")
        self.resize(1100, 700)

        self.record_button = QPushButton("Записать вопрос")
        self.record_button.clicked.connect(self.start_recognition)

        self.status_label = QLabel(f"Загружено вопросов: {len(self.items)}")

        self.recognized_text = QPlainTextEdit()
        self.recognized_text.setPlaceholderText("Здесь появится распознанный текст...")
        self.recognized_text.setReadOnly(False)

        self.manual_search_button = QPushButton("Найти по тексту")
        self.manual_search_button.clicked.connect(self.search_manual_text)

        self.answer_text = QPlainTextEdit()
        self.answer_text.setPlaceholderText("Здесь появится ответ...")
        self.answer_text.setReadOnly(True)

        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.show_selected_result)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Распознанный вопрос"))
        left_layout.addWidget(self.recognized_text)
        left_layout.addWidget(self.manual_search_button)
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
        top_layout.addWidget(self.record_button)
        top_layout.addWidget(self.status_label)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(splitter)

        self.setCentralWidget(central)

    def start_recognition(self) -> None:
        self.record_button.setEnabled(False)
        self.status_label.setText("Запись и распознавание... говори вопрос.")

        self.thread = QThread()
        self.worker = RecognitionWorker(self.items)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_recognition_finished)
        self.worker.failed.connect(self.on_recognition_failed)

        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup_thread)

        self.thread.start()

    def on_recognition_finished(
        self,
        recognized_text: str,
        results: list[dict[str, Any]],
    ) -> None:
        self.recognized_text.setPlainText(recognized_text)
        self.show_results(results)
        self.record_button.setEnabled(True)

        if recognized_text:
            self.status_label.setText("Готово.")
        else:
            self.status_label.setText("Речь не распознана. Попробуй еще раз.")

    def on_recognition_failed(self, error: str) -> None:
        self.record_button.setEnabled(True)
        self.status_label.setText("Ошибка.")
        self.answer_text.setPlainText(error)

    def cleanup_thread(self) -> None:
        self.worker = None
        self.thread = None

    def search_manual_text(self) -> None:
        query = self.recognized_text.toPlainText()
        results = search(query, self.items)
        self.show_results(results)

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
        self.answer_text.setPlainText(format_answer(results[0]))

    def show_selected_result(self, item: QListWidgetItem) -> None:
        index = item.data(1000)
        if index is None:
            return

        result = self.last_results[index]
        self.answer_text.setPlainText(format_answer(result))


def run_app() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())