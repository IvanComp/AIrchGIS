#!/usr/bin/env python3
"""Train and compare 3 strong audio models with static config.

No CLI arguments are required.
At launch, choose dataset: YESNO or RUTUS.
"""

from __future__ import annotations

import json
import random
import shutil
import wave
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
import torchaudio
from matplotlib.backends.backend_pdf import PdfPages

SEED = 42
EPOCHS = 35
BATCH_SIZE = 16
VAL_RATIO = 0.15
TEST_RATIO = 0.15
MODEL_VARIANTS = ["small", "medium", "big"]

TARGET_SR = 16000
CLIP_SECONDS = 1.0
N_FFT = 512
HOP = 160
WIN = 400
N_MELS = 64

DATA_DIR = Path("data")
YESNO_ROOT = DATA_DIR / "yesno"
RUTUS_ROOT = DATA_DIR / "rutus"
OUTPUT_ROOT = Path("artifacts")


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)


def hz_to_mel(freq_hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + freq_hz / 700.0)


def mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10 ** (mel / 2595.0) - 1.0)


def build_mel_filterbank(sample_rate: int, n_fft: int, n_mels: int, f_min: float, f_max: float) -> np.ndarray:
    mel_edges = np.linspace(hz_to_mel(np.array([f_min]))[0], hz_to_mel(np.array([f_max]))[0], n_mels + 2)
    hz_edges = mel_to_hz(mel_edges)
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


def resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    src_idx = np.arange(len(audio), dtype=np.float32)
    dst_len = int(len(audio) * (dst_sr / src_sr))
    dst_idx = np.linspace(0, len(audio) - 1, num=max(dst_len, 1), dtype=np.float32)
    return np.interp(dst_idx, src_idx, audio).astype(np.float32)


def extract_log_mel(
    audio: np.ndarray,
    sample_rate: int,
    target_samples: int,
    n_fft: int,
    hop_length: int,
    win_length: int,
    mel_filterbank: np.ndarray,
) -> np.ndarray:
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    audio = resample_linear(audio.astype(np.float32), sample_rate, TARGET_SR)
    audio = audio / (np.max(np.abs(audio)) + 1e-8)

    if len(audio) < target_samples:
        audio = np.pad(audio, (0, target_samples - len(audio)))
    elif len(audio) > target_samples:
        audio = audio[:target_samples]

    if len(audio) < win_length:
        audio = np.pad(audio, (0, win_length - len(audio)))

    n_frames = 1 + max(0, (len(audio) - win_length) // hop_length)
    if n_frames <= 0:
        n_frames = 1

    stride = audio.strides[0]
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(n_frames, win_length),
        strides=(hop_length * stride, stride),
        writeable=False,
    ).copy()

    frames *= np.hanning(win_length).astype(np.float32)
    spectrum = np.fft.rfft(frames, n=n_fft, axis=1)
    power_spec = (np.abs(spectrum) ** 2).astype(np.float32)

    mel_spec = power_spec @ mel_filterbank.T
    log_mel = np.log(mel_spec + 1e-6)

    mean = float(log_mel.mean())
    std = float(log_mel.std() + 1e-6)
    return ((log_mel - mean) / std).T.astype(np.float32)


def _frame_rms(audio: np.ndarray, frame_len: int, hop_len: int) -> np.ndarray:
    if len(audio) < frame_len:
        audio = np.pad(audio, (0, frame_len - len(audio)))

    n = 1 + max(0, (len(audio) - frame_len) // hop_len)
    stride = audio.strides[0]
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(n, frame_len),
        strides=(hop_len * stride, stride),
        writeable=False,
    )
    return np.sqrt(np.mean(frames * frames, axis=1) + 1e-10)


