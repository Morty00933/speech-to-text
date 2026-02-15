"""
Speaker diarization module.
Identifies "who spoke when" in audio recordings.

Note: Full diarization with pyannote.audio requires:
1. pip install pyannote.audio
2. HuggingFace token (HF_TOKEN env var)

Without pyannote, uses SimpleDiarizer which assigns single speaker.
"""
import abc
from typing import List, Dict, Optional
from dataclasses import dataclass
from collections import defaultdict

import torch

from common.config import settings
from common.logging_config import get_logger
from common.metrics import diarization_duration_seconds, model_loaded

logger = get_logger("transcriber.diarizer")


@dataclass
class SpeakerSegment:
    """Speaker segment with timing."""
    start: float
    end: float
    speaker: str


@dataclass
class SpeakerInfo:
    """Aggregated speaker information."""
    id: str
    segments_count: int
    total_duration: float


class BaseDiarizer(abc.ABC):
    """Abstract base class for all diarizers.

    Concrete subclasses must implement ``diarize`` and ``align_with_transcription``.
    The ``get_speaker_info`` helper and context-manager protocol are shared.
    """

    @abc.abstractmethod
    def diarize(
        self,
        audio_path: str,
        min_speakers: int = 1,
        max_speakers: Optional[int] = None,
    ) -> List[SpeakerSegment]:
        """Perform speaker diarization on an audio file."""

    @abc.abstractmethod
    def align_with_transcription(
        self,
        transcription_segments: List[dict],
        diarization_segments: List[SpeakerSegment],
    ) -> List[dict]:
        """Align transcription segments with speaker labels."""

    def get_speaker_info(self, segments: List[SpeakerSegment]) -> List[SpeakerInfo]:
        """Get aggregated information about each speaker."""
        speaker_data: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "duration": 0.0})

        for seg in segments:
            speaker_data[seg.speaker]["count"] += 1
            speaker_data[seg.speaker]["duration"] += seg.end - seg.start

        return [
            SpeakerInfo(
                id=speaker,
                segments_count=data["count"],
                total_duration=round(data["duration"], 2),
            )
            for speaker, data in sorted(speaker_data.items())
        ]

    def unload_model(self):
        """Unload model to free memory. Override in subclasses that load models."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload_model()


class SimpleDiarizer(BaseDiarizer):
    """
    Simple fallback diarizer.

    Assigns all speech to a single speaker.
    For multi-speaker detection, install pyannote.audio and set HF_TOKEN.
    """

    def __init__(self):
        logger.info("Using simple diarizer (single speaker mode)")

    def diarize(
        self,
        audio_path: str,
        min_speakers: int = 1,
        max_speakers: Optional[int] = None,
    ) -> List[SpeakerSegment]:
        logger.warning(
            "SimpleDiarizer is active: all speech assigned to SPEAKER_00. "
            "Multi-speaker detection disabled. "
            "Set HF_TOKEN and install pyannote.audio to enable real diarization."
        )

        import librosa
        audio, sr = librosa.load(audio_path, sr=16000, mono=True)
        duration = len(audio) / sr

        return [
            SpeakerSegment(
                start=0.0,
                end=duration,
                speaker="SPEAKER_00",
            )
        ]

    def align_with_transcription(
        self,
        transcription_segments: List[dict],
        diarization_segments: List[SpeakerSegment],
    ) -> List[dict]:
        """Align transcription segments with speaker labels."""
        for trans_seg in transcription_segments:
            trans_seg["speaker"] = "SPEAKER_00"
        return transcription_segments


class SpeakerDiarizer(BaseDiarizer):
    """
    Speaker diarization using pyannote.audio.

    Identifies different speakers in audio and assigns labels
    to each speech segment.
    """

    def __init__(self, device: str = "auto"):
        self.pipeline = None
        self.device = self._determine_device(device)
        logger.info(f"Initializing speaker diarizer (device: {self.device})")

    def _determine_device(self, device: str) -> str:
        """Determine the best device to use."""
        if device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def load_model(self):
        """Load the diarization pipeline."""
        if self.pipeline is not None:
            return

        hf_token = settings.hf_token
        if not hf_token:
            logger.error("HuggingFace token not set. Required for pyannote.audio models.")
            raise ValueError(
                "HF_TOKEN environment variable is required for speaker diarization. "
                "Get a token from https://huggingface.co/settings/tokens"
            )

        logger.info("Loading pyannote speaker diarization pipeline")

        try:
            from pyannote.audio import Pipeline

            self.pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
            self.pipeline.to(torch.device(self.device))

            model_loaded.labels(model_name="pyannote", model_size="diarization-3.1").set(1)
            logger.info("Diarization pipeline loaded")

        except ImportError:
            logger.error("pyannote.audio not installed. Run: pip install pyannote.audio")
            raise
        except Exception as e:
            logger.error(f"Failed to load diarization pipeline: {e}")
            model_loaded.labels(model_name="pyannote", model_size="diarization-3.1").set(0)
            raise

    def diarize(
        self,
        audio_path: str,
        min_speakers: int = 1,
        max_speakers: Optional[int] = None,
    ) -> List[SpeakerSegment]:
        """Perform speaker diarization on audio file."""
        import time
        start_time = time.time()

        self.load_model()
        logger.info(f"Starting diarization: {audio_path}")

        try:
            diarization = self.pipeline(
                audio_path,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )

            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(SpeakerSegment(
                    start=turn.start,
                    end=turn.end,
                    speaker=speaker,
                ))

            processing_time = time.time() - start_time
            diarization_duration_seconds.observe(processing_time)

            speakers = set(s.speaker for s in segments)

            logger.info(
                f"Diarization completed",
                extra={
                    "segments_count": len(segments),
                    "speakers_count": len(speakers),
                    "processing_time": processing_time,
                }
            )

            return segments

        except Exception as e:
            logger.error(f"Diarization failed: {e}")
            raise

    def align_with_transcription(
        self,
        transcription_segments: List[dict],
        diarization_segments: List[SpeakerSegment],
    ) -> List[dict]:
        """Align transcription segments with speaker labels via overlap matching."""
        logger.info("Aligning transcription with speaker diarization")

        for trans_seg in transcription_segments:
            trans_start = trans_seg.get("start", 0)
            trans_end = trans_seg.get("end", 0)

            overlaps: Dict[str, float] = defaultdict(float)

            for diar_seg in diarization_segments:
                overlap_start = max(trans_start, diar_seg.start)
                overlap_end = min(trans_end, diar_seg.end)
                overlap_duration = max(0, overlap_end - overlap_start)

                if overlap_duration > 0:
                    overlaps[diar_seg.speaker] += overlap_duration

            if overlaps:
                trans_seg["speaker"] = max(overlaps, key=overlaps.get)
            else:
                trans_seg["speaker"] = None

        return transcription_segments

    def unload_model(self):
        """Unload the model to free memory."""
        if self.pipeline is not None:
            del self.pipeline
            self.pipeline = None

            if self.device == "cuda":
                torch.cuda.empty_cache()

            model_loaded.labels(model_name="pyannote", model_size="diarization-3.1").set(0)
            logger.info("Diarization model unloaded")

    def __enter__(self):
        self.load_model()
        return self


def get_diarizer(use_simple: bool = False) -> BaseDiarizer:
    """
    Factory function to get the appropriate diarizer.

    Args:
        use_simple: Force use of simple diarizer

    Returns:
        Diarizer instance (SimpleDiarizer or SpeakerDiarizer)
    """
    pyannote_available = False
    try:
        import pyannote.audio  # noqa: F401
        pyannote_available = True
    except ImportError:
        pass

    if use_simple or not settings.hf_token or not pyannote_available:
        if not pyannote_available:
            logger.info("pyannote.audio not installed, using SimpleDiarizer")
        elif not settings.hf_token:
            logger.info("HF_TOKEN not set, using SimpleDiarizer")
        return SimpleDiarizer()

    return SpeakerDiarizer()
