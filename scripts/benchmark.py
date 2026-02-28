#!/usr/bin/env python3
"""
Benchmark script for Speech-to-Text Pipeline.
Tests transcription performance with various configurations.
"""
import os
import sys
import time
import argparse
import tempfile
from typing import List, Dict

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_test_audio(duration_seconds: int = 60) -> str:
    """Generate a test audio file with speech."""
    import numpy as np
    import soundfile as sf

    sample_rate = 16000
    samples = int(duration_seconds * sample_rate)

    # Generate simple tone (placeholder - in real scenario use actual speech)
    t = np.linspace(0, duration_seconds, samples)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t)  # 440 Hz tone

    # Add some noise
    audio += 0.1 * np.random.randn(samples)

    # Save to temp file
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    sf.write(path, audio, sample_rate)

    return path


def benchmark_transcription(
    audio_path: str,
    model_sizes: List[str],
    num_runs: int = 3,
) -> Dict:
    """Benchmark transcription with different model sizes."""
    from services.transcriber.engine import TranscriptionEngine

    results = {}

    for model_size in model_sizes:
        print(f"\nBenchmarking model: {model_size}")
        print("-" * 40)

        engine = TranscriptionEngine(model_size=model_size)

        times = []
        for i in range(num_runs):
            print(f"  Run {i + 1}/{num_runs}...", end=" ", flush=True)

            start = time.time()
            result = engine.transcribe(audio_path)
            elapsed = time.time() - start

            times.append(elapsed)
            print(f"{elapsed:.2f}s")

        # Calculate stats
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        rtf = avg_time / result.duration  # Real-Time Factor

        results[model_size] = {
            "avg_time": avg_time,
            "min_time": min_time,
            "max_time": max_time,
            "rtf": rtf,
            "audio_duration": result.duration,
        }

        print(f"  Average: {avg_time:.2f}s")
        print(f"  RTF: {rtf:.3f}")

        # Cleanup
        engine.unload_model()

    return results


def benchmark_preprocessing(audio_path: str, num_runs: int = 5) -> Dict:
    """Benchmark audio preprocessing."""
    from services.transcriber.preprocessor import AudioPreprocessor

    print("\nBenchmarking preprocessing")
    print("-" * 40)

    preprocessor = AudioPreprocessor()

    times = []
    for i in range(num_runs):
        print(f"  Run {i + 1}/{num_runs}...", end=" ", flush=True)

        start = time.time()
        output_path = preprocessor.preprocess(audio_path)
        elapsed = time.time() - start

        times.append(elapsed)
        print(f"{elapsed:.2f}s")

        # Cleanup temp file
        if output_path != audio_path:
            os.remove(output_path)

    avg_time = sum(times) / len(times)

    return {
        "avg_time": avg_time,
        "min_time": min(times),
        "max_time": max(times),
    }


def print_results(results: Dict):
    """Print benchmark results in a nice format."""
    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)

    if "transcription" in results:
        print("\nTranscription Performance:")
        print("-" * 40)
        print(f"{'Model':<12} {'Avg Time':<12} {'RTF':<10} {'Speed':<15}")
        print("-" * 40)

        for model, data in results["transcription"].items():
            speed = f"{1/data['rtf']:.1f}x real-time"
            print(f"{model:<12} {data['avg_time']:.2f}s{'':<6} {data['rtf']:.3f}{'':<5} {speed:<15}")

    if "preprocessing" in results:
        print("\nPreprocessing Performance:")
        print("-" * 40)
        data = results["preprocessing"]
        print(f"Average time: {data['avg_time']:.2f}s")
        print(f"Range: {data['min_time']:.2f}s - {data['max_time']:.2f}s")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Benchmark Speech-to-Text Pipeline")
    parser.add_argument(
        "--audio",
        help="Path to audio file for benchmarking",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration of generated test audio (seconds)",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=["tiny", "small", "medium"],
        help="Model sizes to benchmark",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per model",
    )
    parser.add_argument(
        "--skip-preprocessing",
        action="store_true",
        help="Skip preprocessing benchmark",
    )
    args = parser.parse_args()

    # Get or generate test audio
    if args.audio:
        audio_path = args.audio
        cleanup_audio = False
    else:
        print(f"Generating {args.duration}s test audio...")
        audio_path = generate_test_audio(args.duration)
        cleanup_audio = True

    try:
        results = {}

        # Benchmark transcription
        results["transcription"] = benchmark_transcription(
            audio_path,
            args.models,
            args.runs,
        )

        # Benchmark preprocessing
        if not args.skip_preprocessing:
            results["preprocessing"] = benchmark_preprocessing(
                audio_path,
                args.runs,
            )

        # Print results
        print_results(results)

    finally:
        # Cleanup
        if cleanup_audio and os.path.exists(audio_path):
            os.remove(audio_path)


if __name__ == "__main__":
    main()