def _detect_voiced_regions(audio: np.ndarray, sample_rate: int) -> List[Tuple[int, int]]:
    frame_len = max(64, int(0.025 * sample_rate))
    hop_len = max(32, int(0.010 * sample_rate))

    rms = _frame_rms(audio, frame_len, hop_len)
    smooth = np.convolve(rms, np.ones(5, dtype=np.float32) / 5.0, mode="same")

    med = float(np.median(smooth))
    p90 = float(np.percentile(smooth, 90))
    mx = float(np.max(smooth))
    thr = max(med + 0.35 * (p90 - med), 0.12 * mx)

    voiced = smooth > thr
    regions: List[Tuple[int, int]] = []

    i = 0
    while i < len(voiced):
        if voiced[i]:
            j = i + 1
            while j < len(voiced) and voiced[j]:
                j += 1
            start = i * hop_len
            end = min(len(audio), j * hop_len + frame_len)
            regions.append((start, end))
            i = j
        else:
            i += 1

    if not regions:
        return []

    merged: List[List[int]] = [[regions[0][0], regions[0][1]]]
    max_gap = int(0.08 * sample_rate)

    for s, e in regions[1:]:
        prev = merged[-1]
        if s - prev[1] <= max_gap:
            prev[1] = e
        else:
            merged.append([s, e])

    min_dur = int(0.09 * sample_rate)
    return [(s, e) for s, e in merged if (e - s) >= min_dur]


def split_into_token_segments(audio: np.ndarray, sample_rate: int, token_count: int) -> List[np.ndarray]:
    regions = _detect_voiced_regions(audio, sample_rate)

    if len(regions) > token_count:
        reg = regions[:]
        while len(reg) > token_count:
            gaps = [reg[i + 1][0] - reg[i][1] for i in range(len(reg) - 1)]
            k = int(np.argmin(gaps))
            merged = (reg[k][0], reg[k + 1][1])
            reg = reg[:k] + [merged] + reg[k + 2 :]
        regions = reg

    if len(regions) == token_count:
        return [audio[s:e] for s, e in regions]

    if regions:
        a0, a1 = regions[0][0], regions[-1][1]
        active = audio[a0:a1]
    else:
        active = audio

    if len(active) < token_count * 60:
        return []

    seg_len = len(active) // token_count
    segments: List[np.ndarray] = []
    for i in range(token_count):
        s = i * seg_len
        e = (i + 1) * seg_len if i < token_count - 1 else len(active)
        seg = active[s:e]
        if len(seg) < 60:
            return []
        segments.append(seg)
    return segments


def load_yesno_segments(root: Path) -> Tuple[List[np.ndarray], List[int], List[str], int]:
    root.mkdir(parents=True, exist_ok=True)
    ds = torchaudio.datasets.YESNO(root=str(root), download=True)

    waveforms: List[np.ndarray] = []
    labels: List[int] = []

    for i in range(len(ds)):
        waveform, _sample_rate, token_labels = ds[i]
        wav = waveform.squeeze(0).numpy().astype(np.float32)

        segments = split_into_token_segments(wav, 8000, len(token_labels))
        if len(segments) != len(token_labels):
            continue

        for seg, tok in zip(segments, token_labels):
            waveforms.append(seg)
            labels.append(int(tok))

    return waveforms, labels, ["no", "yes"], 8000


def read_wav_mono(path: Path) -> Tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sr = wf.getframerate()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        data = wf.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError(f"Unsupported WAV bit depth in {path}. Use 16-bit PCM WAV.")

    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, sr


