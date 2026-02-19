"""
Prometheus metrics for Speech-to-Text Pipeline.
Defines all metrics used across the application.
"""
from prometheus_client import Counter, Histogram, Gauge, Info

# =============================================================================
# Request Metrics
# =============================================================================

transcription_requests_total = Counter(
    "stt_transcription_requests_total",
    "Total number of transcription requests",
    ["status", "model_size", "format"]
)

transcription_errors_total = Counter(
    "stt_transcription_errors_total",
    "Total number of transcription errors",
    ["error_type", "model_size"]
)

# =============================================================================
# Duration Metrics
# =============================================================================

transcription_duration_seconds = Histogram(
    "stt_transcription_duration_seconds",
    "Time spent on transcription processing",
    ["model_size", "enable_diarization"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600]
)

audio_duration_seconds = Histogram(
    "stt_audio_duration_seconds",
    "Duration of input audio files",
    ["format"],
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600, 7200]
)

preprocessing_duration_seconds = Histogram(
    "stt_preprocessing_duration_seconds",
    "Time spent on audio preprocessing (VAD, normalization)",
    buckets=[0.5, 1, 2, 5, 10, 30, 60]
)

diarization_duration_seconds = Histogram(
    "stt_diarization_duration_seconds",
    "Time spent on speaker diarization",
    buckets=[5, 10, 30, 60, 120, 300, 600]
)

postprocessing_duration_seconds = Histogram(
    "stt_postprocessing_duration_seconds",
    "Time spent on postprocessing (punctuation, formatting)",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30]
)

# =============================================================================
# Queue Metrics
# =============================================================================

active_jobs = Gauge(
    "stt_active_jobs",
    "Number of currently processing jobs"
)

jobs_completed_total = Counter(
    "stt_jobs_completed_total",
    "Total number of completed jobs",
    ["status"]  # success, failed, cancelled
)

# =============================================================================
# Resource Metrics
# =============================================================================

gpu_memory_usage_bytes = Gauge(
    "stt_gpu_memory_usage_bytes",
    "GPU memory usage in bytes",
    ["device"]
)

model_loaded = Gauge(
    "stt_model_loaded",
    "Whether a model is loaded (1) or not (0)",
    ["model_name", "model_size"]
)

model_load_time_seconds = Histogram(
    "stt_model_load_time_seconds",
    "Time to load a model",
    ["model_name", "model_size"],
    buckets=[1, 5, 10, 30, 60, 120]
)

# =============================================================================
# API Metrics
# =============================================================================

api_requests_total = Counter(
    "stt_api_requests_total",
    "Total API requests",
    ["method", "endpoint", "status_code"]
)

api_request_duration_seconds = Histogram(
    "stt_api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10]
)

# =============================================================================
# Application Info
# =============================================================================

app_info = Info(
    "stt_app",
    "Speech-to-Text Pipeline application information"
)
