"""Local ASR. Audio is decoded in memory and is never written to disk."""
import io
import threading
import wave


class SpeechService:
    def __init__(self, model_name: str = "base.en"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def prepare(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.model_name, device="cpu", compute_type="int8",
                    cpu_threads=4, local_files_only=True,
                )
        return self._model

    def transcribe(self, audio: bytes) -> tuple[str, float]:
        # Reject oversized/unsupported recordings before allocating decoded audio.
        try:
            with wave.open(io.BytesIO(audio)) as wav:
                duration = wav.getnframes() / wav.getframerate()
                if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                        or not 8000 <= wav.getframerate() <= 48000
                        or not 0.15 <= duration <= 31):
                    raise ValueError("Expected mono PCM16 WAV, 0.15-31 seconds")
        except (wave.Error, EOFError) as error:
            raise ValueError("Invalid WAV audio") from error
        model = self.prepare()
        with self._lock:
            segments, _ = model.transcribe(
                io.BytesIO(audio), language="en", beam_size=3,
                condition_on_previous_text=False, vad_filter=True, word_timestamps=True,
            )
            segments = [s for s in segments if s.no_speech_prob < 0.6]
        text = " ".join(s.text.strip() for s in segments).strip()
        # Segment logprob includes timestamp/control tokens; it is not a speech
        # confidence score (in particular it under-scores short "yes"/"no" turns).
        probabilities = [float(word.probability) for s in segments for word in (s.words or [])]
        confidence = sum(probabilities) / len(probabilities) if probabilities else 0.0
        return text[:2000], min(1.0, max(0.0, confidence))
