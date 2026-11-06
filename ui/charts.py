"""Small chart widgets, drawn with QPainter (no charting library to install or ship).

* :class:`LineChart`        percentages over time, with an optional comparison line
* :class:`StackedBarChart`  focus / distracted / away hours per day or week
* :class:`HBarChart`        a ranking of people (or anything) as horizontal bars
* :class:`DonutChart`       shares of a whole, with a legend

Every chart paints with the *current theme* on screen and can be painted again onto an
image or a PDF page with the fixed :data:`PRINT_COLORS` (dark text on white), through
:meth:`BaseChart.paint_to`. Hovering a bar, point or slice shows its exact numbers.
"""
import math
from dataclasses import dataclass

from PyQt5.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QSizePolicy, QToolTip, QWidget

from ui import theme


@dataclass(frozen=True)
class ChartColors:
    background: str
    text: str
    muted: str
    grid: str
    focus: str
    distraction: str
    away: str
    accent: str
    series: tuple


#: dark text on white, for the PDF and for saved images
PRINT_COLORS = ChartColors(
    background="#FFFFFF", text="#111827", muted="#6B7280", grid="#E5E7EB", focus="#16A34A", distraction="#D97706",
    away="#DC2626", accent="#2563EB",
    series=("#2563EB", "#16A34A", "#D97706", "#9333EA", "#0891B2", "#DB2777", "#6B7280"))


def theme_colors() -> ChartColors:
    """The colours of the theme that is currently applied (read at paint time, so a theme
    switch shows on the next repaint)."""
    p = theme.CURRENT_PALETTE
    return ChartColors(
        background=p["SURFACE"], text=p["TEXT_PRIMARY"], muted=p["TEXT_MUTED"], grid=p["BORDER_SOFT"],
        focus=p["SUCCESS"], distraction=p["WARNING"], away=p["DANGER"], accent=p["ACCENT"],
        series=(p["ACCENT"], p["SUCCESS"], p["WARNING"], "#A78BFA", p["INFO"], "#F472B6", p["TEXT_MUTED"]))


def nice_ceiling(value: float) -> float:
    """A round axis maximum at or above ``value`` (1, 2, 5, 10, 20, 50 ...)."""
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * 10 ** exponent >= value:
            return step * 10 ** exponent
    return 10 ** (exponent + 1)


def hours_text(hours: float) -> str:
    """3.17 -> '3h 10m'."""
    total_minutes = int(round(hours * 60))
    return f"{total_minutes // 60}h {total_minutes % 60:02d}m" if total_minutes >= 60 else f"{total_minutes}m"


