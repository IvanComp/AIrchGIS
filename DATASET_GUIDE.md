# Manual Dataset Build Guide (Metal Detector Audio)

## 1) Define your classes and metadata first
Use a fixed class list, for example:
- `gold`
- `silver`
- `copper`
- `iron`
- `aluminum`
- `background_noise`

Create a metadata CSV with these columns:
- `file_name`
- `label`
- `device_model` (iPhone model)
- `detector_model`
- `distance_cm` (coil-to-target distance)
- `orientation` (flat/edge/angled)
- `environment` (indoor, soil, beach, concrete, etc.)
- `noise_level` (low/medium/high)
- `sample_rate`
- `notes`

## 2) Recording protocol (critical for accuracy)
- Record in WAV, 16 kHz or 44.1 kHz, mono if possible.
- Use fixed clip length for training (1-2 seconds windows).
- Keep iPhone mic gain/exposure consistent when possible.
- Capture at least 3-5 sessions per class on different days.
- Vary conditions intentionally: quiet/noisy, different surfaces, slight angle and distance changes.

Target minimum per class for a first usable model:
- 20-30 minutes of raw audio per class.

## 3) Folder layout
Use a deterministic structure:

```text
dataset/
  raw/
    2026-02-13_session1/
  clips/
    gold/
    silver/
    copper/
    iron/
    aluminum/
    background_noise/
  metadata/
    labels.csv
```

## 4) Manual clipping + labeling
1. Import raw recordings into annotation software.
2. Mark each detector event (beep/response) and export as 1-2 second clips.
3. Name files with a stable pattern:
   - `gold_s3_take014.wav`
4. Write one row per clip in `labels.csv`.
5. Add a second pass QA check to relabel uncertain clips.

## 5) Free/open-source tools to speed annotation
- **Audacity** (free, open-source): quick waveform review, trimming, batch export.
- **Sonic Visualiser** (free, open-source): useful spectrogram inspection.
- **Label Studio** (open-source): flexible metadata labeling workflows.
- **CVAT** (open-source): can be adapted for audio segment tasks.
- **Python + Jupyter** (open-source): fast custom clip validation scripts.

Practical fast setup:
- Use Audacity for segmentation + export.
- Use Label Studio for structured metadata entry and QA.

## 6) Data balancing and split strategy
- Keep class counts roughly balanced.
- Split by session/day (not random clip-only split) to avoid leakage.
- Suggested split:
  - `train`: 70%
  - `val`: 15%
  - `test`: 15%

## 7) Prepare mobile-ready model variants
Train/export at multiple complexities:
- `metalnet_tiny.tflite`
- `metalnet_small.tflite`
- `metalnet_medium.tflite`
- `metalnet_large.tflite`

Then benchmark:
- accuracy/F1 on test set
- on-device latency (ms/inference)
- battery impact

## 8) iPhone deployment optimization checklist
- Prefer **TensorFlow Lite** with float16 or int8 quantization.
- Keep input length short (1 second windows) for low latency.
- Run inference every 300-500 ms (not every audio frame).
- Use a ring buffer for audio and a separate worker thread for inference.
- Ship labels in a plain `labels.txt` file.

## 9) Quality control rules before retraining
- Remove clips with clipping/distortion.
- Remove ambiguous labels.
- Keep at least 10% hard/noisy examples in each class.
- Re-train after each +10-20% dataset size increase and track confusion matrix changes.
