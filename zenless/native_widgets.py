from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QSizePolicy, QToolButton

UI_TOOL_CONTROL = 22
UI_WINDOW_CONTROL = 22

class PromptComposer(QPlainTextEdit):
    submit = Signal()
    focus_state = Signal(bool)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_state.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_state.emit(False)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (not event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submit.emit()
            event.accept()
            return
        super().keyPressEvent(event)

class SymbolButton(QToolButton):

    def __init__(self, kind, parent=None, size=UI_TOOL_CONTROL):
        super().__init__(parent)
        self.kind = str(kind or 'more')
        self.setText('')
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName('symbolButton')

    def set_kind(self, kind):
        self.kind = str(kind or 'more')
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor('#e8e8e8' if self.isEnabled() else '#4b4b4b')
        pen = QPen(color, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = (self.width() - 1) / 2.0
        cy = (self.height() - 1) / 2.0
        k = self.kind
        if k in {'menu', 'history'}:
            painter.drawLine(QPointF(cx - 5, cy - 4), QPointF(cx + 5, cy - 4))
            painter.drawLine(QPointF(cx - 5, cy), QPointF(cx + 3, cy))
            painter.drawLine(QPointF(cx - 5, cy + 4), QPointF(cx + 5, cy + 4))
        elif k == 'add':
            painter.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
            painter.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        elif k == 'close':
            painter.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
            painter.drawLine(QPointF(cx + 3.5, cy - 3.5), QPointF(cx - 3.5, cy + 3.5))
        elif k == 'refresh':
            rect = QRectF(cx - 5.2, cy - 5.2, 10.4, 10.4)
            painter.drawArc(rect, 35 * 16, 275 * 16)
            painter.drawLine(QPointF(cx + 4, cy - 5), QPointF(cx + 6, cy - 5))
            painter.drawLine(QPointF(cx + 5, cy - 6), QPointF(cx + 5, cy - 3))
        elif k == 'map':
            p1 = QPointF(cx - 5, cy + 4)
            p2 = QPointF(cx, cy - 5)
            p3 = QPointF(cx + 5, cy + 4)
            painter.drawLine(p1, p2)
            painter.drawLine(p2, p3)
            painter.drawEllipse(p1, 1.7, 1.7)
            painter.drawEllipse(p2, 1.7, 1.7)
            painter.drawEllipse(p3, 1.7, 1.7)
        elif k == 'logs':
            for dy, width in ((-4, 10), (0, 7), (4, 10)):
                painter.drawLine(QPointF(cx - 5, cy + dy), QPointF(cx - 5 + width, cy + dy))
        elif k == 'settings':
            painter.drawLine(QPointF(cx - 6, cy - 4), QPointF(cx + 6, cy - 4))
            painter.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
            painter.drawLine(QPointF(cx - 6, cy + 4), QPointF(cx + 6, cy + 4))
            painter.setBrush(color)
            painter.drawRect(QRectF(cx - 2.5, cy - 5.5, 3, 3))
            painter.drawRect(QRectF(cx + 1, cy - 1.5, 3, 3))
            painter.drawRect(QRectF(cx - 4.5, cy + 2.5, 3, 3))
        elif k == 'fit':
            d = 5
            z = 2
            painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx - d + z, cy - d))
            painter.drawLine(QPointF(cx - d, cy - d), QPointF(cx - d, cy - d + z))
            painter.drawLine(QPointF(cx + d, cy - d), QPointF(cx + d - z, cy - d))
            painter.drawLine(QPointF(cx + d, cy - d), QPointF(cx + d, cy - d + z))
            painter.drawLine(QPointF(cx - d, cy + d), QPointF(cx - d + z, cy + d))
            painter.drawLine(QPointF(cx - d, cy + d), QPointF(cx - d, cy + d - z))
            painter.drawLine(QPointF(cx + d, cy + d), QPointF(cx + d - z, cy + d))
            painter.drawLine(QPointF(cx + d, cy + d), QPointF(cx + d, cy + d - z))
        elif k == 'external':
            painter.drawRect(QRectF(cx - 5, cy - 3, 8, 8))
            painter.drawLine(QPointF(cx, cy - 5), QPointF(cx + 5, cy - 5))
            painter.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx + 5, cy))
            painter.drawLine(QPointF(cx - 1, cy + 1), QPointF(cx + 5, cy - 5))
        elif k == 'more':
            painter.setBrush(color)
            for dx in (-4, 0, 4):
                painter.drawEllipse(QPointF(cx + dx, cy), 1.15, 1.15)
        elif k == 'attach':
            path = QPainterPath()
            path.moveTo(cx + 4, cy - 3)
            path.cubicTo(cx + 7, cy + 1, cx + 2, cy + 7, cx - 2, cy + 4)
            path.cubicTo(cx - 5, cy + 2, cx - 2, cy - 3, cx + 1, cy - 1)
            painter.drawPath(path)
        elif k == 'pet':
            painter.drawRect(QRectF(cx - 5, cy - 4, 10, 8))
            painter.drawLine(QPointF(cx - 3, cy - 4), QPointF(cx - 1, cy - 6))
            painter.drawLine(QPointF(cx + 3, cy - 4), QPointF(cx + 1, cy - 6))
            painter.drawPoint(QPointF(cx - 2, cy - 1))
            painter.drawPoint(QPointF(cx + 2, cy - 1))
        painter.end()