class BaseChart(QWidget):
    """Common plumbing: painting with a colour set, hover tooltips, an "empty" message."""

    EMPTY_TEXT = "No data for this period"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(220)
        self._hits = []                 # [(QRectF, tooltip text)] of the last paint

    # -- to override
    def has_data(self) -> bool:
        return False

    def draw(self, painter: QPainter, rect: QRectF, colors: ChartColors, hits: list) -> None:
        raise NotImplementedError

    # -- painting
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self._hits = []
        self._paint(painter, QRectF(self.rect()), theme_colors(), self._hits, fill=False)

    def paint_to(self, painter: QPainter, rect: QRectF, colors: ChartColors = PRINT_COLORS) -> None:
        """Paint the chart into ``rect`` of any painter (an image, a PDF page) with ``colors``."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint(painter, rect, colors, [], fill=True)
        painter.restore()

    def to_image(self, width: int = 900, height: int = 420, colors: ChartColors = PRINT_COLORS) -> QImage:
        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(colors.background))
        painter = QPainter(image)
        self.paint_to(painter, QRectF(0, 0, width, height), colors)
        painter.end()
        return image

    def _paint(self, painter, rect, colors, hits, fill):
        if fill:
            painter.fillRect(rect, QColor(colors.background))
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, font.pointSizeF() if font.pointSizeF() > 0 else 9.0))
        painter.setFont(font)
        if not self.has_data():
            painter.setPen(QColor(colors.muted))
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.EMPTY_TEXT)
            return
        self.draw(painter, rect, colors, hits)

    def changeEvent(self, event):
        if event.type() in (QEvent.StyleChange, QEvent.PaletteChange, QEvent.FontChange):
            self.update()                       # a theme switch shows at once
        super().changeEvent(event)

    # -- hover
    def mouseMoveEvent(self, event):
        for area, text in self._hits:
            if area.contains(QPointF(event.pos())):
                QToolTip.showText(event.globalPos(), text, self)
                return
        QToolTip.hideText()

    def leaveEvent(self, _event):
        QToolTip.hideText()

    # -- helpers for subclasses
    @staticmethod
    def text(painter, colors, x, y, w, h, text, align=Qt.AlignLeft | Qt.AlignVCenter, muted=True, bold=False):
        painter.setPen(QColor(colors.muted if muted else colors.text))
        font = QFont(painter.font())
        font.setBold(bold)
        painter.setFont(font)
        painter.drawText(QRectF(x, y, w, h), align, text)

    @staticmethod
    def legend(painter, colors, x, y, items):
        """Colour dots with captions in a row starting at (x, y); returns the used width."""
        metrics = QFontMetricsF(painter.font())
        cursor = x
        for caption, color in items:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(cursor + 5, y + 8), 4.5, 4.5)
            painter.setPen(QColor(colors.muted))
            painter.drawText(QPointF(cursor + 15, y + 12), caption)
            cursor += 15 + metrics.horizontalAdvance(caption) + 16
        return cursor - x


class LineChart(BaseChart):
    """A percentage (0-100) over time; ``compare`` draws a dashed second line (for example the team).

    A ``None`` value means "no data" and leaves a gap in the line (it is not the same as 0 %)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels, self.values, self.compare = [], [], None
        self.name, self.compare_name, self.unit = "Focus", "Team average", "%"

    def set_series(self, labels, values, compare=None, name="Focus", compare_name="Team average", unit="%"):
        self.labels, self.values, self.compare = list(labels), list(values), list(compare) if compare else None
        self.name, self.compare_name, self.unit = name, compare_name, unit
        self.setAccessibleDescription(
            f"{name} over time: " + ", ".join(f"{l} {'no data' if v is None else str(v) + unit}"
                                              for l, v in zip(self.labels, self.values)))
        self.update()

    def has_data(self):
        return any(v is not None for v in self.values)

    def draw(self, painter, rect, colors, hits):
        left, right, top, bottom = 44, 14, 30, 30
        plot = QRectF(rect.left() + left, rect.top() + top, rect.width() - left - right, rect.height() - top - bottom)
        self.legend(painter, colors, rect.left() + left, rect.top() + 4,
                    [(self.name, colors.accent)] + ([(self.compare_name, colors.muted)] if self.compare else []))
        for tick in (0, 25, 50, 75, 100):
            y = plot.bottom() - plot.height() * tick / 100
            painter.setPen(QPen(QColor(colors.grid), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            self.text(painter, colors, rect.left(), y - 8, left - 6, 16, f"{tick}{self.unit}", Qt.AlignRight | Qt.AlignVCenter)
        count = len(self.values)
        step = plot.width() / max(count - 1, 1)
        x_of = (lambda i: plot.left() + step * i) if count > 1 else (lambda i: plot.center().x())
        every = max(1, math.ceil(count / 8))
        for i, label in enumerate(self.labels):
            if i % every == 0 or i == count - 1:
                label_x = min(max(x_of(i) - 30, rect.left()), rect.right() - 60)     # keep it inside the widget
                self.text(painter, colors, label_x, plot.bottom() + 6, 60, 18, label, Qt.AlignHCenter | Qt.AlignTop)

        def points(values):
            """One QPointF per value, or None where there is no data (a gap, not a zero)."""
            return [None if v is None else
                    QPointF(x_of(i), plot.bottom() - plot.height() * min(max(v, 0), 100) / 100)
                    for i, v in enumerate(values)]

        def runs(pts):
            """Consecutive points without a gap."""
            run = []
            for point in pts:
                if point is None:
                    if run:
                        yield run
                    run = []
                else:
                    run.append(point)
            if run:
                yield run

        if self.compare:
            painter.setPen(QPen(QColor(colors.muted), 1.6, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            for run in runs(points(self.compare)):
                if len(run) > 1:
                    self._polyline(painter, run)
        main = points(self.values)
        fill = QColor(colors.accent)
        fill.setAlpha(36)
        for run in runs(main):
            if len(run) > 1:
                area = QPainterPath(QPointF(run[0].x(), plot.bottom()))
                for point in run:
                    area.lineTo(point)
                area.lineTo(QPointF(run[-1].x(), plot.bottom()))
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawPath(area)
                painter.setPen(QPen(QColor(colors.accent), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                self._polyline(painter, run)
        painter.setPen(QPen(QColor(colors.accent), 2.0))
        painter.setBrush(QColor(colors.background))
        for i, point in enumerate(main):
            x = x_of(i)
            if point is None:
                tip = f"{self.labels[i]}: no data"
            else:
                painter.drawEllipse(point, 3.2, 3.2)
                tip = f"{self.labels[i]}: {self.values[i]}{self.unit}"
            if self.compare and self.compare[i] is not None:
                tip += f"\n{self.compare_name}: {self.compare[i]}{self.unit}"
            hits.append((QRectF(x - max(step / 2, 6), plot.top(), max(step, 12), plot.height()), tip))

    @staticmethod
    def _polyline(painter, points):
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        painter.drawPath(path)


class StackedBarChart(BaseChart):
    """Stacked columns per bucket. By default focus / distracted / away *hours*; with ``unit=""``
    and other ``names`` / ``keys`` it shows counts (for example present / absent people)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels, self.rows = [], []
        self.names, self.keys, self.unit = ("Focus", "Distracted", "Away"), ("focus", "distraction", "away"), "h"

    def set_rows(self, labels, rows, names=("Focus", "Distracted", "Away"), keys=("focus", "distraction", "away"),
                 unit="h"):
        """``rows`` hold one number per name for each label (hours by default)."""
        self.labels, self.rows = list(labels), [tuple(float(x) for x in row) for row in rows]
        self.names, self.keys, self.unit = tuple(names), tuple(keys), unit
        self.setAccessibleDescription("Per period (" + ", ".join(names) + "): " + "; ".join(
            f"{l}: " + ", ".join(self._format(v) for v in r) for l, r in zip(self.labels, self.rows)))
        self.update()

    def _format(self, value):
        return hours_text(value) if self.unit == "h" else f"{value:g}"

    def has_data(self):
        return any(sum(row) > 0 for row in self.rows)

    def draw(self, painter, rect, colors, hits):
        left, right, top, bottom = 44, 14, 30, 30
        plot = QRectF(rect.left() + left, rect.top() + top, rect.width() - left - right, rect.height() - top - bottom)
        shades = [getattr(colors, key) for key in self.keys]
        self.legend(painter, colors, rect.left() + left, rect.top() + 4, list(zip(self.names, shades)))
        top_value = nice_ceiling(max(sum(row) for row in self.rows))
        for fraction in (0, 0.25, 0.5, 0.75, 1):
            y = plot.bottom() - plot.height() * fraction
            painter.setPen(QPen(QColor(colors.grid), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            self.text(painter, colors, rect.left(), y - 8, left - 6, 16, f"{top_value * fraction:g}{self.unit}",
                      Qt.AlignRight | Qt.AlignVCenter)
        count = len(self.rows)
        slot = plot.width() / count
        width = min(slot * 0.62, 46)
        every = max(1, math.ceil(count / 8))
        for i, (row, label) in enumerate(zip(self.rows, self.labels)):
            x = plot.left() + slot * i + (slot - width) / 2
            y = plot.bottom()
            for value, color in zip(row, shades):
                height = plot.height() * value / top_value
                if height > 0.4:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(color))
                    painter.drawRoundedRect(QRectF(x, y - height, width, height), 2, 2)
                    y -= height
            tip = label + "".join(f"\n{name} {self._format(value)}" for name, value in zip(self.names, row))
            hits.append((QRectF(x - 3, plot.top(), width + 6, plot.height()), tip))
            if i % every == 0 or i == count - 1:
                label_x = min(max(plot.left() + slot * i + slot / 2 - 40, rect.left()), rect.right() - 80)
                self.text(painter, colors, label_x, plot.bottom() + 6, 80, 18, label, Qt.AlignHCenter | Qt.AlignTop)


class HBarChart(BaseChart):
    """Horizontal bars, one per row: ``(label, value, caption)``; values are 0-100 by default."""

    ROW = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.maximum, self.color_key = [], 100.0, "focus"

    def set_rows(self, rows, maximum=100.0, color_key="focus"):
        self.rows, self.maximum, self.color_key = list(rows), float(maximum) or 1.0, color_key
        self.setMinimumHeight(max(120, self.ROW * len(self.rows) + 16))
        self.setAccessibleDescription("Ranking: " + "; ".join(f"{label} {caption}" for label, _v, caption in self.rows))
        self.update()

    def has_data(self):
        return bool(self.rows)

    def sizeHint(self):
        return QSize(400, max(120, self.ROW * len(self.rows) + 16))

    def draw(self, painter, rect, colors, hits):
        label_width = min(150, rect.width() * 0.32)
        metrics = QFontMetricsF(painter.font())
        # the caption column is as wide as the longest caption (but never more than a third of the chart)
        caption_width = min(max([74.0] + [metrics.horizontalAdvance(c) + 8 for _l, _v, c in self.rows]),
                            rect.width() * 0.34)
        track = QRectF(rect.left() + label_width + 8, 0, rect.width() - label_width - caption_width - 20, 12)
        color = QColor(getattr(colors, self.color_key))
        for i, (label, value, caption) in enumerate(self.rows):
            y = rect.top() + 8 + self.ROW * i
            painter.setPen(QColor(colors.text))
            painter.drawText(QRectF(rect.left(), y, label_width, self.ROW - 8), Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(str(label), Qt.ElideRight, label_width))
            bar = QRectF(track.left(), y + (self.ROW - 8 - 12) / 2, track.width(), 12)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors.grid))
            painter.drawRoundedRect(bar, 6, 6)
            filled = QRectF(bar.left(), bar.top(), bar.width() * min(max(value, 0), self.maximum) / self.maximum, 12)
            if filled.width() > 0:
                painter.setBrush(color)
                painter.drawRoundedRect(filled, 6, 6)
            painter.setPen(QColor(colors.muted))
            painter.drawText(QRectF(bar.right() + 8, y, caption_width, self.ROW - 8), Qt.AlignLeft | Qt.AlignVCenter, caption)
            hits.append((QRectF(rect.left(), y, rect.width(), self.ROW - 4), f"{label}: {caption}"))


class DonutChart(BaseChart):
    """Shares of a whole: ``(label, value, caption)`` slices, a centre total and a legend."""

    MAX_SLICES = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.slices, self.center = [], ""

    def set_slices(self, slices, center=""):
        ordered = sorted(slices, key=lambda s: -s[1])
        if len(ordered) > self.MAX_SLICES:
            rest = ordered[self.MAX_SLICES - 1:]
            ordered = ordered[:self.MAX_SLICES - 1] + [("Other", sum(s[1] for s in rest), f"{len(rest)} more")]
        self.slices, self.center = ordered, center
        self.setAccessibleDescription("Shares: " + "; ".join(f"{l} {c}" for l, _v, c in self.slices))
        self.update()

    def has_data(self):
        return sum(max(v, 0) for _l, v, _c in self.slices) > 0

    def draw(self, painter, rect, colors, hits):
        total = sum(max(v, 0) for _l, v, _c in self.slices)
        size = min(rect.height() - 16, rect.width() * 0.46)
        ring = QRectF(rect.left() + 12, rect.center().y() - size / 2, size, size)
        thickness = size * 0.22
        angle = 90 * 16
        metrics = QFontMetricsF(painter.font())
        legend_x = ring.right() + 24
        legend_row = 26
        legend_y = rect.center().y() - legend_row * len(self.slices) / 2
        for i, (label, value, caption) in enumerate(self.slices):
            color = QColor(colors.series[i % len(colors.series)])
            span = -int(round(360 * 16 * max(value, 0) / total))
            painter.setPen(QPen(color, thickness, Qt.SolidLine, Qt.FlatCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(ring.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2), angle, span)
            angle += span
            y = legend_y + legend_row * i
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(legend_x, y + 5, 12, 12), 3, 3)
            painter.setPen(QColor(colors.text))
            text_width = rect.right() - legend_x - 150
            painter.drawText(QRectF(legend_x + 20, y, max(text_width, 40), 22), Qt.AlignLeft | Qt.AlignVCenter,
                             metrics.elidedText(str(label), Qt.ElideRight, max(text_width, 40)))
            painter.setPen(QColor(colors.muted))
            painter.drawText(QRectF(rect.right() - 130, y, 130, 22), Qt.AlignRight | Qt.AlignVCenter, caption)
            hits.append((QRectF(legend_x, y, rect.right() - legend_x, 22), f"{label}: {caption}"))
        if self.center:
            self.text(painter, colors, ring.left(), ring.center().y() - 16, ring.width(), 32, self.center,
                      Qt.AlignCenter, muted=False, bold=True)
