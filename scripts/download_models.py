#!/usr/bin/env python3
"""
Download and cache ML models for Speech-to-Text Pipeline.
Run this script before first use to pre-download all models.
"""
import os
import sys
import argparse


def download_whisper(model_size: str, cache_dir: str):
    """Download Whisper model."""
    print(f"Downloading Whisper {model_size} model...")
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, download_root=cache_dir)
        print(f"  Whisper {model_size} downloaded successfully!")
        del model
    except Exception as e:
        print(f"  Error downloading Whisper {model_size}: {e}")


def download_silero_vad():
    """Download Silero VAD model."""
    print("Downloading Silero VAD model...")
    try:
        import torch

        model, _ = torch.hub.load(
            'snakers4/silero-vad',
            'silero_vad',
            force_reload=False,
            trust_repo=True,
        )
        print("  Silero VAD downloaded successfully!")
        del model
    except Exception as e:
        print(f"  Error downloading Silero VAD: {e}")


def download_pyannote(hf_token: str):
    """Download pyannote speaker diarization model."""
    if not hf_token:
        print("Skipping pyannote (no HF_TOKEN provided)")
        return

    print("Downloading pyannote speaker diarization model...")
    try:
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        print("  pyannote speaker diarization downloaded successfully!")
        del pipeline
    except Exception as e:
        print(f"  Error downloading pyannote: {e}")


def download_punctuation():
    """Download punctuation restoration model."""
    print("Downloading punctuation restoration model...")
    try:
        from deepmultilingualpunctuation import PunctuationModel

        model = PunctuationModel(
            model="oliverguhr/fullstop-punctuation-multilang-large"
        )
        print("  Punctuation model downloaded successfully!")
        del model
    except Exception as e:
        print(f"  Error downloading punctuation model: {e}")


def main():
    parser = argparse.ArgumentParser(description="Download ML models")
    parser.add_argument(
        "--model-size",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size to download",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("MODEL_CACHE_DIR", "./models"),
        help="Directory to cache models",
    )
    parser.add_argument(
        "--all-whisper",
        action="store_true",
        help="Download all Whisper models",
    )
    parser.add_argument(
        "--skip-diarization",
        action="store_true",
        help="Skip pyannote diarization model",
    )
    args = parser.parse_args()

    # Ensure cache directory exists
    os.makedirs(args.cache_dir, exist_ok=True)

    print("=" * 60)
    print("Speech-to-Text Pipeline - Model Downloader")
    print("=" * 60)
    print(f"Cache directory: {args.cache_dir}")
    print()

    # Download Whisper
    if args.all_whisper:
        for size in ["tiny", "base", "small", "medium"]:
            download_whisper(size, args.cache_dir)
    else:
        download_whisper(args.model_size, args.cache_dir)

    # Download Silero VAD
    download_silero_vad()

    # Download pyannote
    if not args.skip_diarization:
        hf_token = os.getenv("HF_TOKEN")
        download_pyannote(hf_token)

    # Download punctuation model
    download_punctuation()

    print()
    print("=" * 60)
    print("Model download complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
