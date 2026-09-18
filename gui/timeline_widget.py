import math
import tempfile
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QWidget, QToolTip, QApplication, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QCursor, QFontMetrics, QLinearGradient

from core.models import PipelineState, DialogueItem
from config import COLORS, SPEAKER_PALETTE


class TimelineWidget(QWidget):
    segment_moved = Signal(int, float, float)
    segment_selected = Signal(int)
    seek_requested = Signal(float)
    split_requested = Signal(int)
    split_at_playhead_requested = Signal()
    trim_left_requested = Signal()
    trim_right_requested = Signal()
    merge_requested = Signal(int)
    delete_requested = Signal(int)
    add_track_requested = Signal()
    delete_track_requested = Signal(str)
    track_renamed = Signal(str, str)
    undo_requested = Signal()
    redo_requested = Signal()
    add_clip_requested = Signal(str, float)
    tracks_reordered = Signal()
    sticky_headers_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = None
        self.duration = 0.0
        self.current_time = 0.0
        self.pixels_per_second = 50.0
        self.selected_index = -1
        self.sticky_headers = True
        self._is_hovering_pin = False
        self._scroll_connected = False
        self._last_scrub_seek_time = 0.0

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._dragging = None       # ("start"|"end"|"body"|"playhead"|"track_header", item, drag_start_x, drag_start_val, ...)
        self._is_hovering_playhead = False
        self._was_playing_before_drag = False
        
        # Middle Mouse Button (MMB) 2D Pan State
        self._is_panning = False
        self._pan_start_pos = QPoint()
        self._pan_start_h = 0
        self._pan_start_v = 0

        # Distinct colors for each speaker track (unified with speaker panel)
        self.colors = list(SPEAKER_PALETTE)


        # Professional NLE Track layout parameters
        self.HEADER_WIDTH = 136
        self.RULER_HEIGHT = 28
        self.TRACK_HEIGHT = 48
        self.TRACK_GAP = 5

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

    def _get_scroll_area(self) -> Optional[QScrollArea]:
        parent = self.parentWidget()
        if parent:
            grandparent = parent.parentWidget()
            if isinstance(grandparent, QScrollArea):
                return grandparent
            if isinstance(parent, QScrollArea):
                return parent
        return None

    def set_sticky_headers(self, enabled: bool):
        if self.sticky_headers != enabled:
            self.sticky_headers = enabled
            self.update()

    def toggle_sticky_headers(self):
        self.sticky_headers = not self.sticky_headers
        self.sticky_headers_toggled.emit(self.sticky_headers)
        self.update()

    def _get_header_x(self) -> int:
        if not self.sticky_headers:
            return 0
        scroll_area = self._get_scroll_area()
        if scroll_area:
            return scroll_area.horizontalScrollBar().value()
        return 0

    def _ensure_scroll_connected(self):
        scroll_area = self._get_scroll_area()
        if scroll_area and not self._scroll_connected:
            scroll_area.horizontalScrollBar().valueChanged.connect(self._on_horizontal_scroll)
            self._scroll_connected = True

    def _on_horizontal_scroll(self, val: int):
        if self.sticky_headers:
            self.update()

    def ensure_playhead_visible(self, margin: int = 60):
        """Keep playhead in horizontal view when scrubbing near viewport edges without altering vertical scroll."""
        scroll_area = self._get_scroll_area()
        if scroll_area:
            h_bar = scroll_area.horizontalScrollBar()
            vp_w = scroll_area.viewport().width()
            px = int(self.HEADER_WIDTH + self.current_time * self.pixels_per_second)
            cur_scroll_x = h_bar.value()

            # Strictly adjust horizontal scroll ONLY; never disturb vertical Y scroll position!
            if px < cur_scroll_x + margin:
                h_bar.setValue(max(0, px - margin))
            elif px > cur_scroll_x + vp_w - margin:
                h_bar.setValue(min(h_bar.maximum(), px - vp_w + margin))

    def set_duration(self, d: float):
        self.duration = max(1.0, d)
        self._recalculate_size()
        self.update()

    def _recalculate_size(self):
        speakers = self._get_speaker_list()
        n_tracks = max(1, len(speakers))
        total_h = self.RULER_HEIGHT + n_tracks * (self.TRACK_HEIGHT + self.TRACK_GAP) + 30
        total_w = self.HEADER_WIDTH + int(self.duration * self.pixels_per_second) + 350
        self.setMinimumSize(total_w, total_h)

    playhead_tick = Signal(float)

    def _get_speaker_list(self) -> List[str]:
        if not self.state or not self.state.speakers:
            return ["SPEAKER_00"]
        return self.state.get_speaker_order()

    def zoom_in(self):
        self._zoom_by_factor(1.25)

    def zoom_out(self):
        self._zoom_by_factor(1.0 / 1.25)

    def _zoom_by_factor(self, factor: float, center_time: Optional[float] = None):
        """Zoom timeline by factor keeping center_time (or current playhead) anchored in view."""
        if center_time is None:
            center_time = self.current_time
        scroll_area = self._get_scroll_area()
        old_pps = self.pixels_per_second
        new_pps = max(10.0, min(500.0, old_pps * factor))
        if abs(new_pps - old_pps) < 0.05:
            return

        self.pixels_per_second = new_pps
        self._recalculate_size()

        if scroll_area:
            h_bar = scroll_area.horizontalScrollBar()
            vp_w = scroll_area.viewport().width()
            target_x = int(self.HEADER_WIDTH + center_time * new_pps)
            h_bar.setValue(max(0, target_x - int(vp_w / 2)))

        self.update()

    def wheelEvent(self, event):
        """
        NLE Standard Wheel Controls:
        - Ctrl + Wheel / Alt + Wheel : Zoom Timeline horizontally (anchored at cursor)
        - Shift + Wheel              : Scroll Timeline horizontally (left / right)
        - Plain Wheel                : Scroll tracks vertically (if overflow) or horizontally
        """
        angle = event.angleDelta()
        y_delta = angle.y()
        x_delta = angle.x()
        modifiers = event.modifiers()
        scroll_area = self._get_scroll_area()

        # 1. Ctrl + Wheel OR Alt + Wheel: Zoom Timeline horizontally (centered at mouse position!)
        if (modifiers & Qt.KeyboardModifier.ControlModifier) or (modifiers & Qt.KeyboardModifier.AltModifier):
            if y_delta == 0:
                event.accept()
                return

            mouse_x = event.position().x()
            time_under_mouse = max(0.0, (mouse_x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second))

            zoom_factor = 1.18 if y_delta > 0 else (1.0 / 1.18)
            new_pps = max(10.0, min(500.0, self.pixels_per_second * zoom_factor))

            if abs(new_pps - self.pixels_per_second) > 0.05:
                old_h = scroll_area.horizontalScrollBar().value() if scroll_area else 0
                self.pixels_per_second = new_pps
                self._recalculate_size()

                if scroll_area:
                    new_mouse_x = self.HEADER_WIDTH + time_under_mouse * self.pixels_per_second
                    delta_x = int(new_mouse_x - mouse_x)
                    scroll_area.horizontalScrollBar().setValue(old_h + delta_x)

                self.update()
            event.accept()
            return

        # 2. Shift + Wheel: Scroll Timeline horizontally (ขยับซ้าย-ขวา)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            if scroll_area:
                step = -int(y_delta * 0.85)
                h_bar = scroll_area.horizontalScrollBar()
                h_bar.setValue(h_bar.value() + step)
            event.accept()
            return

        # 3. Horizontal Tilt Wheel (mice with horizontal wheel)
        if x_delta != 0:
            if scroll_area:
                step = -int(x_delta * 0.85)
                scroll_area.horizontalScrollBar().setValue(scroll_area.horizontalScrollBar().value() + step)
            event.accept()
            return

        # 4. Plain Vertical Wheel (no modifier):
        if scroll_area:
            v_bar = scroll_area.verticalScrollBar()
            if v_bar and v_bar.maximum() > 0:
                step = -int(y_delta * 0.6)
                v_bar.setValue(v_bar.value() + step)
            else:
                step = -int(y_delta * 0.85)
                scroll_area.horizontalScrollBar().setValue(scroll_area.horizontalScrollBar().value() + step)
        event.accept()

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

        target_url = QUrl.fromLocalFile(str(audio_src))
        if self.player.source() != target_url:
            self.player.setSource(target_url)
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
        self._ensure_scroll_connected()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Fill deep matte neutral dark background (matching website #1e1e1e)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        speakers_list = self._get_speaker_list()

        # Empty state prompt
        if not self.state or not self.state.dialogues:
            painter.setPen(QColor("#777777"))
            font_empty = QFont("Segoe UI", 9)
            painter.setFont(font_empty)
            empty_rect = QRectF(self.HEADER_WIDTH, self.RULER_HEIGHT, self.width() - self.HEADER_WIDTH, self.height() - self.RULER_HEIGHT)
            painter.drawText(empty_rect, Qt.AlignmentFlag.AlignCenter, "Import a video file or audio to display dialogue clips on the timeline")

        # Check if dragging a clip to highlight target track lane
        active_drag_spk_idx = -1
        if self._dragging and self._dragging[0] == "body" and self.state:
            drag_item = self._dragging[1]
            if drag_item and drag_item.speaker_id in speakers_list:
                active_drag_spk_idx = speakers_list.index(drag_item.speaker_id)

        # Check if dragging a track header to dim the lifted track
        dragged_track_spk_id = self._dragging[1] if (self._dragging and self._dragging[0] == "track_header") else None

        # 2. Track Lanes (Alternating neutral dark shades + subtle border)
        for spk_idx, spk_id in enumerate(speakers_list):
            y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP)
            track_rect = QRectF(self.HEADER_WIDTH, y_top, self.width() - self.HEADER_WIDTH, self.TRACK_HEIGHT)

            is_lifted_track = (spk_id == dragged_track_spk_id)
            bg_color = QColor("#141414") if is_lifted_track else (QColor("#242424") if spk_idx % 2 == 0 else QColor("#1e1e1e"))
            painter.fillRect(track_rect, bg_color)

            # Subtle highlight track lane if clip is currently being dragged over it
            if spk_idx == active_drag_spk_idx:
                painter.fillRect(track_rect, QColor(255, 255, 255, 10))
                painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
                painter.drawRect(track_rect)

            # Bottom separator line
            painter.setPen(QPen(QColor("#2d2d2d"), 1))
            painter.drawLine(self.HEADER_WIDTH, int(y_top + self.TRACK_HEIGHT), self.width(), int(y_top + self.TRACK_HEIGHT))

        # 3. Dynamic Ruler Ticks & Track Guidelines
        pps = self.pixels_per_second
        if pps >= 150:
            major_step = 1.0
            minor_step = 0.2
        elif pps >= 80:
            major_step = 2.0
            minor_step = 0.5
        elif pps >= 35:
            major_step = 5.0
            minor_step = 1.0
        elif pps >= 15:
            major_step = 10.0
            minor_step = 2.0
        else:
            major_step = 30.0
            minor_step = 5.0

        font_ruler = QFont("Segoe UI", 8)
        painter.setFont(font_ruler)

        t = 0.0
        max_t = self.duration + 30.0
        while t <= max_t:
            x = self.HEADER_WIDTH + t * pps
            if x > self.width():
                break

            is_major = (round(t / major_step) * major_step == round(t, 4))

            if is_major:
                # Downward subtle track guideline across all tracks
                if t > 0:
                    painter.setPen(QPen(QColor(255, 255, 255, 12), 1, Qt.PenStyle.DashLine))
                    painter.drawLine(int(x), self.RULER_HEIGHT, int(x), self.height())

                # Major tick line on ruler
                painter.setPen(QPen(QColor("#888888"), 1))
                painter.drawLine(int(x), self.RULER_HEIGHT - 10, int(x), self.RULER_HEIGHT)

                # Timecode text on ruler
                m = int(t // 60)
                s = int(t % 60)
                ms = int(round((t - int(t)) * 10))
                tc_text = f"{m:02d}:{s:02d}.{ms:01d}" if major_step < 1.0 else f"{m:02d}:{s:02d}"
                painter.setPen(QColor("#aaaaaa"))
                painter.drawText(int(x) + 4, 16, tc_text)
            else:
                # Minor tick line
                painter.setPen(QPen(QColor("#444444"), 1))
                painter.drawLine(int(x), self.RULER_HEIGHT - 5, int(x), self.RULER_HEIGHT)

            t = round(t + minor_step, 4)

        # 4. Dialogue Clips per Track (Waveform + Gradient + Clean Typography)
        if self.state:
            for item in self.state.active_dialogues():
                try:
                    spk_idx = speakers_list.index(item.speaker_id)
                except ValueError:
                    spk_idx = 0

                y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP) + 3
                h = self.TRACK_HEIGHT - 6
                x1 = self.HEADER_WIDTH + item.start * self.pixels_per_second
                w = max(4.0, item.duration * self.pixels_per_second)

                color_hex = self.colors[spk_idx % len(self.colors)]
                base_color = QColor(color_hex)
                is_sel = (item.index == self.selected_index)

                # Clip rect with 1.5px right margin so adjacent clips are distinctly separated
                clip_rect = QRectF(x1, y_top, max(3.0, w - 1.5), h)

                # Vertical gradient for clip background
                grad = QLinearGradient(x1, y_top, x1, y_top + h)
                if is_sel:
                    grad.setColorAt(0.0, base_color.lighter(135))
                    grad.setColorAt(1.0, base_color.lighter(105))
                else:
                    grad.setColorAt(0.0, base_color.lighter(110))
                    grad.setColorAt(1.0, base_color.darker(115))

                painter.setBrush(QBrush(grad))
                if is_sel:
                    painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
                else:
                    painter.setPen(QPen(base_color.darker(135), 1.0))

                painter.drawRoundedRect(clip_rect, 4.0, 4.0)

                # Top subtle highlight line
                painter.setPen(QPen(QColor(255, 255, 255, 55 if is_sel else 25), 1.0))
                painter.drawLine(int(x1 + 4), int(y_top + 1), int(x1 + w - 5), int(y_top + 1))

                # Stylized audio waveform in bottom half of clip
                wave_h = h * 0.42
                wave_y = y_top + h - wave_h - 4
                wave_w = w - 10
                if wave_w > 12:
                    painter.setPen(Qt.PenStyle.NoPen)
                    wave_color = QColor(255, 255, 255, 45 if is_sel else 28)
                    painter.setBrush(QBrush(wave_color))
                    n_bars = int(wave_w // 3)
                    bar_x = x1 + 5
                    for b_idx in range(n_bars):
                        progress = b_idx / max(1, n_bars)
                        env = math.sin(progress * math.pi)
                        freq = math.sin(b_idx * 0.75 + item.index * 1.9) * 0.5 + 0.5
                        bh = max(2.0, wave_h * env * freq)
                        by = wave_y + (wave_h - bh) / 2.0
                        painter.drawRect(QRectF(bar_x, by, 1.8, bh))
                        bar_x += 3.0

                # Selected clip trim handles at ends
                if is_sel and w > 12:
                    painter.setPen(QPen(QColor("#FFFFFF"), 2.0))
                    painter.drawLine(int(x1 + 3), int(y_top + 6), int(x1 + 3), int(y_top + h - 6))
                    painter.drawLine(int(x1 + w - 4), int(y_top + 6), int(x1 + w - 4), int(y_top + h - 6))

                # Typography inside clip with text elision
                avail_w = w - 12
                if avail_w > 16:
                    painter.setPen(QColor("#FFFFFF"))
                    font_bold = QFont("Segoe UI", 8, QFont.Weight.Bold)
                    font_reg = QFont("Segoe UI", 7.5)
                    fm_bold = QFontMetrics(font_bold)
                    spk_name = self.state.get_speaker_safe_name(item.speaker_id)

                    if avail_w > 110 and h >= 38:
                        painter.setFont(font_bold)
                        title_text = f"#{item.index:03d} {spk_name}"
                        elided_title = fm_bold.elidedText(title_text, Qt.TextElideMode.ElideRight, int(avail_w))
                        painter.drawText(QRectF(x1 + 6, y_top + 4, avail_w, 15), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_title)

                        if item.caption:
                            painter.setFont(font_reg)
                            painter.setPen(QColor("#E2E8F0"))
                            fm_reg = QFontMetrics(font_reg)
                            elided_cap = fm_reg.elidedText(f'"{item.caption}"', Qt.TextElideMode.ElideRight, int(avail_w))
                            painter.drawText(QRectF(x1 + 6, y_top + 19, avail_w, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_cap)
                    else:
                        painter.setFont(font_bold)
                        if avail_w < 50:
                            label = f"#{item.index:03d}"
                        else:
                            label = f"#{item.index:03d} {spk_name}"
                        elided = fm_bold.elidedText(label, Qt.TextElideMode.ElideRight, int(avail_w))
                        painter.drawText(QRectF(x1 + 6, y_top + 2, avail_w, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # 5. Ruler Header Background & Border
        ruler_rect = QRectF(0, 0, self.width(), self.RULER_HEIGHT)
        painter.fillRect(ruler_rect, QColor("#282828"))
        painter.setPen(QPen(QColor("#383838"), 1))
        painter.drawLine(0, self.RULER_HEIGHT, self.width(), self.RULER_HEIGHT)

        # Re-draw ticks inside ruler area on top
        t = 0.0
        while t <= max_t:
            x = self.HEADER_WIDTH + t * pps
            if x > self.width():
                break

            is_major = (round(t / major_step) * major_step == round(t, 4))
            if is_major:
                painter.setPen(QPen(QColor("#888888"), 1))
                painter.drawLine(int(x), self.RULER_HEIGHT - 10, int(x), self.RULER_HEIGHT)
                m = int(t // 60)
                s = int(t % 60)
                ms = int(round((t - int(t)) * 10))
                tc_text = f"{m:02d}:{s:02d}.{ms:01d}" if major_step < 1.0 else f"{m:02d}:{s:02d}"
                painter.setPen(QColor("#aaaaaa"))
                painter.drawText(int(x) + 4, 16, tc_text)
            else:
                painter.setPen(QPen(QColor("#444444"), 1))
                painter.drawLine(int(x), self.RULER_HEIGHT - 5, int(x), self.RULER_HEIGHT)
            t = round(t + minor_step, 4)

        # 6. Playhead line & handle (Prominent studio cyan-blue matching video player seekbar)
        px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second
        header_x = self._get_header_x()
        is_active = (self._dragging and self._dragging[0] == "playhead") or self._is_hovering_playhead

        head_w = 7.0
        if px + head_w >= header_x + self.HEADER_WIDTH:
            painter.save()
            # Clip playhead to visible timeline area to guarantee it never bleeds onto left character headers
            clip_left = header_x + self.HEADER_WIDTH
            clip_w = max(0.0, float(self.width() - clip_left))
            painter.setClipRect(QRectF(clip_left, 0, clip_w, float(self.height())))

            # Background subtle glow line
            if is_active:
                painter.setPen(QPen(QColor(56, 189, 248, 60), 4))
                painter.drawLine(int(px), 0, int(px), self.height())

            # Vertical tracking line
            line_color = QColor("#38BDF8") if is_active else QColor("#0EA5E9")
            painter.setPen(QPen(line_color, 1.8 if is_active else 1.5))
            painter.drawLine(int(px), 0, int(px), self.height())

            # Playhead handle head on ruler
            head_h = 13.0
            head_tip = 19.0
            head_poly = [
                QPointF(px - head_w, 0),
                QPointF(px + head_w, 0),
                QPointF(px + head_w, head_h),
                QPointF(px, head_tip),
                QPointF(px - head_w, head_h),
            ]

            grad = QLinearGradient(px, 0, px, head_tip)
            if is_active:
                grad.setColorAt(0.0, QColor("#38BDF8"))
                grad.setColorAt(1.0, QColor("#0284C7"))
            else:
                grad.setColorAt(0.0, QColor("#0EA5E9"))
                grad.setColorAt(1.0, QColor("#0369A1"))

            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor("#FFFFFF" if is_active else "#BAE6FD"), 1.2))
            painter.drawPolygon(head_poly)

            # Center indicator dot
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#FFFFFF" if is_active else "#E0F2FE")))
            painter.drawEllipse(QPointF(px, 6.0), 1.5, 1.5)

            painter.restore()

        # 7. Left Track Header (Fixed Labels: A1, A2... or Sticky to Viewport Left Edge - ALWAYS ON TOP of Playhead)
        header_rect = QRectF(header_x, 0, self.HEADER_WIDTH, self.height())
        painter.fillRect(header_rect, QColor("#222222"))
        painter.setPen(QPen(QColor("#383838"), 1))
        painter.drawLine(int(header_x + self.HEADER_WIDTH), 0, int(header_x + self.HEADER_WIDTH), self.height())

        # Subtle drop-shadow on right edge when sticky headers are scrolled
        if self.sticky_headers and header_x > 0:
            shadow_grad = QLinearGradient(header_x + self.HEADER_WIDTH, 0, header_x + self.HEADER_WIDTH + 8, 0)
            shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 130))
            shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(QRectF(header_x + self.HEADER_WIDTH, 0, 8, self.height()), QBrush(shadow_grad))

        # Top-left corner cell
        corner_rect = QRectF(header_x, 0, self.HEADER_WIDTH, self.RULER_HEIGHT)
        painter.fillRect(corner_rect, QColor("#282828"))
        painter.setPen(QPen(QColor("#383838"), 1))
        painter.drawLine(int(header_x), self.RULER_HEIGHT, int(header_x + self.HEADER_WIDTH), self.RULER_HEIGHT)
        
        painter.setPen(QColor("#aaaaaa"))
        font_corner = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font_corner)
        title_rect = QRectF(header_x + 8, 0, self.HEADER_WIDTH - 36, self.RULER_HEIGHT)
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "AUDIO TRACKS")

        # Discreet Pin Button in Corner Cell
        pin_btn_rect = QRectF(header_x + self.HEADER_WIDTH - 24, 4, 18, 20)
        if getattr(self, "_is_hovering_pin", False):
            painter.fillRect(pin_btn_rect, QColor(255, 255, 255, 30))
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
            painter.drawRoundedRect(pin_btn_rect, 3, 3)

        # Draw Pin Vector Icon
        pin_center_x = header_x + self.HEADER_WIDTH - 15
        pin_center_y = 14
        painter.save()
        painter.translate(pin_center_x, pin_center_y)
        if self.sticky_headers:
            # Active Sticky Pin (sleek studio cyan)
            painter.setPen(QPen(QColor("#38BDF8"), 1.4))
            painter.setBrush(QBrush(QColor("#0284C7")))
            painter.rotate(30)
            painter.drawRoundedRect(-4, -6, 8, 4, 1, 1)
            painter.drawRect(-2, -2, 4, 3)
            painter.drawLine(0, 1, 0, 6)
        else:
            # Inactive Pin (subtle muted outline)
            painter.setPen(QPen(QColor("#666666"), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.rotate(30)
            painter.drawRoundedRect(-4, -6, 8, 4, 1, 1)
            painter.drawRect(-2, -2, 4, 3)
            painter.drawLine(0, 1, 0, 6)
        painter.restore()

        for spk_idx, spk_id in enumerate(speakers_list):
            y_top = self.RULER_HEIGHT + spk_idx * (self.TRACK_HEIGHT + self.TRACK_GAP)
            row_rect = QRectF(header_x, y_top, self.HEADER_WIDTH, self.TRACK_HEIGHT)

            # Row background
            is_lifted = (spk_id == dragged_track_spk_id)
            if is_lifted:
                painter.fillRect(row_rect, QColor("#151515"))
                painter.setPen(QPen(QColor("#383838"), 1.0, Qt.PenStyle.DashLine))
                painter.drawRect(row_rect.adjusted(1, 1, -1, -1))
            else:
                painter.fillRect(row_rect, QColor("#242424"))
                painter.setPen(QPen(QColor("#303030"), 1))
                painter.drawLine(int(header_x), int(y_top + self.TRACK_HEIGHT), int(header_x + self.HEADER_WIDTH), int(y_top + self.TRACK_HEIGHT))

            color_hex = self.colors[spk_idx % len(self.colors)]
            track_color = QColor(color_hex)

            # Left color indicator bar
            painter.fillRect(QRectF(header_x, y_top, 4, self.TRACK_HEIGHT), track_color if not is_lifted else track_color.darker(160))

            # Track badge (e.g. "A1", "A2")
            badge_rect = QRectF(header_x + 10, y_top + (self.TRACK_HEIGHT - 22) / 2, 28, 22)
            painter.setBrush(QBrush(QColor("#1a1a1a")))
            painter.setPen(QPen(track_color.lighter(115) if not is_lifted else track_color.darker(140), 1.5))
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setPen(QColor("#FFFFFF" if not is_lifted else "#555555"))
            font_badge = QFont("Segoe UI", 8, QFont.Weight.Bold)
            painter.setFont(font_badge)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"A{spk_idx+1}")

            # Speaker Name
            spk_name = self.state.get_speaker(spk_id).display_name if self.state else spk_id
            name_rect = QRectF(header_x + 44, y_top + 6, self.HEADER_WIDTH - 48, 18)
            painter.setPen(QColor("#E0E0E0" if not is_lifted else "#555555"))
            font_name = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
            painter.setFont(font_name)
            fm_name = QFontMetrics(font_name)
            elided_spk = fm_name.elidedText(spk_name, Qt.TextElideMode.ElideRight, int(self.HEADER_WIDTH - 48))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_spk)

            # Clip count subtitle
            count = sum(1 for d in (self.state.active_dialogues() if self.state else []) if d.speaker_id == spk_id)
            sub_rect = QRectF(header_x + 44, y_top + 25, self.HEADER_WIDTH - 48, 14)
            painter.setPen(QColor("#888888" if not is_lifted else "#444444"))
            font_sub = QFont("Segoe UI", 7)
            painter.setFont(font_sub)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{count} clips")

        # 8. Track Reordering Visual Feedback (Drag Ghost + Drop Target Insertion Line)
        if self._dragging and self._dragging[0] == "track_header" and len(self._dragging) > 4:
            drag_spk_id = self._dragging[1]
            drag_y = self._dragging[4]

            # Compute target slot line
            raw_slot = (drag_y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP)
            target_slot = max(0, min(len(speakers_list), int(round(raw_slot))))
            line_y = self.RULER_HEIGHT + target_slot * (self.TRACK_HEIGHT + self.TRACK_GAP)

            # Subtle dashed insertion guideline (clean silver-white)
            painter.setPen(QPen(QColor(255, 255, 255, 130), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(0, int(line_y), self.width(), int(line_y))

            # Small target indicator triangle on the left edge
            tri = [
                QPointF(0, line_y - 4),
                QPointF(6, line_y),
                QPointF(0, line_y + 4),
            ]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 160)))
            painter.drawPolygon(tri)

            # Clamp ghost_y so it can NEVER rise above "AUDIO TRACKS" ruler bar!
            min_ghost_y = float(self.RULER_HEIGHT)
            max_ghost_y = float(self.RULER_HEIGHT + max(0, len(speakers_list) - 1) * (self.TRACK_HEIGHT + self.TRACK_GAP))
            ghost_y = max(min_ghost_y, min(max_ghost_y, drag_y - self.TRACK_HEIGHT / 2.0))
            ghost_rect = QRectF(header_x + 2, ghost_y, self.HEADER_WIDTH - 4, self.TRACK_HEIGHT)

            # Multi-layer soft drop shadow (realistic 3D elevation indicating it is grabbed)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 70)))
            painter.drawRoundedRect(QRectF(header_x + 4, ghost_y + 4, self.HEADER_WIDTH - 4, self.TRACK_HEIGHT), 6, 6)
            painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
            painter.drawRoundedRect(QRectF(header_x + 3, ghost_y + 2, self.HEADER_WIDTH - 4, self.TRACK_HEIGHT), 6, 6)

            try:
                g_spk_idx = speakers_list.index(drag_spk_id)
            except ValueError:
                g_spk_idx = 0
            g_color = QColor(self.colors[g_spk_idx % len(self.colors)])

            # Card body: Sleek dark studio gradient (NOT bright blue!)
            card_grad = QLinearGradient(0, ghost_y, 0, ghost_y + self.TRACK_HEIGHT)
            card_grad.setColorAt(0.0, QColor("#2A2A2A"))
            card_grad.setColorAt(1.0, QColor("#1E1E1E"))
            painter.setBrush(QBrush(card_grad))
            painter.setPen(QPen(g_color, 1.5))
            painter.drawRoundedRect(ghost_rect, 5, 5)

            # Left color indicator strip (rounded corners on the left)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(g_color))
            painter.drawRoundedRect(QRectF(header_x + 2, ghost_y, 4, self.TRACK_HEIGHT), 2, 2)

            # Subtle Grip Handle Dots (6 dots: 2 columns x 3 rows) showing it is grabbed
            painter.setBrush(QBrush(QColor(180, 180, 180, 200)))
            grip_x1 = header_x + 9.0
            grip_x2 = header_x + 13.0
            for dot_row in range(3):
                dot_y = ghost_y + (self.TRACK_HEIGHT / 2.0) - 5.0 + (dot_row * 5.0)
                painter.drawEllipse(QPointF(grip_x1, dot_y), 1.1, 1.1)
                painter.drawEllipse(QPointF(grip_x2, dot_y), 1.1, 1.1)

            # Track badge (A1, A2...)
            g_badge_rect = QRectF(header_x + 18, ghost_y + (self.TRACK_HEIGHT - 22) / 2, 26, 22)
            painter.setBrush(QBrush(QColor("#161616")))
            painter.setPen(QPen(g_color.lighter(115), 1.5))
            painter.drawRoundedRect(g_badge_rect, 4, 4)

            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(g_badge_rect, Qt.AlignmentFlag.AlignCenter, f"A{g_spk_idx+1}")

            # Speaker Name
            g_name = self.state.get_speaker(drag_spk_id).display_name if self.state else drag_spk_id
            g_name_rect = QRectF(header_x + 48, ghost_y + 7, self.HEADER_WIDTH - 52, 16)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
            fm_gname = QFontMetrics(painter.font())
            elided_gname = fm_gname.elidedText(g_name, Qt.TextElideMode.ElideRight, int(self.HEADER_WIDTH - 52))
            painter.drawText(g_name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_gname)

            # Subtitle
            sub_rect = QRectF(header_x + 48, ghost_y + 24, self.HEADER_WIDTH - 52, 14)
            painter.setPen(QColor("#9E9E9E"))
            font_sub = QFont("Segoe UI", 7)
            painter.setFont(font_sub)
            painter.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Reordering...")

    # ── Mouse Interaction & Cursors ─────────────────────────────────────────────

    def leaveEvent(self, event):
        if self._is_hovering_playhead:
            self._is_hovering_playhead = False
            self.update()
        if self._is_hovering_pin:
            self._is_hovering_pin = False
            self.update()
        super().leaveEvent(event)

    def _hit_test(self, x: float, y: float) -> Tuple[Optional[str], Optional[DialogueItem]]:
        """Returns (mode, dialogue_item) where mode in ['playhead', 'ruler', 'start', 'end', 'body', 'track', 'header', 'pin_button']"""
        header_x = self._get_header_x()

        # 0. Check Pin Button in AUDIO TRACKS corner
        if header_x + self.HEADER_WIDTH - 24 <= x <= header_x + self.HEADER_WIDTH - 4 and 4 <= y <= self.RULER_HEIGHT - 4:
            return "pin_button", None

        # 1. Left Track Header zone (or area behind sticky header)
        if x < header_x + self.HEADER_WIDTH:
            if y < self.RULER_HEIGHT:
                return "header_corner", None
            return "header", None

        px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second

        # 2. Playhead handle grab zone (on ruler or top edge)
        if abs(x - px) <= 8 and y <= self.RULER_HEIGHT + 4:
            return "playhead", None

        # 3. Ruler area (clicking/dragging anywhere on ruler scrubs playhead)
        if y < self.RULER_HEIGHT:
            return "ruler", None

        # 4. Clips on track lanes
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

        # 5. Playhead vertical line over empty space
        if abs(x - px) <= 6:
            return "playhead", None

        # 6. Empty track area
        return "track", None

    def mouseDoubleClickEvent(self, event):
        """Double-click on a character track header to rename it immediately."""
        if event.button() == Qt.MouseButton.LeftButton and self.state:
            x = event.pos().x()
            y = event.pos().y()
            header_x = self._get_header_x()
            if header_x <= x < header_x + self.HEADER_WIDTH and y >= self.RULER_HEIGHT:
                speakers_list = self._get_speaker_list()
                track_idx = int((y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP))
                if 0 <= track_idx < len(speakers_list):
                    spk_id = speakers_list[track_idx]
                    self._prompt_rename_track(spk_id)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def _prompt_rename_track(self, spk_id: str):
        if not self.state or spk_id not in self.state.speakers:
            return
        from PySide6.QtWidgets import QInputDialog
        spk_info = self.state.get_speaker(spk_id)
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Character",
            f"Enter character / speaker name for '{spk_info.display_name}':",
            text=spk_info.display_name
        )
        if ok and new_name.strip():
            self.track_renamed.emit(spk_id, new_name.strip())

    def mousePressEvent(self, event):
        self.setFocus()
        if not self.state:
            return

        x = event.pos().x()
        y = event.pos().y()

        # ── Right Click Context Menus (Track Header or Clip) ──
        if event.button() == Qt.MouseButton.RightButton:
            from PySide6.QtWidgets import QMenu
            header_x = self._get_header_x()
            if header_x <= x < header_x + self.HEADER_WIDTH:
                # Right-click on Track Header
                speakers_list = self._get_speaker_list()
                track_idx = int((y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP))
                menu = QMenu(self)
                if 0 <= track_idx < len(speakers_list) and self.state:
                    spk_id = speakers_list[track_idx]
                    spk_info = self.state.get_speaker(spk_id)
                    act_rename = menu.addAction(f"Rename Character ('{spk_info.display_name}')...")
                    act_rename.triggered.connect(lambda s=spk_id: self._prompt_rename_track(s))
                    act_del = menu.addAction(f"Delete Track '{spk_info.display_name}'...")
                    act_del.triggered.connect(lambda s=spk_id: self.delete_track_requested.emit(s))
                    menu.addSeparator()

                act_pin = menu.addAction("Pin Tracks to Edge (Sticky)")
                act_pin.setCheckable(True)
                act_pin.setChecked(self.sticky_headers)
                act_pin.triggered.connect(self.toggle_sticky_headers)
                menu.exec(event.globalPosition().toPoint())
                event.accept()
                return
            else:
                # Right-click on Clip / Track Lane
                mode, item = self._hit_test(x, y)
                if item:
                    self.selected_index = item.index
                    self.segment_selected.emit(item.index)
                    self.update()

                    menu = QMenu(self)
                    act_split = menu.addAction("Split at Playhead (S)")
                    act_split.triggered.connect(lambda: self.split_at_playhead_requested.emit())

                    act_tl = menu.addAction("Delete Left to Playhead (Q)")
                    act_tl.triggered.connect(lambda: self.trim_left_requested.emit())

                    act_tr = menu.addAction("Delete Right to Playhead (W)")
                    act_tr.triggered.connect(lambda: self.trim_right_requested.emit())

                    menu.addSeparator()
                    act_del = menu.addAction("Delete Clip (Del)")
                    act_del.triggered.connect(lambda: self.delete_requested.emit(item.index))

                    menu.exec(event.globalPosition().toPoint())
                    event.accept()
                    return

        # ── Middle Mouse Button (MMB) 2D Pan ─────────────────────────
        if event.button() == Qt.MouseButton.MiddleButton:
            scroll_area = self._get_scroll_area()
            if scroll_area:
                self._is_panning = True
                self._pan_start_pos = event.globalPosition().toPoint()
                self._pan_start_h = scroll_area.horizontalScrollBar().value()
                self._pan_start_v = scroll_area.verticalScrollBar().value()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        mode, item = self._hit_test(x, y)

        if mode == "pin_button":
            self.toggle_sticky_headers()
            return

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
                self._dragging = ("track_header", speakers_list[track_idx], x, y, y)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
        elif item:
            self.selected_index = item.index
            self.segment_selected.emit(item.index)
            self._dragging = (mode, item, x, item.start if mode != "end" else item.end)
            self.setCursor(Qt.CursorShape.ClosedHandCursor if mode == "body" else Qt.CursorShape.SizeHorCursor)
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

        # ── Middle Mouse Button (MMB) 2D Pan ─────────────────────────
        if self._is_panning:
            scroll_area = self._get_scroll_area()
            if scroll_area:
                delta = event.globalPosition().toPoint() - self._pan_start_pos
                scroll_area.horizontalScrollBar().setValue(self._pan_start_h - delta.x())
                scroll_area.verticalScrollBar().setValue(self._pan_start_v - delta.y())
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return

        x = event.pos().x()
        y = event.pos().y()

        if self._dragging:
            mode = self._dragging[0]
            if mode == "track_header":
                spk_id = self._dragging[1]
                start_x = self._dragging[2]
                start_y = self._dragging[3]
                speakers_list = self._get_speaker_list()
                min_drag_y = self.RULER_HEIGHT + self.TRACK_HEIGHT / 2.0
                max_drag_y = self.RULER_HEIGHT + max(1, len(speakers_list)) * (self.TRACK_HEIGHT + self.TRACK_GAP) - self.TRACK_HEIGHT / 2.0
                clamped_y = max(min_drag_y, min(max_drag_y, y))
                self._dragging = ("track_header", spk_id, start_x, start_y, clamped_y)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return

            if mode == "playhead":
                t = max(0.0, min(self.duration, (x - self.HEADER_WIDTH) / max(1.0, self.pixels_per_second)))
                self.set_current_time(t)
                import time
                now = time.monotonic()
                if now - self._last_scrub_seek_time >= 0.030:
                    self.seek_requested.emit(t)
                    self._last_scrub_seek_time = now
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

            _, item, start_x, start_val = self._dragging[:4]
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
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
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
                    if item.speaker_id != speakers_list[target_spk_idx]:
                        item.speaker_id = speakers_list[target_spk_idx]
            self.update()
        else:
            header_x = self._get_header_x()
            px = self.HEADER_WIDTH + self.current_time * self.pixels_per_second
            is_near_playhead = (px >= header_x + self.HEADER_WIDTH) and (
                (abs(x - px) <= 8 and y <= self.RULER_HEIGHT + 6) or (abs(x - px) <= 5)
            )
            if is_near_playhead != self._is_hovering_playhead:
                self._is_hovering_playhead = is_near_playhead
                self.update()

            mode, item = self._hit_test(x, y)
            if mode == "pin_button":
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                tip_text = "Sticky Tracks: ON (Click to unpin) / ตรึงรายชื่อตัวละคร" if self.sticky_headers else "Sticky Tracks: OFF (Click to pin) / ตรึงรายชื่อตัวละคร"
                QToolTip.showText(event.globalPosition().toPoint(), tip_text, self)
                if not self._is_hovering_pin:
                    self._is_hovering_pin = True
                    self.update()
            else:
                if self._is_hovering_pin:
                    self._is_hovering_pin = False
                    self.update()

                if mode in ("start", "end"):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)  # Trim Cursor
                elif mode == "body":
                    self.setCursor(Qt.CursorShape.OpenHandCursor)  # Hand grab cursor for clip
                elif mode == "header":
                    self.setCursor(Qt.CursorShape.OpenHandCursor)  # Hand grab cursor for speaker track
                elif mode == "playhead":
                    self.setCursor(Qt.CursorShape.SizeHorCursor)  # Playhead Drag Cursor
                elif mode == "ruler":
                    self.setCursor(Qt.CursorShape.PointingHandCursor)  # Ruler Scrub Cursor
                else:
                    self.setCursor(Qt.CursorShape.ArrowCursor)

            if item:
                spk_name = self.state.get_speaker_safe_name(item.speaker_id)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"Clip #{item.index:03d} — {spk_name}\nStart: {item.format_start()}  End: {item.format_end()}  (Duration: {item.duration:.2f}s)",
                    self
                )

    def mouseReleaseEvent(self, event):
        # ── Middle Mouse Button (MMB) Release ─────────────────────────
        if event.button() == Qt.MouseButton.MiddleButton:
            if self._is_panning:
                self._is_panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                event.accept()
                return

        if self._dragging:
            mode = self._dragging[0]
            if mode == "track_header":
                spk_id = self._dragging[1]
                current_y = self._dragging[4] if len(self._dragging) > 4 else event.pos().y()
                speakers_list = list(self._get_speaker_list())
                if spk_id in speakers_list:
                    old_idx = speakers_list.index(spk_id)
                    raw_slot = (current_y - self.RULER_HEIGHT) / (self.TRACK_HEIGHT + self.TRACK_GAP)
                    target_spk_idx = max(0, min(len(speakers_list) - 1, int(round(raw_slot))))
                    if old_idx != target_spk_idx:
                        speakers_list.pop(old_idx)
                        speakers_list.insert(target_spk_idx, spk_id)
                        if self.state:
                            self.state.speaker_order = speakers_list
                        self.tracks_reordered.emit()
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

    def _get_clip_at_time(self, t: float) -> Optional[DialogueItem]:
        """Find the dialogue clip at timestamp t, prioritizing selected item."""
        if not self.state:
            return None
        # First priority: if selected clip contains t
        for d in self.state.active_dialogues():
            if d.index == self.selected_index and d.start <= t <= d.end:
                return d
        # Second priority: any clip containing t
        for d in self.state.active_dialogues():
            if d.start <= t <= d.end:
                return d
        # Third priority: selected clip even if playhead is slightly off
        if self.selected_index >= 0:
            for d in self.state.active_dialogues():
                if d.index == self.selected_index:
                    return d
        return None

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        has_ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        has_shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        if key == Qt.Key.Key_Space:
            self.toggle_playback()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_index >= 0:
                self.delete_requested.emit(self.selected_index)
            else:
                item = self._get_clip_at_time(self.current_time)
                if item:
                    self.delete_requested.emit(item.index)
        elif key == Qt.Key.Key_Q:
            self.trim_left_requested.emit()
        elif key == Qt.Key.Key_W:
            self.trim_right_requested.emit()
        elif key == Qt.Key.Key_S or (key == Qt.Key.Key_B and has_ctrl):
            self.split_at_playhead_requested.emit()
        elif key == Qt.Key.Key_M:
            if self.selected_index >= 0:
                self.merge_requested.emit(self.selected_index)
        elif key == Qt.Key.Key_Z and has_ctrl:
            if has_shift:
                self.redo_requested.emit()
            else:
                self.undo_requested.emit()
        elif key == Qt.Key.Key_Y and has_ctrl:
            self.redo_requested.emit()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif key == Qt.Key.Key_Minus:
            self.zoom_out()
        elif key == Qt.Key.Key_Left:
            step = 1.0 if has_shift else 0.1
            self.set_current_time(self.current_time - step)
            self.seek_requested.emit(self.current_time)
        elif key == Qt.Key.Key_Right:
            step = 1.0 if has_shift else 0.1
            self.set_current_time(self.current_time + step)
            self.seek_requested.emit(self.current_time)
        else:
            super().keyPressEvent(event)
