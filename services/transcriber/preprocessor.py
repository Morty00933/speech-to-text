"""
Audio preprocessor with Voice Activity Detection (VAD).
Uses Silero VAD for efficient speech detection.
Supports ffmpeg fallback for OPUS, M4A, OGG and other formats.
"""
import os
import subprocess
import tempfile
from typing import List, Tuple, Optional
from dataclasses import dataclass

import torch
import numpy as np
import librosa
import soundfile as sf

from common.logging_config import get_logger
from common.metrics import preprocessing_duration_seconds

logger = get_logger("transcriber.preprocessor")


@dataclass
class SpeechSegment:
    """Detected speech segment."""
    start: float  # Start time in seconds
    end: float    # End time in seconds


class AudioPreprocessor:
    """
    Audio preprocessor for speech-to-text pipeline.

    Features:
    - Voice Activity Detection (Silero VAD)
    - Audio normalization
    - Resampling to 16kHz
    - Silence removal
    """

    TARGET_SAMPLE_RATE = 16000

    def __init__(self, vad_threshold: float = 0.5):
        """
        Initialize preprocessor.

        Args:
            vad_threshold: VAD sensitivity threshold (0.0-1.0)
        """
        self.vad_threshold = vad_threshold
        self.vad_model = None
        self.get_speech_timestamps = None

        logger.info("Initializing audio preprocessor")

    def _load_vad_model(self):
        """Load Silero VAD model."""
        if self.vad_model is not None:
            return

        logger.info("Loading Silero VAD model")
        try:
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True,
            )
            self.vad_model = model
            self.get_speech_timestamps = utils[0]
            logger.info("Silero VAD model loaded")
        except Exception as e:
            logger.error(f"Failed to load VAD model: {e}")
            raise

    def convert_to_wav_if_needed(self, audio_path: str) -> str:
        """
        Convert audio to WAV via ffmpeg if the format is not natively
        supported by librosa (e.g. OPUS, OGG Opus, some M4A codecs).

        Args:
            audio_path: Path to source audio file

        Returns:
            Path to WAV file (may be the original path if no conversion needed,
            or a new temp file). Caller is responsible for cleanup of temp files.
        """
        # Fast path: if extension looks like a raw PCM-compatible format, skip
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in {".wav", ".flac", ".mp3"}:
            return audio_path

        # Try ffmpeg conversion
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="converted_")
            os.close(fd)
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", audio_path,
                    "-ar", str(self.TARGET_SAMPLE_RATE),
                    "-ac", "1",
                    "-f", "wav",
                    wav_path,
                ],
                capture_output=True,
                timeout=120,
            )
            if result.returncode == 0:
                logger.info(f"ffmpeg converted {ext} → WAV: {wav_path}")
                return wav_path
            else:
                logger.warning(
                    f"ffmpeg conversion failed (rc={result.returncode}), "
                    f"will try librosa directly: {result.stderr.decode(errors='replace')[:200]}"
                )
                os.remove(wav_path)
        except FileNotFoundError:
            logger.warning("ffmpeg not found in PATH, skipping conversion")
        except Exception as e:
            logger.warning(f"ffmpeg conversion error: {e}")

        return audio_path

    def load_audio(self, audio_path: str) -> Tuple[np.ndarray, int]:
        """
        Load audio file and resample to target sample rate.
        Attempts ffmpeg conversion first for formats like OPUS/OGG/M4A
        that may not be natively supported by librosa.

        Args:
            audio_path: Path to audio file

        Returns:
            Tuple of (audio_array, sample_rate)
        """
        logger.info(f"Loading audio: {audio_path}")

        converted_path = self.convert_to_wav_if_needed(audio_path)
        _cleanup_converted = converted_path != audio_path

        try:
            # Load with librosa (handles most formats)
            audio, sr = librosa.load(
                converted_path,
                sr=self.TARGET_SAMPLE_RATE,
                mono=True,
            )

            # Convert to float32 if needed
            if audio.dtype != np.float32:
                audio = audio.astype(np.float32)

            logger.info(
                f"Audio loaded",
                extra={
                    "duration": len(audio) / sr,
                    "sample_rate": sr,
                }
            )

            return audio, sr

        except Exception as e:
            logger.error(f"Failed to load audio: {e}")
            raise
        finally:
            if _cleanup_converted and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except OSError:
                    pass

    def normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Normalize audio to consistent volume level.

        Args:
            audio: Audio array

        Returns:
            Normalized audio array
        """
        # Peak normalization
        max_val = np.abs(audio).max()
        if max_val > 0:
            audio = audio / max_val * 0.95

        return audio

    def detect_speech(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        min_speech_duration_ms: int = 250,
        min_silence_duration_ms: int = 100,
    ) -> List[SpeechSegment]:
        """
        Detect speech segments using Silero VAD.

        Args:
            audio: Audio array
            sample_rate: Sample rate
            min_speech_duration_ms: Minimum speech duration
            min_silence_duration_ms: Minimum silence duration

        Returns:
            List of detected speech segments
        """
        self._load_vad_model()

        # Convert to tensor
        audio_tensor = torch.tensor(audio)

        # Get speech timestamps
        speech_timestamps = self.get_speech_timestamps(
            audio_tensor,
            self.vad_model,
            sampling_rate=sample_rate,
            threshold=self.vad_threshold,
            min_speech_duration_ms=min_speech_duration_ms,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=400,
            return_seconds=True,
        )

        segments = [
            SpeechSegment(start=ts["start"], end=ts["end"])
            for ts in speech_timestamps
        ]

        logger.info(f"Detected {len(segments)} speech segments")
        return segments

    def extract_speech(
        self,
        audio: np.ndarray,
        segments: List[SpeechSegment],
        sample_rate: int = 16000,
        padding_ms: int = 200,
    ) -> np.ndarray:
        """
        Extract only speech portions from audio.

        Args:
            audio: Full audio array
            segments: Speech segments to extract
            sample_rate: Sample rate
            padding_ms: Padding around each segment

        Returns:
            Audio array containing only speech
        """
        if not segments:
            logger.warning("No speech segments to extract")
            return audio

        padding_samples = int(padding_ms * sample_rate / 1000)
        speech_parts = []

        for seg in segments:
            start_sample = max(0, int(seg.start * sample_rate) - padding_samples)
            end_sample = min(len(audio), int(seg.end * sample_rate) + padding_samples)
            speech_parts.append(audio[start_sample:end_sample])

        if speech_parts:
            extracted = np.concatenate(speech_parts)
            reduction = (1 - len(extracted) / len(audio)) * 100
            logger.info(f"Extracted speech, reduced audio by {reduction:.1f}%")
            return extracted

        return audio

    def preprocess(
        self,
        audio_path: str,
        output_path: Optional[str] = None,
        remove_silence: bool = False,  # Disabled by default - Whisper has better VAD
        normalize: bool = True,
    ) -> str:
        """
        Full preprocessing pipeline.

        Args:
            audio_path: Input audio file path
            output_path: Output file path (auto-generated if None)
            remove_silence: Whether to remove silence
            normalize: Whether to normalize volume

        Returns:
            Path to preprocessed audio file
        """
        import time
        start_time = time.time()

        logger.info(f"Starting preprocessing: {audio_path}")

        # Load audio
        audio, sr = self.load_audio(audio_path)
        original_duration = len(audio) / sr

        # Normalize
        if normalize:
            audio = self.normalize_audio(audio)

        # Remove silence using VAD
        if remove_silence:
            segments = self.detect_speech(audio, sr)
            if segments:
                audio = self.extract_speech(audio, segments, sr)

        # Generate output path if not provided
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="preprocessed_")
            os.close(fd)

        # Save preprocessed audio
        sf.write(output_path, audio, sr)

        processing_time = time.time() - start_time
        final_duration = len(audio) / sr

        # Update metrics
        preprocessing_duration_seconds.observe(processing_time)

        logger.info(
            f"Preprocessing completed",
            extra={
                "original_duration": original_duration,
                "final_duration": final_duration,
                "processing_time": processing_time,
                "output_path": output_path,
            }
        )

        return output_path

    def split_audio_chunks(
        self,
        audio_path: str,
        chunk_duration: float = 1800.0,
        overlap: float = 30.0,
    ) -> List[Tuple[str, float]]:
        """
        Split a long audio file into overlapping chunks.

        Args:
            audio_path: Path to audio file
            chunk_duration: Duration of each chunk in seconds (default 30 min)
            overlap: Overlap between chunks in seconds (default 30 s)

        Returns:
            List of (chunk_file_path, chunk_start_offset_seconds) tuples.
            Caller must delete the temp files after use.
        """
        logger.info(
            f"Splitting audio into chunks",
            extra={"chunk_duration": chunk_duration, "overlap": overlap},
        )

        converted_path = self.convert_to_wav_if_needed(audio_path)
        _cleanup = converted_path != audio_path

        try:
            audio, sr = librosa.load(converted_path, sr=self.TARGET_SAMPLE_RATE, mono=True)
        finally:
            if _cleanup and os.path.exists(converted_path):
                try:
                    os.remove(converted_path)
                except OSError:
                    pass

        total_duration = len(audio) / sr
        chunk_samples = int(chunk_duration * sr)
        overlap_samples = int(overlap * sr)
        step_samples = chunk_samples - overlap_samples

        chunks: List[Tuple[str, float]] = []
        start_sample = 0

        while start_sample < len(audio):
            end_sample = min(start_sample + chunk_samples, len(audio))
            chunk_audio = audio[start_sample:end_sample]
            start_offset = start_sample / sr

            fd, chunk_path = tempfile.mkstemp(suffix=".wav", prefix=f"chunk_{len(chunks)}_")
            os.close(fd)
            sf.write(chunk_path, chunk_audio, sr)

            chunks.append((chunk_path, start_offset))
            logger.info(
                f"Created chunk {len(chunks)}",
                extra={
                    "start": start_offset,
                    "end": end_sample / sr,
                    "path": chunk_path,
                },
            )

            if end_sample >= len(audio):
                break
            start_sample += step_samples

        logger.info(
            f"Split audio into {len(chunks)} chunks",
            extra={"total_duration": total_duration},
        )
        return chunks

    def get_audio_info(self, audio_path: str) -> dict:
        """
        Get audio file information.

        Args:
            audio_path: Path to audio file

        Returns:
            Dictionary with audio information
        """
        try:
            import subprocess
            import json

            # Try ffprobe for detailed info
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    audio_path,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                format_info = data.get("format", {})
                stream_info = data.get("streams", [{}])[0]

                return {
                    "duration": float(format_info.get("duration", 0)),
                    "format": format_info.get("format_name"),
                    "sample_rate": int(stream_info.get("sample_rate", 0)),
                    "channels": int(stream_info.get("channels", 0)),
                    "bit_rate": int(format_info.get("bit_rate", 0)),
                }
        except Exception:
            pass

        # Fallback to librosa
        try:
            audio, sr = librosa.load(audio_path, sr=None, mono=True)
            return {
                "duration": len(audio) / sr,
                "sample_rate": sr,
                "channels": 1,
            }
        except Exception as e:
            logger.error(f"Failed to get audio info: {e}")
            return {}