def prepare_rutus_structure(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(
            "Put dataset files here as:\n"
            "data/rutus/<class_name>/*.wav\n"
            "Example:\n"
            "data/rutus/yes/sample01.wav\n"
            "data/rutus/no/sample02.wav\n",
            encoding="utf-8",
        )


def load_rutus_segments(root: Path) -> Tuple[List[np.ndarray], List[int], List[str], List[int]]:
    prepare_rutus_structure(root)

    class_dirs = sorted([p for p in root.iterdir() if p.is_dir()])
    class_dirs = [d for d in class_dirs if any(d.glob("*.wav"))]
    if not class_dirs:
        return [], [], [], []

    class_names = [d.name for d in class_dirs]
    label_map = {name: i for i, name in enumerate(class_names)}

    waveforms: List[np.ndarray] = []
    labels: List[int] = []
    sample_rates: List[int] = []

    for d in class_dirs:
        for wav_path in sorted(d.glob("*.wav")):
            try:
                audio, sr = read_wav_mono(wav_path)
            except Exception as exc:
                print(f"[WARN] Skipping {wav_path}: {exc}")
                continue

            if len(audio) < 100:
                continue

            waveforms.append(audio)
            labels.append(label_map[d.name])
            sample_rates.append(sr)

    return waveforms, labels, class_names, sample_rates


def stratified_split_indices(labels: Sequence[int], val_ratio: float, test_ratio: float, seed: int):
    if val_ratio <= 0 or test_ratio <= 0 or (val_ratio + test_ratio) >= 1:
        raise ValueError("Use split ratios where val,test > 0 and val+test < 1")

    rng = random.Random(seed)
    unique_classes = sorted(set(int(y) for y in labels))
    per_class: Dict[int, List[int]] = {c: [] for c in unique_classes}

    for i, y in enumerate(labels):
        per_class[int(y)].append(i)

    train_idx, val_idx, test_idx = [], [], []
    for c, idxs in per_class.items():
        if len(idxs) < 10:
            raise ValueError(f"Class {c} has too few samples: {len(idxs)}")

        idxs = idxs.copy()
        rng.shuffle(idxs)

        n = len(idxs)
        n_test = max(1, int(n * test_ratio))
        n_val = max(1, int(n * val_ratio))
        n_train = n - n_val - n_test

        train_idx.extend(idxs[:n_train])
        val_idx.extend(idxs[n_train : n_train + n_val])
        test_idx.extend(idxs[n_train + n_val :])

    rng.shuffle(train_idx)
    rng.shuffle(val_idx)
    rng.shuffle(test_idx)
    return train_idx, val_idx, test_idx


def residual_block(x: tf.Tensor, filters: int, stride: int = 1) -> tf.Tensor:
    shortcut = x

    x = tf.keras.layers.Conv2D(filters, 3, strides=stride, padding="same", use_bias=False)(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.ReLU()(x)

    x = tf.keras.layers.Conv2D(filters, 3, padding="same", use_bias=False)(x)
    x = tf.keras.layers.BatchNormalization()(x)

    if shortcut.shape[-1] != filters or stride != 1:
        shortcut = tf.keras.layers.Conv2D(filters, 1, strides=stride, padding="same", use_bias=False)(shortcut)
        shortcut = tf.keras.layers.BatchNormalization()(shortcut)

    x = tf.keras.layers.Add()([x, shortcut])
    return tf.keras.layers.ReLU()(x)


def build_model(name: str, input_shape: Tuple[int, int, int], num_classes: int) -> tf.keras.Model:
    configs = {
        "small": {"filters": [32, 64], "dense": 128, "dropout": 0.25},
        "medium": {"filters": [32, 64, 128], "dense": 160, "dropout": 0.3},
        "big": {"filters": [48, 96, 192], "dense": 224, "dropout": 0.35},
    }

    c = configs[name]
    inputs = tf.keras.Input(shape=input_shape)

    x = tf.keras.layers.Conv2D(c["filters"][0], 5, padding="same", use_bias=False)(inputs)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.ReLU()(x)

    for f in c["filters"]:
        x = residual_block(x, filters=f, stride=1)
        x = tf.keras.layers.MaxPool2D(2)(x)

    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dropout(c["dropout"])(x)
    x = tf.keras.layers.Dense(c["dense"], activation="relu")(x)
    x = tf.keras.layers.Dropout(c["dropout"])(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)

    model = tf.keras.Model(inputs=inputs, outputs=outputs, name=f"audiocls_{name}")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=3e-4),
        loss=tf.keras.losses.CategoricalCrossentropy(label_smoothing=0.05),
        metrics=["accuracy"],
    )
    return model


