# Neural Detecting v0.5

YES/NO recognition with stronger speech models and live PC interface.

## Main Scripts

- `train_audio_compare.py`: your local training pipeline (YESNO/RUTUS, 3 models)
- `asr_yesno_benchmark.py`: benchmark 3 pretrained ASR models on YESNO
- `yesno_live_inference.py`: always-listening live UI on PC (real-time yes/no percentages)
- `metal_model.py`: shared TFLite utilities (legacy path support)

## Powerful ASR Models Used

- `wav2vec2_base_960h`
- `wav2vec2_large_960h`
- `hubert_asr_large`

These are pretrained speech models and generally generalize much better across voices than a small classifier trained from scratch on YESNO.

## 1) Benchmark Pretrained ASR Models

```bash
cd '/Users/ivan/Desktop/Neural-Detecting'
python3 asr_yesno_benchmark.py
```

Output:
- `artifacts/asr_yesno_benchmark.json`

Note: first run downloads large model weights; subsequent runs use cache.

## 2) Live Inference (Always Listening) on PC

```bash
cd '/Users/ivan/Desktop/Neural-Detecting'
python3 yesno_live_inference.py
```

Behavior:
- starts listening continuously
- choose model from dropdown
- speaks YES/NO and percentages update in real time
- pause/resume microphone if needed

## 3) Local Training Pipeline (Optional)

```bash
cd '/Users/ivan/Desktop/Neural-Detecting'
python3 train_audio_compare.py
```

This keeps your custom training flow if you want to compare against ASR-based inference.

## License

MIT (see `LICENSE`).
