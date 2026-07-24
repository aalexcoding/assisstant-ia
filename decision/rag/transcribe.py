"""
Transcribe un WAV con faster-whisper (CTranslate2, backend int8 en CPU).

Se eligio faster-whisper frente a openai-whisper: mismos pesos que Whisper
(reimplementacion en CTranslate2), pero en CPU corre varias veces mas rapido
gracias a la cuantizacion int8, y no arrastra la dependencia de PyTorch
(instalacion mas ligera en un venv con include-system-site-packages=true).
Sin GPU en esta maquina, la velocidad en CPU es el factor que decide.

Se probaron los modelos "small" y "medium" contra el mismo clip de 528s:
- small:  65.6s de proceso (~8.1x mas rapido que el audio real), buena
  calidad, con algun desliz fonetico puntual en jerga de poker (p.ej.
  "botes" -> "botas" en 2 de 7 menciones).
- medium: 181.9s de proceso (~2.9x mas rapido que el audio real, es decir
  ~2.8x mas lento que small), corrige ese desliz pero al precio de casi
  triplicar el tiempo total sobre ~90h de video.
Se elige "small" por el corpus completo: la diferencia de tiempo (dias vs
horas) pesa mas que un puñado de terminos mal oidos, tolerable para
recuperacion semantica con chunks de varias frases.

Uso: .venv/bin/python decision/rag/transcribe.py <audio.wav>
"""
import argparse
import json

from faster_whisper import WhisperModel

MODEL_SIZE = "small"

_model = None


def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_path, model=None):
    model = model or get_model()
    segments, info = model.transcribe(wav_path, language="es", vad_filter=True)
    segments = [
        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        for seg in segments
    ]
    return segments, info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wav")
    args = parser.parse_args()
    segments, info = transcribe(args.wav)
    print(f"idioma detectado: {info.language} (p={info.language_probability:.2f})")
    print(json.dumps(segments, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
