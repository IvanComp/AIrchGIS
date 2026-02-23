# Neural Detecting v0.5

## MASE

<https://sim.mase.gov.it/portalediaccesso/mappe/#/viewer/new>

## iPhone / Chrome mobile (modo semplice)

Avvio standard con link HTTPS Gradio:

```bash
cd '/Users/ivan/Desktop/Neural-Detecting'
pip install gradio torch torchaudio numpy
python3 yesno_live_web.py
```

Apri SOLO il link `https://...gradio.live` stampato nel terminale.
Non usare `https://IP:7860` (quello genera `Invalid HTTP request`).

## Se il link gradio.live non funziona

Usa tunnel HTTPS alternativo (`localhost.run`):

Terminale A:

```bash
cd '/Users/ivan/Desktop/Neural-Detecting'
YESNO_SHARE=0 python3 yesno_live_web.py
```

Terminale B:

```bash
ssh -o StrictHostKeyChecking=no -R 80:127.0.0.1:7860 nokey@localhost.run
```

Apri sul telefono l'URL `https://...localhost.run` mostrato dal comando SSH.

## Script

- `yesno_live_web.py`: web app per iPhone/Android (Safari/Chrome)
- `yesno_live_inference.py`: GUI desktop locale
- `asr_yesno_benchmark.py`: benchmark ASR su YESNO
- `train_audio_compare.py`: training pipeline custom
