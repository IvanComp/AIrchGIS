#!/usr/bin/env python3
"""Benchmark 3 pretrained ASR models on YESNO token recognition.

No CLI arguments.
Outputs JSON report in artifacts/asr_yesno_benchmark.json
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torchaudio


DATA_ROOT = Path("data/yesno")
OUT_PATH = Path("artifacts/asr_yesno_benchmark.json")
MAX_UTTERANCES = 60  # increase to 120/240 for deeper benchmark
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

BUNDLES = {
    "wav2vec2_base_960h": torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H,
    "wav2vec2_large_960h": torchaudio.pipelines.WAV2VEC2_ASR_LARGE_960H,
    "hubert_asr_large": torchaudio.pipelines.HUBERT_ASR_LARGE,
}


@dataclass
class ASRModel:
    model: torch.nn.Module
    labels: List[str]
    sample_rate: int


def collapse_ctc(indices: List[int], labels: List[str]) -> str:
    out: List[str] = []
    prev = -1
    blank = 0
    for idx in indices:
        if idx == prev:
            continue
        prev = idx
        if idx == blank:
            continue
        token = labels[idx]
        out.append(" " if token == "|" else token)
    return "".join(out).strip().lower()


def word_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    # lightweight normalized overlap heuristic
    a2 = a.strip().lower()
    b2 = b.strip().lower()
    if a2 == b2:
        return 1.0
    common = sum(1 for ch in set(a2) if ch in set(b2))
    return common / max(len(set(a2 + b2)), 1)


def yes_no_scores(text: str) -> Tuple[float, float]:
    words = [w for w in text.replace("-", " ").split() if w]
    if not words:
        return 0.5, 0.5

    s_yes = max(word_similarity(w, "yes") for w in words)
    s_no = max(word_similarity(w, "no") for w in words)

    if "yes" in words:
        s_yes = max(s_yes, 0.98)
    if "no" in words:
        s_no = max(s_no, 0.98)

    total = s_yes + s_no + 1e-8
    return s_yes / total, s_no / total


def voiced_regions(audio: np.ndarray, sr: int) -> List[Tuple[int, int]]:
    frame = max(64, int(0.025 * sr))
    hop = max(32, int(0.010 * sr))
    if len(audio) < frame:
        audio = np.pad(audio, (0, frame - len(audio)))

    n = 1 + max(0, (len(audio) - frame) // hop)
    stride = audio.strides[0]
    frames = np.lib.stride_tricks.as_strided(
        audio,
        shape=(n, frame),
        strides=(hop * stride, stride),
        writeable=False,
    )
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-10)
    smooth = np.convolve(rms, np.ones(5, dtype=np.float32) / 5.0, mode="same")

    med = float(np.median(smooth))
    p90 = float(np.percentile(smooth, 90))
    mx = float(np.max(smooth))
    thr = max(med + 0.35 * (p90 - med), 0.12 * mx)

    act = smooth > thr
    regs: List[Tuple[int, int]] = []
    i = 0
    while i < len(act):
        if not act[i]:
            i += 1
            continue
        j = i + 1
        while j < len(act) and act[j]:
            j += 1
        regs.append((i * hop, min(len(audio), j * hop + frame)))
        i = j

    if not regs:
        return []

    merged: List[List[int]] = [[regs[0][0], regs[0][1]]]
    for s, e in regs[1:]:
        if s - merged[-1][1] <= int(0.08 * sr):
            merged[-1][1] = e
        else:
            merged.append([s, e])

    return [(s, e) for s, e in merged if e - s >= int(0.08 * sr)]


def split_tokens(wav: np.ndarray, sr: int, n_tokens: int) -> List[np.ndarray]:
    regs = voiced_regions(wav, sr)

    if len(regs) > n_tokens:
        r = regs[:]
        while len(r) > n_tokens:
            gaps = [r[i + 1][0] - r[i][1] for i in range(len(r) - 1)]
            k = int(np.argmin(gaps))
            r = r[:k] + [(r[k][0], r[k + 1][1])] + r[k + 2 :]
        regs = r

    if len(regs) == n_tokens:
        return [wav[s:e] for s, e in regs]

    span = wav[regs[0][0] : regs[-1][1]] if regs else wav
    if len(span) < n_tokens * 60:
        return []

    seg_len = len(span) // n_tokens
    out = []
    for i in range(n_tokens):
        s = i * seg_len
        e = (i + 1) * seg_len if i < n_tokens - 1 else len(span)
        out.append(span[s:e])
    return out


def load_model(bundle) -> ASRModel:
    m = bundle.get_model().to(DEVICE).eval()
    labels = list(bundle.get_labels())
    return ASRModel(model=m, labels=labels, sample_rate=bundle.sample_rate)


def transcribe_segment(asr: ASRModel, audio: np.ndarray, sr: int) -> str:
    audio = audio.astype(np.float32)
    if sr != asr.sample_rate:
        src = np.arange(len(audio), dtype=np.float32)
        dst_len = int(len(audio) * (asr.sample_rate / sr))
        dst = np.linspace(0, len(audio) - 1, num=max(dst_len, 1), dtype=np.float32)
        audio = np.interp(dst, src, audio).astype(np.float32)

    if len(audio) < int(0.25 * asr.sample_rate):
        pad = int(0.25 * asr.sample_rate) - len(audio)
        audio = np.pad(audio, (0, pad))

    x = torch.from_numpy(audio).unsqueeze(0).to(DEVICE)
    with torch.inference_mode():
        em, _ = asr.model(x)
        pred = torch.argmax(em, dim=-1)[0].cpu().tolist()
    return collapse_ctc(pred, asr.labels)


def benchmark_bundle(name: str, bundle) -> Dict[str, float]:
    asr = load_model(bundle)
    ds = torchaudio.datasets.YESNO(root=str(DATA_ROOT), download=True)

    token_total = 0
    token_ok = 0
    utt_total = 0
    utt_ok = 0

    start = time.perf_counter()
    for i in range(min(len(ds), MAX_UTTERANCES)):
        wav_t, sr, labels = ds[i]
        wav = wav_t.squeeze(0).numpy()
        segs = split_tokens(wav, sr, len(labels))
        if len(segs) != len(labels):
            continue

        utt_pred: List[int] = []
        for seg, y in zip(segs, labels):
            txt = transcribe_segment(asr, seg, sr)
            py, pn = yes_no_scores(txt)
            pred = 1 if py >= pn else 0
            utt_pred.append(pred)
            token_total += 1
            token_ok += int(pred == int(y))

        utt_total += 1
        utt_ok += int(utt_pred == list(labels))

    elapsed = time.perf_counter() - start
    return {
        "token_accuracy": token_ok / max(token_total, 1),
        "utterance_exact_match": utt_ok / max(utt_total, 1),
        "tokens_evaluated": token_total,
        "utterances_evaluated": utt_total,
        "elapsed_sec": elapsed,
    }


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    report: Dict[str, object] = {
        "device": DEVICE,
        "max_utterances": MAX_UTTERANCES,
        "results": {},
    }

    for name, bundle in BUNDLES.items():
        print(f"\n=== Benchmark {name} ===")
        metrics = benchmark_bundle(name, bundle)
        report["results"][name] = metrics
        print(json.dumps(metrics, indent=2))

    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved report: {OUT_PATH}")


if __name__ == "__main__":
    main()