def export_tflite(model: tf.keras.Model, path: Path) -> None:
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]
    path.write_bytes(converter.convert())


def plot_comparison_pdf(histories: Dict[str, dict], reports_dir: Path, dataset_name: str) -> Path:
    pdf_path = reports_dir / "training_comparison.pdf"

    with PdfPages(pdf_path) as pdf:
        fig = plt.figure(figsize=(10, 14))

        ax1 = plt.subplot(3, 1, 1)
        for name, hist in histories.items():
            ax1.plot(hist["val_loss"], label=name)
        ax1.set_title(f"{dataset_name} - Validation Loss")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("Val Loss")
        ax1.grid(alpha=0.3)
        ax1.legend()

        ax2 = plt.subplot(3, 1, 2)
        for name, hist in histories.items():
            ax2.plot(hist["loss"], label=name)
        ax2.set_title(f"{dataset_name} - Training Loss")
        ax2.set_xlabel("Epoch")
        ax2.set_ylabel("Train Loss")
        ax2.grid(alpha=0.3)
        ax2.legend()

        ax3 = plt.subplot(3, 1, 3)
        for name, hist in histories.items():
            ax3.plot(hist["val_accuracy"], label=name)
        ax3.set_title(f"{dataset_name} - Validation Accuracy")
        ax3.set_xlabel("Epoch")
        ax3.set_ylabel("Val Accuracy")
        ax3.grid(alpha=0.3)
        ax3.legend()

        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

    return pdf_path


def clean_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def as_dataset(x: np.ndarray, y: np.ndarray, batch_size: int, training: bool) -> tf.data.Dataset:
    ds = tf.data.Dataset.from_tensor_slices((x, y))
    if training:
        ds = ds.shuffle(buffer_size=len(x), reshuffle_each_iteration=True)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def pick_dataset() -> str:
    print("\nSelect dataset:")
    print("  1) YESNO")
    print("  2) RUTUS")
    try:
        choice = input("Choice [1/2] (default 1): ").strip().lower()
    except EOFError:
        choice = ""
    return "RUTUS" if choice in {"2", "rutus"} else "YESNO"


def load_dataset(dataset_name: str) -> Tuple[List[np.ndarray], List[int], List[str], List[int], Path]:
    if dataset_name == "YESNO":
        waves, labels, class_names, sr = load_yesno_segments(YESNO_ROOT)
        return waves, labels, class_names, [sr] * len(waves), OUTPUT_ROOT / "yesno"

    waves, labels, class_names, sample_rates = load_rutus_segments(RUTUS_ROOT)
    return waves, labels, class_names, sample_rates, OUTPUT_ROOT / "rutus"


