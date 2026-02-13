#!/usr/bin/env python3
"""YES/NO web app with PC-like utterance logic (VAD endpointing + ASR decode)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gradio as gr
import numpy as np
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


LOADED: dict[str, LoadedASR] = {}


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
        tok = labels[idx]
        out.append(" " if tok == "|" else tok)
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

    if abs(s_yes - s_no) < 0.07:
        return 0.5, 0.5

    tot = s_yes + s_no + 1e-8
    return s_yes / tot, s_no / tot


def get_or_load(model_name: str) -> LoadedASR:
    if model_name in LOADED:
        return LOADED[model_name]
    bundle = MODEL_BUNDLES[model_name]
    model = bundle.get_model().to(DEVICE).eval()
    obj = LoadedASR(model=model, labels=list(bundle.get_labels()), sample_rate=bundle.sample_rate)
    LOADED[model_name] = obj
    return obj


def resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    src_idx = np.arange(len(audio), dtype=np.float32)
    dst_len = int(len(audio) * (dst_sr / src_sr))
    dst_idx = np.linspace(0, len(audio) - 1, num=max(dst_len, 1), dtype=np.float32)
    return np.interp(dst_idx, src_idx, audio).astype(np.float32)


def decode_utterance(audio: np.ndarray, sr: int, model_name: str) -> tuple[str, float, float]:
    asr = get_or_load(model_name)
    audio = resample_linear(audio, sr, asr.sample_rate)
    audio = audio.astype(np.float32)

    if len(audio) < int(0.16 * asr.sample_rate):
        return "", 50.0, 50.0

    max_len = int(2.0 * asr.sample_rate)
    if len(audio) > max_len:
        audio = audio[:max_len]

    audio = audio / (np.max(np.abs(audio)) + 1e-8)

    x = torch.from_numpy(audio).unsqueeze(0).to(DEVICE)
    with torch.inference_mode():
        emissions, _ = asr.model(x)
        pred = torch.argmax(emissions, dim=-1)[0].cpu().tolist()

    txt = collapse_ctc(pred, asr.labels)
    py, pn = yes_no_scores(txt)
    return txt, py * 100.0, pn * 100.0


def init_state() -> dict[str, Any]:
    return {
        "sr": None,
        "silence_threshold": 0.0040,
        "start_frames": 2,
        "end_silence_frames": 7,
        "max_utt_sec": 1.8,
        "in_speech": False,
        "voice_count": 0,
        "sil_count": 0,
        "chunks": [],
        "last_pred": "-",
        "last_yes": 50.0,
        "last_no": 50.0,
        "last_txt": "",
        "last_status": "Waiting for audio...",
    }


def process_stream(audio_chunk, model_name: str, state: dict[str, Any]):
    if state is None:
        state = init_state()

    if audio_chunk is None:
        return state["last_pred"], {"yes": state["last_yes"] / 100.0, "no": state["last_no"] / 100.0}, state["last_txt"], state["last_status"], state

    sr, audio = audio_chunk
    if audio is None:
        return state["last_pred"], {"yes": state["last_yes"] / 100.0, "no": state["last_no"] / 100.0}, state["last_txt"], state["last_status"], state

    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    if state["sr"] is None:
        state["sr"] = sr
    state_sr = state["sr"]

    if sr != state_sr:
        audio = resample_linear(audio, sr, state_sr)

    rms = float(np.sqrt(np.mean(audio * audio) + 1e-10))
    voiced = rms >= state["silence_threshold"]

    block_samples = len(audio)
    max_samples = int(state["max_utt_sec"] * state_sr)

    if not state["in_speech"]:
        if voiced:
            state["voice_count"] += 1
            if state["voice_count"] >= state["start_frames"]:
                state["in_speech"] = True
                state["sil_count"] = 0
                state["chunks"] = [audio]
                # Reset only when new utterance starts.
                state["last_pred"] = "-"
                state["last_yes"] = 50.0
                state["last_no"] = 50.0
                state["last_txt"] = ""
                state["last_status"] = "Capturing utterance..."
        else:
            state["voice_count"] = 0
            state["last_status"] = "Waiting for speech..."
    else:
        state["chunks"].append(audio)
        if voiced:
            state["sil_count"] = 0
        else:
            state["sil_count"] += 1

        cur_samples = len(state["chunks"]) * block_samples
        ended = state["sil_count"] >= state["end_silence_frames"] or cur_samples >= max_samples

        if ended:
            utt = np.concatenate(state["chunks"], axis=0)
            txt, yes, no = decode_utterance(utt, state_sr, model_name)
            pred = "YES" if yes >= no else "NO"

            state["last_pred"] = pred
            state["last_yes"] = yes
            state["last_no"] = no
            state["last_txt"] = txt
            state["last_status"] = "Utterance decoded. Waiting for next audio..."

            state["in_speech"] = False
            state["voice_count"] = 0
            state["sil_count"] = 0
            state["chunks"] = []

    probs = {"yes": state["last_yes"] / 100.0, "no": state["last_no"] / 100.0}
    pred_text = f"Prediction: {state['last_pred']} | yes={state['last_yes']:.1f}% no={state['last_no']:.1f}%"
    transcript = state["last_txt"]
    status = f"{state['last_status']} (rms={rms:.4f})"

    return pred_text, probs, transcript, status, state


def on_stream_stop(state: dict[str, Any]):
    # Keep last result visible; don't wipe after stop.
    if state is None:
        state = init_state()
    status = "Stream stopped. Last result retained."
    return status, state


def build_app() -> gr.Blocks:
    with gr.Blocks(title="YES/NO Web Inference") as demo:
        gr.Markdown(
            "## YES/NO Web Inference (PC logic)\n"
            "Apri in Safari/Chrome esterno (non in-app browser).\n"
            "Premi Record: la logica è come desktop (start speech -> capture -> end speech -> decode)."
        )

        model = gr.Dropdown(list(MODEL_BUNDLES.keys()), value="wav2vec2_base_960h", label="Model")
        audio = gr.Audio(sources=["microphone"], type="numpy", streaming=True, label="Live microphone stream")

        pred = gr.Textbox(label="Result")
        probs = gr.Label(label="Probabilities")
        transcript = gr.Textbox(label="Transcript")
        status = gr.Textbox(label="Status")

        st = gr.State(init_state())

        audio.stream(
            fn=process_stream,
            inputs=[audio, model, st],
            outputs=[pred, probs, transcript, status, st],
        )
        audio.stop_recording(
            fn=on_stream_stop,
            inputs=[st],
            outputs=[status, st],
        )

    return demo


def main() -> None:
    app = build_app()
    app.launch(server_name="127.0.0.1", server_port=7860, inbrowser=False, show_error=True, share=True)


if __name__ == "__main__":
    main()
