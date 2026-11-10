"""Bounded local audio analysis; no live project access from the worker."""
from threading import Event

from PySide6.QtCore import QThread, Signal


class AgentAudioWorker(QThread):
    ready = Signal(object, str)

    def __init__(self, job_id, state, item, source, parent=None, *, operation='analyze_voice', speaker_id=None):
        super().__init__(parent)
        self.job_id, self.state, self.item, self.source = job_id, state, item, source
        self.cancelled = Event()
        self.operation, self.speaker_id = operation, speaker_id

    def cancel(self):
        self.cancelled.set()

    def run(self):
        result, error = None, ''
        try:
            if not self.cancelled.is_set():
                from core.speaker_matcher import SpeakerMatcher
                if self.operation == 'enroll_voice':
                    if not SpeakerMatcher.enroll_speaker_sample(self.state, self.speaker_id, self.source,
                            self.item.start, self.item.end, sample_name='Reference clip'):
                        raise ValueError('AUDIO_ANALYSIS_FAILED')
                    result = {'enrolled': True}
                else:
                    result = SpeakerMatcher.analyze_segment(self.state, self.source, self.item.start, self.item.end)
        except ValueError as exc:
            error = str(exc) if str(exc) in ('NO_REFERENCE_VOICE', 'AUDIO_ANALYSIS_FAILED') else 'OPERATION_FAILED'
        except Exception:
            error = 'AUDIO_ANALYSIS_FAILED'
        self.ready.emit(result, error)
