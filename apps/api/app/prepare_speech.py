"""One-time model download. After this step, speech recognition works offline."""
import os

from faster_whisper import WhisperModel

if __name__ == "__main__":
    WhisperModel(os.getenv("SPEECH_MODEL", "base.en"), device="cpu", compute_type="int8")
    print("Local speech model ready. No transcription API key is required.")