def main() -> None:
    set_seed(SEED)

    dataset_name = pick_dataset()
    print(f"\nDataset selected: {dataset_name}")

    print("[1/6] Loading dataset...")
    waveforms, labels, class_names, sample_rates, out_root = load_dataset(dataset_name)

    if not waveforms:
        if dataset_name == "RUTUS":
            print("RUTUS is currently empty.")
            print("Add WAV files under: data/rutus/<class_name>/*.wav")
            return
        raise RuntimeError("No audio samples found.")

    models_dir = out_root / "models"
    reports_dir = out_root / "reports"
    clean_output_dir(out_root)
    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    print(f"Samples: {len(waveforms)} | Classes: {class_names}")
    class_counts = {name: int(sum(1 for y in labels if y == i)) for i, name in enumerate(class_names)}
    print(f"Class distribution: {class_counts}")

    target_samples = int(TARGET_SR * CLIP_SECONDS)
    mel_fb = build_mel_filterbank(sample_rate=TARGET_SR, n_fft=N_FFT, n_mels=N_MELS, f_min=20.0, f_max=8000.0)

    print("[2/6] Extracting log-mel features...")
    x = np.stack(
        [
            extract_log_mel(
                audio=waveforms[i],
                sample_rate=sample_rates[i],
                target_samples=target_samples,
                n_fft=N_FFT,
                hop_length=HOP,
                win_length=WIN,
                mel_filterbank=mel_fb,
            )
            for i in range(len(waveforms))
        ],
        axis=0,
    )
    x = x[..., np.newaxis].astype(np.float32)

    y_idx = np.array(labels, dtype=np.int32)
    y = tf.keras.utils.to_categorical(y_idx, num_classes=len(class_names)).astype(np.float32)
    print(f"Feature tensor shape: {x.shape}")

    print("[3/6] Creating stratified train/val/test split...")
    train_idx, val_idx, test_idx = stratified_split_indices(y_idx.tolist(), VAL_RATIO, TEST_RATIO, SEED)

    x_train, y_train = x[train_idx], y[train_idx]
    x_val, y_val = x[val_idx], y[val_idx]
    x_test, y_test = x[test_idx], y[test_idx]

    print(f"Split sizes: train={len(x_train)} val={len(x_val)} test={len(x_test)}")

    train_ds = as_dataset(x_train, y_train, BATCH_SIZE, training=True)
    val_ds = as_dataset(x_val, y_val, BATCH_SIZE, training=False)
    test_ds = as_dataset(x_test, y_test, BATCH_SIZE, training=False)

    (models_dir / "labels.txt").write_text("\n".join(class_names) + "\n", encoding="utf-8")

    histories: Dict[str, dict] = {}
    metrics: Dict[str, dict] = {}

    print("[4/6] Training models...")
    dataset_prefix = dataset_name.lower()

    for model_name in MODEL_VARIANTS:
        print(f"\n=== {model_name.upper()} ===")
        model = build_model(model_name, input_shape=x.shape[1:], num_classes=len(class_names))

        ckpt_path = models_dir / f"{dataset_prefix}net_{model_name}.best.weights.h5"
        checkpoint_cb = tf.keras.callbacks.ModelCheckpoint(
            filepath=str(ckpt_path),
            monitor="val_accuracy",
            mode="max",
            save_best_only=True,
            save_weights_only=True,
            verbose=0,
        )

        hist = model.fit(
            train_ds,
            validation_data=val_ds,
            epochs=EPOCHS,
            verbose=2,
            callbacks=[checkpoint_cb],
        )

        if ckpt_path.exists():
            model.load_weights(str(ckpt_path))
            ckpt_path.unlink(missing_ok=True)

        test_loss, test_acc = model.evaluate(test_ds, verbose=0)
        print(f"Test results -> loss: {test_loss:.4f} | accuracy: {test_acc:.4f}")

        base_name = f"{dataset_prefix}net_{model_name}"
        keras_path = models_dir / f"{base_name}.keras"
        tflite_path = models_dir / f"{base_name}.tflite"
        hist_path = models_dir / f"{base_name}_history.json"

        model.save(keras_path)
        export_tflite(model, tflite_path)
        history_dict = hist.history
        hist_path.write_text(json.dumps(history_dict, indent=2), encoding="utf-8")

        histories[model_name] = history_dict
        metrics[model_name] = {
            "best_val_accuracy": float(max(history_dict.get("val_accuracy", [0.0]))),
            "test_loss": float(test_loss),
            "test_accuracy": float(test_acc),
            "keras_model": str(keras_path),
            "tflite_model": str(tflite_path),
        }

    print("[5/6] Generating comparison PDF...")
    pdf_path = plot_comparison_pdf(histories, reports_dir, dataset_name)

    summary_path = out_root / "summary_metrics.json"
    summary_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("[6/6] Done.")
    print(f"Models: {models_dir}")
    print(f"Reports: {reports_dir}")
    print(f"Comparison PDF: {pdf_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
