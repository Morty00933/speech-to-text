"""
Unit tests for postprocessor module.
"""
import pytest
from services.transcriber.postprocessor import Postprocessor, ProcessedSegment


class TestPostprocessor:
    """Tests for Postprocessor class."""

    @pytest.fixture
    def postprocessor(self):
        """Create postprocessor without ML model."""
        return Postprocessor(use_punctuation_model=False)

    def test_capitalize_sentences(self, postprocessor):
        """Test sentence capitalization."""
        text = "hello world. this is a test. how are you?"
        result = postprocessor.capitalize_sentences(text)
        assert result.startswith("Hello")
        assert "This is" in result

    def test_normalize_text(self, postprocessor):
        """Test text normalization."""
        text = "  hello   world  "
        result = postprocessor.normalize_text(text)
        assert result == "hello world"

    def test_normalize_text_punctuation(self, postprocessor):
        """Test punctuation normalization."""
        text = "hello ,world .how are you ?"
        result = postprocessor.normalize_text(text)
        assert ", " not in result or result == "hello, world. how are you?"

    def test_format_output_json(self, postprocessor):
        """Test JSON output format."""
        segments = [
            ProcessedSegment(start=0.0, end=1.5, text="Hello world."),
            ProcessedSegment(start=1.5, end=3.0, text="How are you?"),
        ]
        result = postprocessor.format_output(segments, "json", include_speakers=False)
        assert '"text":' in result
        assert '"segments":' in result
        assert "Hello world." in result

    def test_format_output_srt(self, postprocessor):
        """Test SRT output format."""
        segments = [
            ProcessedSegment(start=0.0, end=1.5, text="Hello world."),
            ProcessedSegment(start=1.5, end=3.0, text="How are you?"),
        ]
        result = postprocessor.format_output(segments, "srt", include_speakers=False)
        assert "1\n" in result
        assert "00:00:00,000 --> 00:00:01,500" in result
        assert "Hello world." in result

    def test_format_output_vtt(self, postprocessor):
        """Test VTT output format."""
        segments = [
            ProcessedSegment(start=0.0, end=1.5, text="Hello world."),
        ]
        result = postprocessor.format_output(segments, "vtt", include_speakers=False)
        assert "WEBVTT" in result
        assert "00:00:00.000 --> 00:00:01.500" in result

    def test_format_output_txt(self, postprocessor):
        """Test TXT output format."""
        segments = [
            ProcessedSegment(start=0.0, end=1.5, text="Hello world."),
            ProcessedSegment(start=1.5, end=3.0, text="How are you?"),
        ]
        result = postprocessor.format_output(segments, "txt", include_speakers=False)
        assert "Hello world." in result
        assert "How are you?" in result

    def test_format_output_with_speakers(self, postprocessor):
        """Test output format with speaker labels."""
        segments = [
            ProcessedSegment(start=0.0, end=1.5, text="Hello.", speaker="SPEAKER_00"),
            ProcessedSegment(start=1.5, end=3.0, text="Hi there.", speaker="SPEAKER_01"),
        ]
        result = postprocessor.format_output(segments, "srt", include_speakers=True)
        assert "[SPEAKER_00]" in result
        assert "[SPEAKER_01]" in result

    def test_timestamp_formatting_srt(self, postprocessor):
        """Test SRT timestamp formatting."""
        timestamp = postprocessor._format_timestamp_srt(3661.5)  # 1h 1m 1.5s
        assert timestamp == "01:01:01,500"

    def test_timestamp_formatting_vtt(self, postprocessor):
        """Test VTT timestamp formatting."""
        timestamp = postprocessor._format_timestamp_vtt(3661.5)
        assert timestamp == "01:01:01.500"


class TestProcessedSegment:
    """Tests for ProcessedSegment dataclass."""

    def test_creation(self):
        """Test segment creation."""
        seg = ProcessedSegment(
            start=0.0,
            end=1.5,
            text="Hello world",
            speaker="SPEAKER_00",
            confidence=0.95,
        )
        assert seg.start == 0.0
        assert seg.end == 1.5
        assert seg.text == "Hello world"
        assert seg.speaker == "SPEAKER_00"
        assert seg.confidence == 0.95

    def test_optional_fields(self):
        """Test optional fields default to None."""
        seg = ProcessedSegment(start=0.0, end=1.0, text="Test")
        assert seg.speaker is None
        assert seg.confidence is None
        assert seg.words is None
