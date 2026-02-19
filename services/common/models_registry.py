"""
Single source of truth for Whisper model metadata.

Used by both the API layer (model listing) and the transcription engine
(VRAM requirements) to avoid duplication.
"""
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class WhisperModelInfo:
    """Metadata for a Whisper model variant."""
    name: str
    parameters: str
    vram_required_gb: float
    languages: int
    description: str
    recommended_for: str


WHISPER_MODELS: List[WhisperModelInfo] = [
    WhisperModelInfo(
        name="tiny",
        parameters="39M parameters",
        vram_required_gb=1.0,
        languages=99,
        description="Fastest model, lower accuracy",
        recommended_for="Quick drafts, real-time transcription",
    ),
    WhisperModelInfo(
        name="base",
        parameters="74M parameters",
        vram_required_gb=1.0,
        languages=99,
        description="Good balance of speed and accuracy",
        recommended_for="Simple audio, clear speech",
    ),
    WhisperModelInfo(
        name="small",
        parameters="244M parameters",
        vram_required_gb=2.0,
        languages=99,
        description="Better accuracy, moderate speed",
        recommended_for="General purpose transcription",
    ),
    WhisperModelInfo(
        name="medium",
        parameters="769M parameters",
        vram_required_gb=5.0,
        languages=99,
        description="High accuracy, good for multiple languages",
        recommended_for="Professional transcription, multilingual",
    ),
    WhisperModelInfo(
        name="large-v3",
        parameters="1550M parameters",
        vram_required_gb=10.0,
        languages=99,
        description="Best accuracy, slowest",
        recommended_for="Maximum quality, complex audio",
    ),
]

# Quick lookup: model name -> VRAM requirement in GB
MODEL_VRAM: Dict[str, float] = {m.name: m.vram_required_gb for m in WHISPER_MODELS}
