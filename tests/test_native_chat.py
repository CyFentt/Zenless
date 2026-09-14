from PySide6.QtWidgets import QApplication

from zenless.event_bus import CoreEvent, EventBus
from zenless.native_chat import NativeChat


class CoreStub:
    def __init__(self):
        self.events = EventBus()

    def jobs(self):
        return [{"id": "A", "title": "Alpha"}, {"id": "B", "title": "Beta"}]

    def timeline(self, job_id):
        return {"jobId": job_id, "messages": [{"role": "user", "content": job_id, "timestamp": 10}]}

    def job(self, job_id):
        return {"id": job_id, "stage": "COMPLETE"}


def test_native_history_rejects_late_snapshot():
    app = QApplication.instance() or QApplication([])
    panel = NativeChat(CoreStub())
    try:
        panel.select_job("A")
        old_generation = panel.generation
        panel.select_job("B")
        panel.on_result(f"timeline:{panel.generation}", {"jobId": "B", "messages": [{"content": "Beta", "timestamp": 1}]}, None)
        panel.on_result(f"timeline:{old_generation}", {"jobId": "A", "messages": [{"content": "Alpha", "timestamp": 1}]}, None)
        assert "Beta" in panel.transcript.toPlainText()
        assert "Alpha" not in panel.transcript.toPlainText()
        panel.on_event(CoreEvent("CHAT_MESSAGE", {"jobId": "A"}))
        assert not panel.refresh_timer.isActive()
        panel.select_job("A")
        panel.on_result(f"timeline:{panel.generation}", {"jobId": "A", "messages": [{"content": "Alpha", "timestamp": 1}]}, None)
        assert "Alpha" in panel.transcript.toPlainText()
    finally:
        panel.shutdown()
        panel.close()
        app.processEvents()


def test_native_stream_is_scoped_and_cleared_on_selection():
    app = QApplication.instance() or QApplication([])
    panel = NativeChat(CoreStub())
    try:
        panel.job_id = "A"
        panel.snapshot = {"jobId": "A", "messages": []}
        panel.on_event(CoreEvent("CHAT_STREAM_STARTED", {"jobId": "A", "messageId": "s1"}))
        panel.on_event(CoreEvent("CHAT_STREAM_DELTA", {"jobId": "B", "messageId": "s1", "delta": "wrong"}))
        panel.on_event(CoreEvent("CHAT_STREAM_DELTA", {"jobId": "A", "messageId": "s2", "delta": "wrong"}))
        panel.on_event(CoreEvent("CHAT_STREAM_DELTA", {"jobId": "A", "messageId": "s1", "delta": "Visible"}))
        panel.render_timeline(panel.snapshot)
        assert "Visible" in panel.transcript.toPlainText()
        assert "wrong" not in panel.transcript.toPlainText()
        panel.select_job("B")
        assert not panel.stream_id
        assert not panel.stream_text
        assert "Visible" not in panel.transcript.toPlainText()
    finally:
        panel.shutdown()
        panel.close()
        app.processEvents()


def test_native_historical_message_is_escaped():
    app = QApplication.instance() or QApplication([])
    panel = NativeChat(CoreStub())
    try:
        panel.job_id = "A"
        panel.render_timeline({"jobId": "A", "messages": [{"content": '<img src="https://example.invalid/secret">', "timestamp": 1}]})
        assert '<img src="https://example.invalid/secret">' in panel.transcript.toPlainText()
    finally:
        panel.shutdown()
        panel.close()
        app.processEvents()
