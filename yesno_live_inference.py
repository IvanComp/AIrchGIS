#!/usr/bin/env python3
"""Reliable YES/NO live inference (utterance-based) with pretrained ASR.

Design:
- Always listening microphone
- VAD endpointing (start/end speech detection)
- Decode complete utterance (not rolling window) for stable yes/no prediction
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import sounddevice as sd
import torch
import torchaudio


MODEL_BUNDLES = {
    "wav2vec2_base_960h": torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H,
    "wav2vec2_large_960h": torchaudio.pipelines.WAV2VEC2_ASR_LARGE_960H,
    "hubert_asr_large": torchaudio.pipelines.HUBERT_ASR_LARGE,
}
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class LoadedASR:
    model: torch.nn.Module
    labels: list[str]
    sample_rate: int


def collapse_ctc(indices: list[int], labels: list[str]) -> str:
    out: list[str] = []
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


def levenshtein_norm(a: str, b: str) -> float:
    a = a.strip().lower()
    b = b.strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    m, n = len(a), len(b)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            cur = dp[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + cost)
            prev = cur

    dist = dp[n]
    return 1.0 - (dist / max(m, n))


def yes_no_scores(text: str) -> tuple[float, float]:
    words = [w for w in text.replace("-", " ").split() if w]
    if not words:
        return 0.5, 0.5

    yes_aliases = ["yes", "yeah", "yep", "yea", "yas", "es"]
    no_aliases = ["no", "nope", "nah", "know", "naw"]

    s_yes = max(max(levenshtein_norm(w, y) for y in yes_aliases) for w in words)
    s_no = max(max(levenshtein_norm(w, n) for n in no_aliases) for w in words)

    txt = " ".join(words)
    if "yes" in txt or "yeah" in txt or "yep" in txt:
        s_yes = max(s_yes, 0.995)
    if "no" in txt or "nope" in txt:
        s_no = max(s_no, 0.995)

    if max(s_yes, s_no) < 0.45:
        return 0.5, 0.5

    gap = abs(s_yes - s_no)
    if gap < 0.07:
        return 0.5, 0.5

    tot = s_yes + s_no + 1e-8
    return s_yes / tot, s_no / tot


def load_asr_model(bundle_name: str) -> LoadedASR:
    bundle = MODEL_BUNDLES[bundle_name]
    model = bundle.get_model().to(DEVICE).eval()
    labels = list(bundle.get_labels())
    return LoadedASR(model=model, labels=labels, sample_rate=bundle.sample_rate)


class RealtimeASR:
    def __init__(self, asr: LoadedASR):
        self.asr = asr
        self.sample_rate = asr.sample_rate

        self.running = False
        self.stream = None
        self.decode_worker = None

        self.events: "queue.Queue[dict]" = queue.Queue(maxsize=40)
        self.utterances: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=12)

        # VAD state
        self.silence_threshold = 0.0040
        self.start_frames = 2
        self.end_silence_frames = 7
        self.max_utt_sec = 1.6
        self.preroll_sec = 0.2

        self.blocksize = 800
        self.last_rms = 0.0

        self._in_speech = False
        self._voice_count = 0
        self._silence_count = 0
        self._current: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._preroll_limit_blocks = max(1, int((self.preroll_sec * self.sample_rate) / self.blocksize))

    def _emit_event(self, item: dict):
        if self.events.full():
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
        self.events.put(item)

    def _push_utterance(self, arr: np.ndarray):
        if self.utterances.full():
            try:
                self.utterances.get_nowait()
            except queue.Empty:
                pass
        self.utterances.put(arr)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            return

        mono = indata[:, 0].astype(np.float32)
        rms = float(np.sqrt(np.mean(mono * mono) + 1e-10))
        self.last_rms = rms

        voiced = rms >= self.silence_threshold

        # maintain preroll buffer always
        self._preroll.append(mono.copy())
        if len(self._preroll) > self._preroll_limit_blocks:
            self._preroll.pop(0)

        if not self._in_speech:
            if voiced:
                self._voice_count += 1
                if self._voice_count >= self.start_frames:
                    self._in_speech = True
                    self._silence_count = 0
                    self._current = self._preroll.copy()
                    self._emit_event({"event": "speech_start"})
            else:
                self._voice_count = 0
            return

        # in speech
        self._current.append(mono.copy())
        if voiced:
            self._silence_count = 0
        else:
            self._silence_count += 1

        cur_samples = len(self._current) * self.blocksize
        max_samples = int(self.max_utt_sec * self.sample_rate)

        if self._silence_count >= self.end_silence_frames or cur_samples >= max_samples:
            utt = np.concatenate(self._current, axis=0)
            self._push_utterance(utt)
            self._emit_event({"event": "speech_end", "rms": rms})

            self._in_speech = False
            self._voice_count = 0
            self._silence_count = 0
            self._current = []

    def _decode_utterances(self):
        min_len = int(0.18 * self.sample_rate)
        max_len = int(2.0 * self.sample_rate)

        while self.running:
            try:
                utt = self.utterances.get(timeout=0.2)
            except queue.Empty:
                continue

            if len(utt) < min_len:
                self._emit_event({"event": "result", "silence": True})
                continue

            if len(utt) > max_len:
                utt = utt[:max_len]

            # normalize
            utt = utt.astype(np.float32)
            utt = utt / (np.max(np.abs(utt)) + 1e-8)

            x = torch.from_numpy(utt).unsqueeze(0).to(DEVICE)
            with torch.inference_mode():
                emissions, _ = self.asr.model(x)
                pred = torch.argmax(emissions, dim=-1)[0].cpu().tolist()

            txt = collapse_ctc(pred, self.asr.labels)
            py, pn = yes_no_scores(txt)
            self._emit_event(
                {
                    "event": "result",
                    "silence": False,
                    "transcript": txt,
                    "yes": py * 100.0,
                    "no": pn * 100.0,
                    "pred": "yes" if py >= pn else "no",
                }
            )

    def start(self):
        if self.running:
            return

        self.running = True
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            callback=self._audio_callback,
        )
        self.stream.start()

        self.decode_worker = threading.Thread(target=self._decode_utterances, daemon=True)
        self.decode_worker.start()

    def stop(self):
        self.running = False

        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if self.decode_worker is not None:
            self.decode_worker.join(timeout=1.0)
            self.decode_worker = None


class LiveApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("YES/NO Live ASR (Reliable)")
        self.root.geometry("780x540")
        self.root.minsize(720, 500)

        self.runner: RealtimeASR | None = None
        self.loaded: dict[str, LoadedASR] = {}

        container = ttk.Frame(root, padding=16)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="YES/NO Live ASR", font=("Helvetica", 20, "bold")).pack(anchor="w")
        ttk.Label(
            container,
            text="Mode: utterance-based. Ogni nuovo audio viene valutato in modo indipendente.",
            font=("Helvetica", 10),
        ).pack(anchor="w", pady=(2, 12))

        top = ttk.Frame(container)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="ASR model:").pack(side="left")

        self.model_var = tk.StringVar(value="wav2vec2_base_960h")
        self.model_box = ttk.Combobox(top, textvariable=self.model_var, values=list(MODEL_BUNDLES.keys()), state="readonly", width=28)
        self.model_box.pack(side="left", padx=(8, 12))
        self.model_box.bind("<<ComboboxSelected>>", self._on_model_change)

        ttk.Button(top, text="Pause", command=self.pause).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Resume", command=self.resume).pack(side="left")

        self.status_var = tk.StringVar(value="Loading model...")
        ttk.Label(container, textvariable=self.status_var, font=("Helvetica", 11)).pack(anchor="w", pady=(4, 10))

        self.pred_var = tk.StringVar(value="Prediction: -")
        ttk.Label(container, textvariable=self.pred_var, font=("Helvetica", 24, "bold")).pack(anchor="w", pady=(8, 10))

        row_yes = ttk.Frame(container)
        row_yes.pack(fill="x", pady=(4, 4))
        ttk.Label(row_yes, text="YES", width=8, font=("Helvetica", 12, "bold")).pack(side="left")
        self.yes_bar = ttk.Progressbar(row_yes, maximum=100, length=520)
        self.yes_bar.pack(side="left", padx=(8, 10), fill="x", expand=True)
        self.yes_var = tk.StringVar(value="50.0%")
        ttk.Label(row_yes, textvariable=self.yes_var, width=8).pack(side="left")

        row_no = ttk.Frame(container)
        row_no.pack(fill="x", pady=(4, 8))
        ttk.Label(row_no, text="NO", width=8, font=("Helvetica", 12, "bold")).pack(side="left")
        self.no_bar = ttk.Progressbar(row_no, maximum=100, length=520)
        self.no_bar.pack(side="left", padx=(8, 10), fill="x", expand=True)
        self.no_var = tk.StringVar(value="50.0%")
        ttk.Label(row_no, textvariable=self.no_var, width=8).pack(side="left")

        self.txt_var = tk.StringVar(value="Transcript: -")
        ttk.Label(container, textvariable=self.txt_var, font=("Helvetica", 11)).pack(anchor="w", pady=(8, 0))

        self.mic_var = tk.StringVar(value="Mic RMS: 0.0000")
        ttk.Label(container, textvariable=self.mic_var, font=("Helvetica", 10)).pack(anchor="w", pady=(4, 0))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._start_with_model(self.model_var.get())
        self._poll()

    def _set_neutral(self):
        self.pred_var.set("Prediction: -")
        self.yes_bar["value"] = 50.0
        self.no_bar["value"] = 50.0
        self.yes_var.set("50.0%")
        self.no_var.set("50.0%")

    def _get_or_load(self, key: str) -> LoadedASR:
        if key not in self.loaded:
            self.status_var.set(f"Loading {key} on {DEVICE}...")
            self.root.update_idletasks()
            self.loaded[key] = load_asr_model(key)
        return self.loaded[key]

    def _start_with_model(self, key: str):
        try:
            if self.runner is not None:
                self.runner.stop()

            asr = self._get_or_load(key)
            self.runner = RealtimeASR(asr)
            self.runner.start()
            self._set_neutral()
            self.status_var.set(f"Listening continuously | model={key} | device={DEVICE}")
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            messagebox.showerror("ASR error", str(exc))

    def _on_model_change(self, _event=None):
        self._start_with_model(self.model_var.get().strip())

    def pause(self):
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
        self.status_var.set("Paused")

    def resume(self):
        self._start_with_model(self.model_var.get().strip())

    def _poll(self):
        if self.runner is not None:
            self.mic_var.set(f"Mic RMS: {self.runner.last_rms:.4f}")

            latest = None
            while not self.runner.events.empty():
                latest = self.runner.events.get_nowait()

            if latest is not None:
                ev = latest.get("event")
                if ev == "speech_start":
                    # reset only when new audio starts
                    self._set_neutral()
                    self.txt_var.set("Transcript: (capturing...)")
                elif ev == "result":
                    if latest.get("silence"):
                        self.txt_var.set("Transcript: (too short)")
                    else:
                        yes = float(latest["yes"])
                        no = float(latest["no"])
                        self.pred_var.set(f"Prediction: {latest['pred'].upper()}")
                        self.yes_var.set(f"{yes:.1f}%")
                        self.no_var.set(f"{no:.1f}%")
                        self.yes_bar["value"] = yes
                        self.no_bar["value"] = no
                        self.txt_var.set(f"Transcript: {latest['transcript']}")

        self.root.after(50, self._poll)

    def on_close(self):
        if self.runner is not None:
            self.runner.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    ttk.Style(root).theme_use("clam")
    LiveApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
