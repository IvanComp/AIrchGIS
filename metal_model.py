#!/usr/bin/env python3
"""Model loading and inference utilities for metal-type audio classification.

Designed for mobile-friendly inference with TensorFlow Lite models.
"""

from __future__ import annotations

import argparse
import pathlib
import time
import wave
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:  # Fallback for environments with full TensorFlow installed.
    from tensorflow.lite.python.interpreter import Interpreter  # type: ignore


@dataclass
class AudioFeatureConfig:
    sample_rate: int = 16000
    clip_seconds: float = 1.0
    n_fft: int = 512
    hop_length: int = 160
    win_length: int = 400
    n_mels: int = 64
    f_min: float = 20.0
    f_max: float = 8000.0


MODEL_VARIANTS = {
    "tiny": "metalnet_tiny.tflite",
    "small": "metalnet_small.tflite",
    "medium": "metalnet_medium.tflite",
    "large": "metalnet_large.tflite",
}


def get_model_path_for_complexity(complexity: str, model_dir: str = "models") -> pathlib.Path:
    key = complexity.lower().strip()
    if key not in MODEL_VARIANTS:
        supported = ", ".join(MODEL_VARIANTS)
        raise ValueError(f"Unknown complexity '{complexity}'. Supported: {supported}")
    return pathlib.Path(model_dir) / MODEL_VARIANTS[key]