class OpticalTextLabel(QLabel):

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = QFontMetrics(self.font())
        bounds = metrics.tightBoundingRect(self.text())
        rect = QRectF(self.contentsRect())
        flags = self.alignment()
        if flags & Qt.AlignmentFlag.AlignHCenter:
            x = rect.center().x() - bounds.width() / 2.0 - bounds.x()
        elif flags & Qt.AlignmentFlag.AlignRight:
            x = rect.right() - bounds.width() - bounds.x()
        else:
            x = rect.left() - bounds.x()
        if flags & Qt.AlignmentFlag.AlignTop:
            y = rect.top() - bounds.y()
        elif flags & Qt.AlignmentFlag.AlignBottom:
            y = rect.bottom() - bounds.height() - bounds.y()
        else:
            y = rect.center().y() - bounds.height() / 2.0 - bounds.y()
        painter.drawText(QPointF(x, y), self.text())
        painter.end()

class WindowControlButton(QToolButton):

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = str(kind)
        self.setText('')
        self.setFixedSize(UI_WINDOW_CONTROL, UI_WINDOW_CONTROL)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName('windowCloseButton' if self.kind == 'close' else 'windowButton')

    def set_kind(self, kind):
        self.kind = str(kind)
        self.setObjectName('windowCloseButton' if self.kind == 'close' else 'windowButton')
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(QColor('#d8d8d8'), 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
        pen.setCosmetic(True)
        painter.setPen(pen)
        cx = (self.width() - 1) / 2.0
        cy = (self.height() - 1) / 2.0
        if self.kind == 'minimize':
            painter.drawLine(QPointF(QPointF(cx - 3.5, cy + 3.5)), QPointF(QPointF(cx + 3.5, cy + 3.5)))
        elif self.kind == 'maximize':
            painter.drawRect(QRectF(cx - 3.5, cy - 3.5, 7, 7))
        elif self.kind == 'restore':
            painter.drawRect(QRectF(cx - 1.5, cy - 3.5, 5, 5))
            painter.drawRect(QRectF(cx - 3.5, cy - 1.5, 5, 5))
        elif self.kind == 'close':
            painter.drawLine(QPointF(QPointF(cx - 3.5, cy - 3.5)), QPointF(QPointF(cx + 3.5, cy + 3.5)))
            painter.drawLine(QPointF(QPointF(cx + 3.5, cy - 3.5)), QPointF(QPointF(cx - 3.5, cy + 3.5)))
        painter.end()

