"""
Transcription engine using Faster-Whisper.
Optimized for RTX 3060 (6GB VRAM).
"""
import os
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

import torch
from faster_whisper import WhisperModel

from common.config import settings
from common.logging_config import get_logger
from common.models_registry import MODEL_VRAM
from common.metrics import (
    model_loaded,
    model_load_time_seconds,
    transcription_duration_seconds,
    gpu_memory_usage_bytes,
)

logger = get_logger("transcriber.engine")


@dataclass
class TranscriptionSegment:
    """Single transcription segment."""
    start: float
    end: float
    text: str
    words: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    speaker: Optional[str] = None


@dataclass
class TranscriptionResult:
    """Complete transcription result."""
    text: str
    segments: List[TranscriptionSegment]
    language: str
    language_probability: float
    duration: float
    processing_time: float


class TranscriptionEngine:
    """
    Whisper-based transcription engine using Faster-Whisper (CTranslate2).

    Optimizations for RTX 3060 (6GB):
    - Uses float16 for reduced VRAM usage
    - Optimal beam size for quality/speed balance
    """

    def __init__(
        self,
        model_size: str = "medium",
        device: str = "auto",
        compute_type: str = "float16",
    ):
        self.model_size = model_size
        self.model: Optional[WhisperModel] = None
        self.device = self._determine_device(device)
        self.compute_type = compute_type if self.device == "cuda" else "float32"

        logger.info(
            f"Initializing transcription engine",
            extra={"model": model_size, "device": self.device, "compute_type": self.compute_type}
        )

    def _determine_device(self, device: str) -> str:
        """Determine the best device to use."""
        if device == "auto":
            if torch.cuda.is_available():
                vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                required = MODEL_VRAM.get(self.model_size, 5.0)

                if vram_gb >= required:
                    logger.info(f"Using CUDA (VRAM: {vram_gb:.1f}GB, required: {required:.1f}GB)")
                    return "cuda"
                else:
                    logger.warning(
                        f"Insufficient VRAM ({vram_gb:.1f}GB < {required:.1f}GB), using CPU"
                    )
                    return "cpu"
            return "cpu"
        return device

    def load_model(self):
        """Load the Whisper model."""
        if self.model is not None:
            return

        start_time = time.time()
        logger.info(f"Loading Whisper model: {self.model_size}")

        # Layout 1: flat snapshot_download layout (make download-model-*)
        #   /models/faster-whisper-{size}/model.bin
        flat_path = f"{settings.model_cache_dir}/faster-whisper-{self.model_size}"
        # Layout 2: HuggingFace Hub cache (hf_hub_download default)
        #   /models/models--Systran--faster-whisper-{size}/snapshots/<hash>/
        hf_snapshots = os.path.join(
            settings.model_cache_dir,
            f"models--Systran--faster-whisper-{self.model_size}",
            "snapshots",
        )

        if os.path.isdir(flat_path) and os.path.isfile(os.path.join(flat_path, "model.bin")):
            logger.info(f"Found pre-downloaded model (flat) at: {flat_path}")
            model_path = flat_path
        elif os.path.isdir(hf_snapshots):
            # Pick the first (usually only) snapshot directory
            try:
                snapshot_dir = next(
                    e.path for e in os.scandir(hf_snapshots) if e.is_dir()
                )
                logger.info(f"Found pre-downloaded model (HF cache) at: {snapshot_dir}")
                model_path = snapshot_dir
            except StopIteration:
                logger.info(f"Model not found locally, will download from HuggingFace...")
                logger.info(f"Run 'make download-model-{self.model_size}' to pre-download")
                model_path = self.model_size
        else:
            logger.info(f"Model not found locally, will download from HuggingFace...")
            logger.info(f"Run 'make download-model-{self.model_size}' to pre-download")
            model_path = self.model_size

        try:
            self.model = WhisperModel(
                model_path,
                device=self.device,
                compute_type=self.compute_type,
                download_root=settings.model_cache_dir,
                cpu_threads=4,
                num_workers=2,
            )

            load_time = time.time() - start_time

            model_loaded.labels(model_name="whisper", model_size=self.model_size).set(1)
            model_load_time_seconds.labels(
                model_name="whisper",
                model_size=self.model_size
            ).observe(load_time)

            logger.info(f"Model loaded in {load_time:.2f}s")

            if self.device == "cuda":
                memory_used = torch.cuda.memory_allocated() / (1024**3)
                logger.info(f"GPU memory used: {memory_used:.2f}GB")
                gpu_memory_usage_bytes.labels(device="0").set(
                    torch.cuda.memory_allocated()
                )

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            model_loaded.labels(model_name="whisper", model_size=self.model_size).set(0)
            raise

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        word_timestamps: bool = True,
        **kwargs
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to audio file
            language: Language code (auto-detect if None)
            initial_prompt: Initial prompt to guide transcription
            word_timestamps: Include word-level timestamps

        Returns:
            TranscriptionResult with text, segments, and metadata
        """
        self.load_model()

        start_time = time.time()
        logger.info(f"Starting transcription", extra={"audio_path": audio_path})

        try:
            segments_generator, info = self.model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                beam_size=5,
                best_of=5,
                patience=1.0,
                length_penalty=1.0,
                repetition_penalty=1.0,
                no_repeat_ngram_size=0,
                temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.9,
                condition_on_previous_text=True,
                prompt_reset_on_temperature=0.5,
                initial_prompt=initial_prompt,
                word_timestamps=word_timestamps,
                vad_filter=False,  # Disabled — Whisper handles VAD better for music/songs
            )

            segments: List[TranscriptionSegment] = []
            full_text_parts = []

            for segment in segments_generator:
                words = []
                if segment.words:
                    words = [
                        {
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability,
                        }
                        for w in segment.words
                    ]

                seg = TranscriptionSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                    words=words,
                    confidence=segment.avg_logprob if hasattr(segment, "avg_logprob") else None,
                )
                segments.append(seg)
                full_text_parts.append(segment.text.strip())

            processing_time = time.time() - start_time

            transcription_duration_seconds.labels(
                model_size=self.model_size,
                enable_diarization="false",
            ).observe(processing_time)

            result = TranscriptionResult(
                text=" ".join(full_text_parts),
                segments=segments,
                language=info.language,
                language_probability=info.language_probability,
                duration=info.duration,
                processing_time=processing_time,
            )

            logger.info(
                f"Transcription completed",
                extra={
                    "duration": info.duration,
                    "processing_time": processing_time,
                    "language": info.language,
                    "segments_count": len(segments),
                }
            )

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

    def unload_model(self):
        """Unload the model to free memory."""
        if self.model is not None:
            del self.model
            self.model = None

            if self.device == "cuda":
                torch.cuda.empty_cache()

            model_loaded.labels(model_name="whisper", model_size=self.model_size).set(0)
            logger.info("Model unloaded")

    def __enter__(self):
        self.load_model()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload_model()