class MetalAudioClassifier:
    def __init__(
        self,
        model_path: str,
        labels_path: str,
        feature_cfg: AudioFeatureConfig | None = None,
        num_threads: int = 2,
    ) -> None:
        self.feature_cfg = feature_cfg or AudioFeatureConfig()
        self.labels = self._load_labels(labels_path)
        self.model_path = str(model_path)

        self.interpreter = Interpreter(model_path=self.model_path, num_threads=num_threads)
        self.interpreter.allocate_tensors()

        self.input_details = self.interpreter.get_input_details()[0]
        self.output_details = self.interpreter.get_output_details()[0]

        self.target_samples = int(self.feature_cfg.sample_rate * self.feature_cfg.clip_seconds)
        self.mel_filterbank = self._build_mel_filterbank(
            sample_rate=self.feature_cfg.sample_rate,
            n_fft=self.feature_cfg.n_fft,
            n_mels=self.feature_cfg.n_mels,
            f_min=self.feature_cfg.f_min,
            f_max=self.feature_cfg.f_max,
        )

    @staticmethod
    def _load_labels(labels_path: str) -> List[str]:
        labels = [line.strip() for line in pathlib.Path(labels_path).read_text().splitlines() if line.strip()]
        if not labels:
            raise ValueError("Labels file is empty.")
        return labels

    @staticmethod
    def _hz_to_mel(freq_hz: np.ndarray) -> np.ndarray:
        return 2595.0 * np.log10(1.0 + freq_hz / 700.0)

    @staticmethod
    def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
        return 700.0 * (10 ** (mel / 2595.0) - 1.0)

    def _build_mel_filterbank(
        self,
        sample_rate: int,
        n_fft: int,
        n_mels: int,
        f_min: float,
        f_max: float,
    ) -> np.ndarray:
        mel_edges = np.linspace(
            self._hz_to_mel(np.array([f_min]))[0],
            self._hz_to_mel(np.array([f_max]))[0],
            n_mels + 2,
        )
        hz_edges = self._mel_to_hz(mel_edges)
        bin_edges = np.floor((n_fft + 1) * hz_edges / sample_rate).astype(int)

        fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for m in range(1, n_mels + 1):
            left = bin_edges[m - 1]
            center = bin_edges[m]
            right = bin_edges[m + 1]

            if center <= left:
                center = left + 1
            if right <= center:
                right = center + 1

            fb[m - 1, left:center] = (np.arange(left, center) - left) / max(center - left, 1)
            fb[m - 1, center:right] = (right - np.arange(center, right)) / max(right - center, 1)

        fb_sum = fb.sum(axis=1, keepdims=True)
        fb_sum[fb_sum == 0] = 1.0
        return fb / fb_sum

    def _prepare_audio(self, audio: np.ndarray) -> np.ndarray:
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = audio.astype(np.float32)

        peak = np.max(np.abs(audio)) + 1e-9
        audio = audio / peak

        if len(audio) < self.target_samples:
            audio = np.pad(audio, (0, self.target_samples - len(audio)))
        elif len(audio) > self.target_samples:
            audio = audio[: self.target_samples]
        return audio

    def _extract_log_mel(self, audio: np.ndarray) -> np.ndarray:
        cfg = self.feature_cfg
        audio = self._prepare_audio(audio)

        if len(audio) < cfg.win_length:
            audio = np.pad(audio, (0, cfg.win_length - len(audio)))

        n_frames = 1 + max(0, (len(audio) - cfg.win_length) // cfg.hop_length)
        if n_frames == 0:
            n_frames = 1
            audio = np.pad(audio, (0, cfg.win_length - len(audio)))

        stride = audio.strides[0]
        frames = np.lib.stride_tricks.as_strided(
            audio,
            shape=(n_frames, cfg.win_length),
            strides=(cfg.hop_length * stride, stride),
            writeable=False,
        ).copy()

        frames *= np.hanning(cfg.win_length).astype(np.float32)
        spectrum = np.fft.rfft(frames, n=cfg.n_fft, axis=1)
        power_spec = (np.abs(spectrum) ** 2).astype(np.float32)

        mel_spec = power_spec @ self.mel_filterbank.T
        log_mel = np.log(mel_spec + 1e-6)

        mean = float(log_mel.mean())
        std = float(log_mel.std() + 1e-6)
        log_mel = (log_mel - mean) / std

        return log_mel.T

    def _reshape_for_model(self, features: np.ndarray) -> np.ndarray:
        expected_shape = self.input_details["shape"]
        arr = features

        if len(expected_shape) == 2:
            arr = arr.reshape(1, -1)
        elif len(expected_shape) == 3:
            if expected_shape[1] == features.shape[0] and expected_shape[2] == features.shape[1]:
                arr = features[np.newaxis, :, :]
            else:
                arr = features.T[np.newaxis, :, :]
        elif len(expected_shape) == 4:
            if expected_shape[1] == features.shape[0] and expected_shape[2] == features.shape[1]:
                arr = features[np.newaxis, :, :, np.newaxis]
            else:
                arr = features.T[np.newaxis, :, :, np.newaxis]
        else:
            raise ValueError(f"Unsupported model input shape: {expected_shape}")

        input_dtype = self.input_details["dtype"]
        if input_dtype == np.int8:
            scale, zero_point = self.input_details["quantization"]
            if scale == 0:
                raise ValueError("Invalid quantization scale=0 for int8 model input.")
            arr = np.clip(np.round(arr / scale + zero_point), -128, 127).astype(np.int8)
        else:
            arr = arr.astype(np.float32)
        return arr

    def _decode_output(self, raw_output: np.ndarray) -> np.ndarray:
        output = raw_output.astype(np.float32).flatten()

        output_dtype = self.output_details["dtype"]
        if output_dtype == np.int8:
            scale, zero_point = self.output_details["quantization"]
            output = scale * (output - zero_point)

        is_prob_like = np.all(output >= 0.0) and np.all(output <= 1.0) and 0.98 <= output.sum() <= 1.02
        if is_prob_like:
            probs = output
        else:
            logits = output - np.max(output)
            exp = np.exp(logits)
            probs = exp / (np.sum(exp) + 1e-9)
        return probs

    def predict(self, audio: np.ndarray, top_k: int = 3) -> Dict[str, object]:
        features = self._extract_log_mel(audio)
        model_input = self._reshape_for_model(features)

        self.interpreter.set_tensor(self.input_details["index"], model_input)
        self.interpreter.invoke()
        raw_output = self.interpreter.get_tensor(self.output_details["index"])
        probs = self._decode_output(raw_output)

        if len(probs) != len(self.labels):
            raise ValueError(
                f"Label count ({len(self.labels)}) does not match model output classes ({len(probs)})."
            )

        ranking = np.argsort(probs)[::-1]
        top_indices = ranking[: min(top_k, len(ranking))]

        top_prediction = {
            "label": self.labels[top_indices[0]],
            "confidence_percent": round(float(probs[top_indices[0]]) * 100.0, 2),
        }
        all_confidences = [
            {
                "label": self.labels[i],
                "confidence_percent": round(float(probs[i]) * 100.0, 2),
            }
            for i in ranking
        ]

        return {
            "top_prediction": top_prediction,
            "top_k": [
                {
                    "label": self.labels[i],
                    "confidence_percent": round(float(probs[i]) * 100.0, 2),
                }
                for i in top_indices
            ],
            "all_confidences": all_confidences,
        }


def read_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        data = wf.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError("Only 16-bit PCM WAV files are supported for this quick test loader.")

    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sample_rate


def resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    src_idx = np.arange(len(audio), dtype=np.float32)
    dst_len = int(len(audio) * (dst_sr / src_sr))
    dst_idx = np.linspace(0, len(audio) - 1, num=dst_len, dtype=np.float32)
    return np.interp(dst_idx, src_idx, audio).astype(np.float32)


def benchmark_models(
    complexity_levels: List[str],
    model_dir: str,
    labels_path: str,
    sample_audio: np.ndarray,
) -> None:
    print("Benchmarking model complexity options:")
    for level in complexity_levels:
        model_path = get_model_path_for_complexity(level, model_dir=model_dir)
        classifier = MetalAudioClassifier(str(model_path), labels_path)

        for _ in range(3):
            classifier.predict(sample_audio)

        runs = 20
        start = time.perf_counter()
        for _ in range(runs):
            classifier.predict(sample_audio)
        elapsed_ms = (time.perf_counter() - start) * 1000 / runs
        print(f"  {level:>6}: {elapsed_ms:7.2f} ms / inference")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TFLite inference for metal audio classification.")
    parser.add_argument("--labels", required=True, help="Path to labels.txt")
    parser.add_argument("--audio", required=True, help="Path to a test WAV clip")
    parser.add_argument("--model", help="Path to a .tflite model file")
    parser.add_argument(
        "--complexity",
        choices=list(MODEL_VARIANTS.keys()),
        default="small",
        help="Model size preset when --model is not provided.",
    )
    parser.add_argument("--model-dir", default="models", help="Directory containing complexity variants")
    parser.add_argument("--benchmark", action="store_true", help="Benchmark all complexity variants")
    args = parser.parse_args()

    audio, sr = read_wav_mono(args.audio)

    if args.benchmark:
        benchmark_models(list(MODEL_VARIANTS.keys()), args.model_dir, args.labels, resample_linear(audio, sr, 16000))
        return

    model_path = args.model or str(get_model_path_for_complexity(args.complexity, args.model_dir))
    classifier = MetalAudioClassifier(model_path=model_path, labels_path=args.labels)

    if sr != classifier.feature_cfg.sample_rate:
        audio = resample_linear(audio, sr, classifier.feature_cfg.sample_rate)

    prediction = classifier.predict(audio, top_k=3)

    top = prediction["top_prediction"]
    print(f"Top prediction: {top['label']} ({top['confidence_percent']}%)")
    print("Top classes:")
    for item in prediction["top_k"]:
        print(f"  - {item['label']}: {item['confidence_percent']}%")


if __name__ == "__main__":
    main()
