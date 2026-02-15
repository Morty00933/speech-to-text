"""
Post-processing for transcription results.
Handles punctuation restoration, formatting, and output generation.
"""
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from common.logging_config import get_logger
from common.metrics import postprocessing_duration_seconds

logger = get_logger("transcriber.postprocessor")


@dataclass
class ProcessedSegment:
    """Processed transcription segment."""
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    words: Optional[List[Dict]] = None


class Postprocessor:
    """
    Post-processor for transcription results.

    Features:
    - Punctuation restoration
    - Text capitalization
    - Number normalization
    - Multiple output formats (JSON, SRT, VTT, TXT)
    """

    def __init__(self, use_punctuation_model: bool = True):
        """
        Initialize postprocessor.

        Args:
            use_punctuation_model: Use ML model for punctuation restoration
        """
        self.punctuator = None
        self.use_punctuation_model = use_punctuation_model

        if use_punctuation_model:
            self._load_punctuator()

    def _load_punctuator(self):
        """Load punctuation restoration model."""
        try:
            from deepmultilingualpunctuation import PunctuationModel

            logger.info("Loading punctuation model")
            self.punctuator = PunctuationModel(
                model="oliverguhr/fullstop-punctuation-multilang-large"
            )
            logger.info("Punctuation model loaded")
        except ImportError:
            logger.warning(
                "deepmultilingualpunctuation not installed. "
                "Using rule-based punctuation."
            )
            self.punctuator = None
        except Exception as e:
            logger.warning(f"Failed to load punctuation model: {e}")
            self.punctuator = None

    def restore_punctuation(self, text: str) -> str:
        """
        Restore punctuation in text.

        Args:
            text: Input text without punctuation

        Returns:
            Text with restored punctuation
        """
        if not text or not text.strip():
            return text

        if self.punctuator:
            try:
                return self.punctuator.restore_punctuation(text)
            except Exception as e:
                logger.warning(f"Punctuation restoration failed: {e}")

        # Fallback: rule-based punctuation
        return self._rule_based_punctuation(text)

    def _rule_based_punctuation(self, text: str) -> str:
        """Simple rule-based punctuation restoration."""
        # Capitalize first letter
        if text:
            text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()

        # Add period at end if missing
        if text and text[-1] not in ".!?":
            text += "."

        return text

    def capitalize_sentences(self, text: str) -> str:
        """
        Capitalize the first letter of each sentence.

        Args:
            text: Input text

        Returns:
            Text with capitalized sentences
        """
        # Split by sentence-ending punctuation
        sentences = re.split(r'([.!?]+\s*)', text)
        result = []

        for i, part in enumerate(sentences):
            if i > 0 and sentences[i - 1] and sentences[i - 1].strip()[-1] in '.!?':
                # This is the start of a new sentence
                part = part.strip()
                if part:
                    part = part[0].upper() + part[1:] if len(part) > 1 else part.upper()
            result.append(part)

        return ''.join(result)

    def normalize_text(self, text: str) -> str:
        """
        Normalize text (numbers, common errors, etc.).

        Args:
            text: Input text

        Returns:
            Normalized text
        """
        # Fix common transcription issues
        replacements = [
            (r'\s+', ' '),                    # Multiple spaces
            (r'^\s+|\s+$', ''),               # Leading/trailing spaces
            (r'\s+([.,!?])', r'\1'),          # Space before punctuation
            (r'([.,!?])(\w)', r'\1 \2'),      # Missing space after punctuation
        ]

        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)

        return text

    def process_segments(
        self,
        segments: List[Dict[str, Any]],
        restore_punctuation: bool = True,
    ) -> List[ProcessedSegment]:
        """
        Process all transcription segments.

        Args:
            segments: Raw transcription segments
            restore_punctuation: Whether to restore punctuation

        Returns:
            List of processed segments
        """
        import time
        start_time = time.time()

        processed = []

        for seg in segments:
            text = seg.get("text", "").strip()

            # Process text
            if restore_punctuation and text:
                text = self.restore_punctuation(text)
            text = self.capitalize_sentences(text)
            text = self.normalize_text(text)

            processed.append(ProcessedSegment(
                start=seg.get("start", 0),
                end=seg.get("end", 0),
                text=text,
                speaker=seg.get("speaker"),
                confidence=seg.get("confidence"),
                words=seg.get("words"),
            ))

        processing_time = time.time() - start_time
        postprocessing_duration_seconds.observe(processing_time)

        logger.info(
            f"Postprocessing completed",
            extra={"segments_count": len(processed), "processing_time": processing_time}
        )

        return processed

    def format_output(
        self,
        segments: List[ProcessedSegment],
        format: str = "json",
        include_speakers: bool = False,
    ) -> str:
        """
        Format segments to specified output format.

        Args:
            segments: Processed segments
            format: Output format (json, srt, vtt, txt)
            include_speakers: Include speaker labels

        Returns:
            Formatted output string
        """
        formatters = {
            "json": self._to_json,
            "srt": self._to_srt,
            "vtt": self._to_vtt,
            "txt": self._to_txt,
        }

        formatter = formatters.get(format.lower(), self._to_json)
        return formatter(segments, include_speakers)

    def _to_json(self, segments: List[ProcessedSegment], include_speakers: bool) -> str:
        """Format as JSON."""
        import json

        data = {
            "text": " ".join(s.text for s in segments),
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    **({"speaker": s.speaker} if include_speakers and s.speaker else {}),
                    **({"confidence": s.confidence} if s.confidence else {}),
                }
                for s in segments
            ],
        }

        return json.dumps(data, ensure_ascii=False, indent=2)

    def _to_srt(self, segments: List[ProcessedSegment], include_speakers: bool) -> str:
        """Format as SRT subtitles."""
        lines = []

        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp_srt(seg.start)
            end = self._format_timestamp_srt(seg.end)

            text = seg.text
            if include_speakers and seg.speaker:
                text = f"[{seg.speaker}] {text}"

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def _to_vtt(self, segments: List[ProcessedSegment], include_speakers: bool) -> str:
        """Format as WebVTT subtitles."""
        lines = ["WEBVTT", ""]

        for i, seg in enumerate(segments, 1):
            start = self._format_timestamp_vtt(seg.start)
            end = self._format_timestamp_vtt(seg.end)

            text = seg.text
            if include_speakers and seg.speaker:
                text = f"<v {seg.speaker}>{text}"

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def _to_txt(self, segments: List[ProcessedSegment], include_speakers: bool) -> str:
        """Format as plain text."""
        lines = []
        current_speaker = None

        for seg in segments:
            if include_speakers and seg.speaker and seg.speaker != current_speaker:
                current_speaker = seg.speaker
                lines.append(f"\n[{current_speaker}]")

            lines.append(seg.text)

        return " ".join(lines).strip()

    def _format_timestamp_srt(self, seconds: float) -> str:
        """Format timestamp for SRT format (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _format_timestamp_vtt(self, seconds: float) -> str:
        """Format timestamp for VTT format (HH:MM:SS.mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
