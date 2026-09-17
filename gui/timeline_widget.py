import math
import tempfile
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget, QToolTip, QApplication, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QCursor

from core.models import PipelineState, DialogueItem
from config import COLORS


class TimelineWidget(QWidget):
    segment_moved = Signal(int, float, float)
    segment_selected = Signal(int)
    seek_requested = Signal(float)
    split_requested = Signal(int)
    merge_requested = Signal(int)
    delete_requested = Signal(int)
    add_track_requested = Signal()
    delete_track_requested = Signal(str)
    add_clip_requested = Signal(str, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.duration = 0.0
        self.current_time = 0.0
        self.pixels_per_second = 50.0
        self.selected_index = -1

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._dragging = None       # ("start"|"end"|"body"|"playhead"|"track_header", item, drag_start_x, drag_start_val)
        self._is_hovering_playhead = False
        self._was_playing_before_drag = False
        self.colors = ["#1473E6", "#3fb950", "#d29922", "#e55353", "#a371f7", "#39c5cf", "#f778ba"]

        # Track layout parameters
        self.HEADER_WIDTH = 120
        self.RULER_HEIGHT = 26
        self.TRACK_HEIGHT = 38
        self.TRACK_GAP = 4

        # Master Audio Player
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        
        self.play_timer = QTimer(self)
        self.play_timer.setInterval(33)  # ~30fps playhead update
        self.play_timer.timeout.connect(self._on_play_timer_tick)
        self._is_playing = False

    # ── State & Layout Management ──────────────────────────────────────────────

    def populate(self, state: PipelineState):
        self.state = state
        self.set_duration(state.video_duration)
        self._recalculate_size()
        self.update()

    def set_current_time(self, t: float):
        self.current_time = max(0.0, min(self.duration if self.duration > 0 else 99999.0, t))
        self.update()

    def ensure_playhead_visible(self, margin: int = 60):
        """Keep playhead in view when scrubbing near viewport edges."""
        parent = self.parentWidget()
        if parent:
            scroll_area = parent.parentWidget()
            if isinstance(scroll_area, QScrollArea):
                px = int(self.HEADER_WIDTH + self.current_time * self.pixels_per_second)
                scroll_area.ensureVisible(px, int(self.height() / 2), margin, 0)

    def set_duration(self, d: float):
        self.duration = max(1.0, d)
        self._recalculate_size()
        self.update()

    def _recalculate_size(self):
        speakers = self._get_speaker_list()
        n_tracks = max(1, len(speakers))
        total_h = self.RULER_HEIGHT + n_tracks * (self.TRACK_HEIGHT + self.TRACK_GAP) + 20
        total_w = self.HEADER_WIDTH + int(self.duration * self.pixels_per_second) + 200
        self.setMinimumSize(total_w, total_h)

    playhead_tick = Signal(float)

    def _get_speaker_list(self) -> List[str]:
        if not self.state or not self.state.speakers:
            return ["SPEAKER_00"]
        return self.state.get_speaker_order()

    def zoom_in(self):
        self.pixels_per_second = min(300.0, self.pixels_per_second * 1.25)
        self._recalculate_size()
        self.update()

    def zoom_out(self):
        self.pixels_per_second = max(10.0, self.pixels_per_second / 1.25)
        self._recalculate_size()
        self.update()

    # ── Master Timeline Audio Playback ─────────────────────────────────────────

    def toggle_playback(self):
        if self._is_playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self):
        if not self.state:
            return
        audio_src = self.state.separated_vocals_path or self.state.work_audio_path
        if not audio_src or not audio_src.exists():
            return

        self.player.setSource(QUrl.fromLocalFile(str(audio_src)))
        self.player.setPosition(int(self.current_time * 1000))
        self.player.play()
        self.play_timer.start()
        self._is_playing = True

    def stop_playback(self):
        self.player.stop()
        self.play_timer.stop()
        self._is_playing = False

    def _on_play_timer_tick(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            pos_sec = self.player.position() / 1000.0
            self.current_time = pos_sec
            self.playhead_tick.emit(pos_sec)
            self.update()
        else:
            self.stop_playback()


    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill background
        painter.fillRect(self.rect(), QColor("#141414"))

        speakers_list = self._get_speaker_list()

        # 1. Track Lanes
        for spk_idx, spk_id in enumerate(speakers_list):
            y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP)
            track_rect = QRectF(self.HEADER_WIDTH, y_top, self.width() - self.HEADER_WIDTH, self.TRACK_HEIGHT)
            
            # Alternating track background
            bg_color = QColor("#1c1c1c") if spk_idx % 2 == 0 else QColor("#222222")
            painter.fillRect(track_rect, bg_color)
            
            # Track bottom separator line
            painter.setPen(QPen(QColor("#2a2a2a"), 1))
            painter.drawLine(self.HEADER_WIDTH, y_top + self.TRACK_HEIGHT, self.width(), y_top + self.TRACK_HEIGHT)

        # 2. Clips per Track
        if self.state:
            for item in self.state.active_dialogues():
                try:
                    spk_idx = speakers_list.index(item.speaker_id)
                except ValueError:
                    spk_idx = 0

                y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP) + 2
                h = self.TRACK_HEIGHT - 4
                x1 = self.HEADER_WIDTH + item.start * self.pixels_per_second
                w = max(4.0, item.duration * self.pixels_per_second)

                color_hex = self.colors[spk_idx % len(self.colors)]
                color = QColor(color_hex)
                color.setAlpha(200)

                clip_rect = QRectF(x1, y_top, w, h)

                if item.index == self.selected_index:
                    painter.setPen(QPen(QColor("#ffffff"), 2))
                    painter.setBrush(QBrush(color.lighter(130)))
                else:
                    painter.setPen(QPen(QColor(color_hex).darker(140), 1))
                    painter.setBrush(QBrush(color))

                painter.drawRoundedRect(clip_rect, 3, 3)

                # Trim handles visual hint on hover/select
                if item.index == self.selected_index:
                    painter.setPen(QPen(QColor("#ffffff"), 2))
                    painter.drawLine(x1 + 3, y_top + 4, x1 + 3, y_top + h - 4)
                    painter.drawLine(x1 + w - 3, y_top + 4, x1 + w - 3, y_top + h - 4)

                # Text label inside clip
                if w > 25:
                    painter.setPen(QColor("#ffffff"))
                    font = painter.font()
                    font.setPointSize(8)
                    font.setBold(True)
                    painter.setFont(font)
                    spk_name = self.state.get_speaker_safe_name(item.speaker_id)
                    label = f"#{item.index:03d} {spk_name}"
                    painter.drawText(clip_rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

        # 3. Ruler (Header)
        ruler_rect = QRectF(0, 0, self.width(), self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#1e1e1e"))
        painter.setPen(QPen(QColor("#3a3a3a"), 1))
        painter.drawLine(0, self.RULER_HEIGHT, self.width(), self.RULER_HEIGHT)

        # Ruler Ticks
        painter.setPen(QPen(QColor("#888888"), 1))
        font_ruler = painter.font()
        font_ruler.setPointSize(8)
        painter.setFont(font_ruler)

        step_sec = 5.0 if self.pixels_per_second < 80 else (1.0 if self.pixels_per_second > 150 else 2.0)
        t = 0.0
        while t <= self.duration + 10.0:
            x = self.HEADER_WIDTH + t * self.pixels_per_second
            if x > self.width():
                break
            if t % (step_sec * 2) == 0:
                painter.drawLine(x, 4, x, self.RULER_HEIGHT)
                m = int(t // 60)
                s = int(t % 60)
                painter.drawText(int(x) + 4, 15, f"{m:02d}:{s:02d}")
            else:
                painter.drawLine(x, 12, x, self.RULER_HEIGHT)
            t += step_sec

        # 4. Left Track Header (Fixed Labels: A1, A2...)
        header_rect = QRectF(0, 0, self.HEADER_WIDTH, self.height())
        painter.fillRect(header_rect, QColor("#181818"))
        painter.setPen(QPen(QColor("#2d2d2d"), 1))
        painter.drawLine(self.HEADER_WIDTH, 0, self.HEADER_WIDTH, self.height())

        # Top-left corner title
        painter.fillRect(QRectF(0, 0, self.HEADER_WIDTH, self.RULER_HEIGHT), QColor("#222222"))
        painter.setPen(QColor("#aaaaaa"))
        painter.drawText(QRectF(0, 0, self.HEADER_WIDTH, self.RULER_HEIGHT), Qt.AlignmentFlag.AlignCenter, "TRACKS")

        for spk_idx, spk_id in enumerate(speakers_list):
            y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP)
            lbl_rect = QRectF(4, y_top + 4, self.HEADER_WIDTH - 8, self.TRACK_HEIGHT - 8)
            
            color_hex = self.colors[spk_idx % len(self.colors)]
            painter.fillRect(QRectF(4, y_top + 6, 5, self.TRACK_HEIGHT - 12), QColor(color_hex))
            
            painter.setPen(QColor("#cccccc"))
            spk_name = self.state.get_speaker(spk_id).display_name if self.state else spk_id
            painter.drawText(lbl_rect.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"A{spk_idx+1}: {spk_name[:12]}")

        # 5. Playhead line & handle
        px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second
        is_active = (self._dragging and self._dragging[0] == "playhead") or self._is_hovering_playhead

        # Vertical tracking line
        line_color = QColor("#3898FF") if is_active else QColor("#1473E6")
        painter.setPen(QPen(line_color, 2))
        painter.drawLine(int(px), 0, int(px), self.height())

        # Playhead handle head on ruler (modern Adobe / DaVinci look)
        head_w = 6.0
        head_h = 12.0
        head_tip = 18.0
        head_poly = [
            QPointF(px - head_w, 0),
            QPointF(px + head_w, 0),
            QPointF(px + head_w, head_h),
            QPointF(px, head_tip),
            QPointF(px - head_w, head_h),
        ]

        handle_color = QColor("#2580EB") if is_active else QColor("#1473E6")
        painter.setBrush(QBrush(handle_color))
        painter.setPen(QPen(QColor("#FFFFFF" if is_active else "#A0C8FF"), 1.2))
        painter.drawPolygon(head_poly)

        # Center grip mark inside the handle
        painter.setPen(QPen(QColor("#FFFFFF" if is_active else "#C4DEFF"), 1.0))
        painter.drawLine(int(px), 3, int(px), int(head_h - 1))

    # ── Mouse Interaction & Cursors ─────────────────────────────────────────────

    def leaveEvent(self, event):
        if self._is_hovering_playhead:
            self._is_hovering_playhead = False
            self.update()
        super().leaveEvent(event)

    def _hit_test(self, x: float, y: float) -> Tuple[Optional[str], Optional[DialogueItem]]:
        """Returns (mode, dialogue_item) where mode in ['playhead', 'ruler', 'start', 'end', 'body', 'track', 'header']"""
        if x < self.HEADER_WIDTH:
            return "header", None

        px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second

        # 1. Playhead handle grab zone (on ruler or top edge)
        if abs(x - px) <= 8 and y <= self.RULER_HEIGHT + 4:
            return "playhead", None

        # 2. Ruler area (clicking/dragging anywhere on ruler scrubs playhead)
        if y < self.RULER_HEIGHT:
            return "ruler", None

        # 3. Clips on track lanes
        speakers_list = self._get_speaker_list()
        t = (x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second)

        for item in self.state.active_dialogues() if self.state else []:
            try:
                spk_idx = speakers_list.index(item.speaker_id)
            except ValueError:
                spk_idx = 0

            y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP)
            if y_top <= y <= y_top + self.TRACK_HEIGHT:
                if item.start <= t <= item.end:
                    edge_sec = 6.0 / max(1.0, self.pixels_per_second)
                    if t - item.start <= edge_sec:
                        return "start", item
                    elif item.end - t <= edge_sec:
                        return "end", item
                    else:
                        return "body", item

        # 4. Playhead vertical line over empty space
        if abs(x - px) <= 6:
            return "playhead", None

        # 5. Empty track area
        return "track", None

    def mousePressEvent(self, event):
        self.setFocus()
        if not self.state:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        x = event.pos().x()
        y = event.pos().y()

        mode, item = self._hit_test(x, y)

        if mode in ("playhead", "ruler", "track"):
            # Pause playback while scrubbing so it does not fight mouse dragging
            self._was_playing_before_drag = self._is_playing
            if self._is_playing:
                self.stop_playback()

            t = max(0.0, min(self.duration, (x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second)))
            self.set_current_time(t)
            self.seek_requested.emit(t)
            self.ensure_playhead_visible(margin=60)
            self.selected_index = -1
            self._dragging = ("playhead", None, x, t)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()
        elif mode == "header":
            track_idx = int((y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP))
            speakers_list = self._get_speaker_list()
            if 0 <= track_idx < len(speakers_list):
                self._dragging = ("track_header", speakers_list[track_idx], x, y)
        elif item:
            self.selected_index = item.index
            self.segment_selected.emit(item.index)
            self._dragging = (mode, item, x, item.start if mode != "end" else item.end)
            self.seek_requested.emit(item.start)

        self.update()

    def _snap_time(self, t: float, ignore_item: Optional[DialogueItem] = None) -> float:
        """Snap time value to clip boundaries or track start/end if within 10 pixels."""
        if not self.state:
            return t
        snap_thresh = 10.0 / max(1.0, self.pixels_per_second)
        candidates = [0.0, self.duration]

        for d in self.state.active_dialogues():
            if ignore_item and d.index == ignore_item.index:
                continue
            candidates.append(d.start)
            candidates.append(d.end)

        for c in candidates:
            if abs(t - c) <= snap_thresh:
                return c
        return t

    def mouseMoveEvent(self, event):
        if not self.state:
            return
        x = event.pos().x()
        y = event.pos().y()

        if self._dragging:
            mode = self._dragging[0]
            if mode == "track_header":
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                self.update()
                return

            if mode == "playhead":
                t = max(0.0, min(self.duration, (x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second)))
                self.set_current_time(t)
                self.seek_requested.emit(t)
                self.ensure_playhead_visible(margin=60)

                # Show dynamic time badge while scrubbing
                m = int(t // 60)
                s = int(t % 60)
                ms = int((t - int(t)) * 1000)
                QToolTip.showText(
                    event.globalPos(),
                    f"⏱ {m:02d}:{s:02d}.{ms:03d}",
                    self
                )
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return

            _, item, start_x, start_val = self._dragging
            dx = (x - start_x) / max(1.0, self.pixels_per_second)
            if mode == "start":
                raw = start_val + dx
                snapped = self._snap_time(raw, ignore_item=item)
                item.start = max(0.0, min(snapped, item.end - 0.1))
                self.seek_requested.emit(item.start)
            elif mode == "end":
                raw = start_val + dx
                snapped = self._snap_time(raw, ignore_item=item)
                item.end = max(item.start + 0.1, min(self.duration, snapped))
                self.seek_requested.emit(item.end)
            elif mode == "body":
                raw_start = start_val + dx
                snapped_start = self._snap_time(raw_start, ignore_item=item)
                dur = item.duration
                new_start = max(0.0, snapped_start)
                new_end = new_start + dur
                if new_end <= self.duration + 5.0:
                    item.start = new_start
                    item.end = new_end
                    self.seek_requested.emit(item.start)
                
                # Vertical drag: move clip to different speaker track
                target_spk_idx = int((y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP))
                speakers_list = self._get_speaker_list()
                if 0 <= target_spk_idx < len(speakers_list):
                    item.speaker_id = speakers_list[target_spk_idx]
            self.update()
        else:
            px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second
            is_near_playhead = (abs(x - px) <= 8 and y <= self.RULER_HEIGHT + 6) or (abs(x - px) <= 5)
            if is_near_playhead != self._is_hovering_playhead:
                self._is_hovering_playhead = is_near_playhead
                self.update()

            mode, item = self._hit_test(x, y)
            if mode in ("start", "end"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)  # Trim Cursor
            elif mode == "body":
                self.setCursor(Qt.CursorShape.SizeAllCursor)  # Move Cursor
            elif mode == "header":
                self.setCursor(Qt.CursorShape.SizeVerCursor)  # Track Drag Cursor
            elif mode == "playhead":
                self.setCursor(Qt.CursorShape.SizeHorCursor)  # Playhead Drag Cursor
            elif mode == "ruler":
                self.setCursor(Qt.CursorShape.PointingHandCursor)  # Ruler Scrub Cursor
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

            if item:
                spk_name = self.state.get_speaker_safe_name(item.speaker_id)
                QToolTip.showText(
                    event.globalPos(),
                    f"Clip #{item.index:03d} — {spk_name}\nStart: {item.format_start()}  End: {item.format_end()}  (Duration: {item.duration:.2f}s)",
                    self
                )

    def mouseReleaseEvent(self, event):
        if self._dragging:
            mode = self._dragging[0]
            if mode == "track_header":
                _, spk_id, start_x, start_y = self._dragging
                target_spk_idx = int((event.pos().y() - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP))
                speakers_list = self._get_speaker_list()
                if 0 <= target_spk_idx < len(speakers_list) and spk_id in speakers_list:
                    old_idx = speakers_list.index(spk_id)
                    if old_idx != target_spk_idx:
                        speakers_list.pop(old_idx)
                        speakers_list.insert(target_spk_idx, spk_id)
                        self.state.speaker_order = speakers_list
                        self.add_track_requested.emit()
            elif mode in ("start", "end", "body"):
                item = self._dragging[1]
                self.segment_moved.emit(item.index, item.start, item.end)
            elif mode == "playhead":
                x = event.pos().x()
                t = max(0.0, min(self.duration, (x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second)))
                self.set_current_time(t)
                self.seek_requested.emit(t)
                QToolTip.hideText()
                if self._was_playing_before_drag:
                    self.start_playback()
                    self._was_playing_before_drag = False

            self._dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    # ── Keyboard Shortcuts ─────────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_playback()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_index >= 0:
                self.delete_requested.emit(self.selected_index)
        elif key == Qt.Key.Key_S:
            if self.selected_index >= 0:
                self.split_requested.emit(self.selected_index)
        elif key == Qt.Key.Key_M:
            if self.selected_index >= 0:
                self.merge_requested.emit(self.selected_index)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key == Qt.Key.Key_Minus:
            self.zoom_out()
        elif key == Qt.Key.Key_Left:
            step = 1.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.1
            self.set_current_time(self.current_time - step)
            self.seek_requested.emit(self.current_time)
        elif key == Qt.Key.Key_Right:
            step = 1.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.1
            self.set_current_time(self.current_time + step)
            self.seek_requested.emit(self.current_time)
        else:
            super().keyPressEvent(event)
