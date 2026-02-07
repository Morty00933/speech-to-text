"""
Pydantic schemas for API request/response validation.
"""
from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class ModelSize(str, Enum):
    """Available Whisper model sizes."""
    TINY = "tiny"
    BASE = "base"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE_V3 = "large-v3"


class OutputFormat(str, Enum):
    """Available output formats."""
    JSON = "json"
    SRT = "srt"
    VTT = "vtt"
    TXT = "txt"


class JobStatus(str, Enum):
    """Job status."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# =============================================================================
# Request Schemas
# =============================================================================

# Whisper-supported language codes (ISO 639-1 and a few exceptions)
SUPPORTED_LANGUAGES = {
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs",
    "ca", "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi",
    "fo", "fr", "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy",
    "id", "is", "it", "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb",
    "ln", "lo", "lt", "lv", "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt",
    "my", "ne", "nl", "nn", "no", "oc", "pa", "pl", "ps", "pt", "ro", "ru",
    "sa", "sd", "si", "sk", "sl", "sn", "so", "sq", "sr", "su", "sv", "sw",
    "ta", "te", "tg", "th", "tk", "tl", "tr", "tt", "uk", "ur", "uz", "vi",
    "yi", "yo", "zh",
}


class TranscribeOptions(BaseModel):
    """Transcription options."""
    language: Optional[str] = Field(
        None,
        description="Language code (e.g., 'en', 'ru'). Auto-detect if not specified."
    )
    model_size: ModelSize = Field(
        ModelSize.MEDIUM,
        description="Whisper model size to use"
    )
    enable_diarization: bool = Field(
        False,
        description="Enable speaker diarization"
    )
    min_speakers: int = Field(
        1,
        ge=1,
        le=20,
        description="Minimum number of speakers for diarization"
    )
    max_speakers: Optional[int] = Field(
        None,
        ge=1,
        le=20,
        description="Maximum number of speakers for diarization"
    )
    output_format: OutputFormat = Field(
        OutputFormat.JSON,
        description="Output format"
    )
    enable_timestamps: bool = Field(
        True,
        description="Include word-level timestamps"
    )
    enable_punctuation: bool = Field(
        True,
        description="Enable automatic punctuation"
    )
    initial_prompt: Optional[str] = Field(
        None,
        max_length=1000,
        description="Initial prompt to guide transcription"
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v):
        if v is not None:
            v = v.strip().lower()
            if v not in SUPPORTED_LANGUAGES:
                raise ValueError(
                    f"Unsupported language code '{v}'. "
                    f"Use a valid ISO 639-1 code (e.g. 'en', 'ru', 'de') or omit for auto-detection. "
                    f"Supported: {sorted(SUPPORTED_LANGUAGES)}"
                )
        return v

    @field_validator("max_speakers")
    @classmethod
    def validate_max_speakers(cls, v, info):
        if v is not None:
            min_speakers = info.data.get("min_speakers")
            if min_speakers is not None and v < min_speakers:
                raise ValueError("max_speakers must be >= min_speakers")
        return v


class TranscribeURLRequest(BaseModel):
    """Request for URL-based transcription."""
    url: str = Field(..., description="URL of the audio file")
    options: TranscribeOptions = Field(default_factory=TranscribeOptions)


class BatchTranscribeRequest(BaseModel):
    """Request for batch transcription."""
    urls: List[str] = Field(..., min_length=1, max_length=100)
    options: TranscribeOptions = Field(default_factory=TranscribeOptions)


# =============================================================================
# Response Schemas
# =============================================================================

class TranscribeResponse(BaseModel):
    """Response after submitting transcription request."""
    job_id: str
    status: JobStatus
    created_at: datetime
    estimated_wait_time: Optional[int] = Field(
        None,
        description="Estimated wait time in seconds"
    )


class Segment(BaseModel):
    """Single transcription segment."""
    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Transcribed text")
    speaker: Optional[str] = Field(None, description="Speaker ID")
    confidence: Optional[float] = Field(None, description="Confidence score (avg log probability, negative values)")


class Speaker(BaseModel):
    """Speaker information."""
    id: str
    segments_count: int
    total_duration: float


class TranscriptionMetadata(BaseModel):
    """Transcription metadata."""
    language: str
    duration: float
    processing_time: float
    model_used: str
    audio_format: Optional[str] = None
    sample_rate: Optional[int] = None


class TranscriptionResult(BaseModel):
    """Full transcription result."""
    job_id: str
    status: JobStatus
    text: Optional[str] = Field(None, description="Full transcribed text")
    segments: Optional[List[Segment]] = Field(None, description="Transcription segments")
    speakers: Optional[List[Speaker]] = Field(None, description="Speaker information")
    metadata: Optional[TranscriptionMetadata] = None
    error: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Job status response."""
    job_id: str
    status: JobStatus
    progress: int = Field(0, ge=0, le=100)
    current_step: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_time_remaining: Optional[int] = None
    error: Optional[str] = None


class BatchJobFailure(BaseModel):
    """Information about a failed URL in a batch request."""
    url: str
    error: str


class BatchJobResponse(BaseModel):
    """Response for batch transcription."""
    batch_id: str
    jobs: List[TranscribeResponse]
    total_jobs: int
    failed_urls: List[BatchJobFailure] = Field(
        default_factory=list,
        description="URLs that could not be queued, with error details"
    )


# =============================================================================
# Model Information
# =============================================================================

class ModelInfo(BaseModel):
    """Information about available models."""
    name: str
    size: str
    vram_required_gb: float
    languages: int
    description: str
    recommended_for: str
    downloaded: bool = False


class ModelsResponse(BaseModel):
    """Response with available models."""
    models: List[ModelInfo]
    default_model: str


# =============================================================================
# Health Check
# =============================================================================

class ServiceHealth(BaseModel):
    """Health status of a service."""
    name: str
    status: str
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    services: List[ServiceHealth]
