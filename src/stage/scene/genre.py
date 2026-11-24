"""Genre and style tagging with an AudioSet audio tagger, mapped onto SoundStage's templates.

Decision 0017. The tagger is the Audio Spectrogram Transformer fine-tuned on AudioSet (Gong,
Chung and Glass 2021, "AST: Audio Spectrogram Transformer", Interspeech), model
`MIT/ast-finetuned-audioset-10-10-0.4593` on the Hugging Face hub, run through the transformers
library. It is optional and lazy:

* it runs only where transformers and torch are installed (the Space), never in CI;
* before loading, the model card's licence is read from the hub and the model is refused unless
  it is one of PERMISSIVE;
* AudioSet's label set is the 2017 ontology: it has "Afrobeat" but no "Amapiano", so each
  template lists the nearest labels (`audioset` in configs/templates). The labels a template
  asks for that the model does not have are reported, not silently ignored;
* the listener's genre choice always wins over the tagger.

Scores: each template's score is the largest probability among its labels; the template with
the highest score wins if it reaches MIN_SCORE, otherwise the default template is used.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.signal import resample_poly

MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
PERMISSIVE = {"bsd-3-clause", "bsd-2-clause", "mit", "apache-2.0", "cc-by-4.0"}
MIN_SCORE = 0.08
WINDOW_S = 10.0


class TaggerUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load() -> tuple[Any, Any, str]:
    try:
        import torch  # noqa: F401
        from huggingface_hub import model_info
        from transformers import ASTFeatureExtractor, ASTForAudioClassification
    except ImportError as exc:
        raise TaggerUnavailable(f"the tagger needs transformers and torch ({exc})") from exc
    try:
        info = model_info(MODEL)
        licence = str(getattr(info.card_data, "license", None) or "").lower()
    except Exception as exc:
        raise TaggerUnavailable(f"could not read the model card of {MODEL}: {exc}") from exc
    if licence not in PERMISSIVE:
        raise TaggerUnavailable(f"{MODEL} is licensed {licence or 'unknown'}, not permissive")
    extractor = ASTFeatureExtractor.from_pretrained(MODEL)
    model = ASTForAudioClassification.from_pretrained(MODEL).eval()
    return extractor, model, licence


def audioset_scores(audio: NDArray, sample_rate: int) -> tuple[dict[str, float], str]:
    """Label probabilities (sigmoid, AudioSet is multi-label) for the loudest 10 s, and licence."""
    import torch

    extractor, model, licence = _load()
    mono = np.asarray(audio, dtype=np.float64).mean(axis=0)
    x = resample_poly(mono, 16000, sample_rate) if sample_rate != 16000 else mono
    n = int(WINDOW_S * 16000)
    if x.size > n:
        frame = 16000
        e = np.array([np.sum(x[i : i + frame] ** 2) for i in range(0, x.size - frame, frame)])
        best = int(np.argmax(np.convolve(e, np.ones(10), mode="valid"))) if e.size >= 10 else 0
        x = x[best * frame : best * frame + n]
    inputs = extractor(x.astype(np.float32), sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        logits = model(**inputs).logits[0]
    probs = torch.sigmoid(logits).numpy()
    labels = model.config.id2label
    return {labels[i]: float(p) for i, p in enumerate(probs)}, licence


def template_scores(scores: dict[str, float], templates: dict[str, dict]) -> tuple[
        dict[str, float], dict[str, list[str]]]:
    """Each template's score, and the labels each template names that the model lacks."""
    out, missing = {}, {}
    for name, t in templates.items():
        wanted = t.get("audioset", [])
        have = [scores[label] for label in wanted if label in scores]
        missing[name] = [label for label in wanted if label not in scores]
        out[name] = max(have) if have else 0.0
    return out, missing


def detect_genre(audio: NDArray, sample_rate: int, templates: dict[str, dict]
                 ) -> dict[str, Any]:
    """{"genre", "scores", "source", "detail"}: the tagger's choice, or why there is none."""
    try:
        raw, licence = audioset_scores(audio, sample_rate)
    except TaggerUnavailable as exc:
        return {"genre": None, "scores": {}, "source": "default", "detail": str(exc)}
    except Exception as exc:  # a broken tagger must not stop the render
        return {"genre": None, "scores": {}, "source": "default",
                "detail": f"tagger failed: {type(exc).__name__}: {exc}"}
    scores, missing = template_scores(raw, templates)
    best = max(scores, key=lambda k: scores[k]) if scores else None
    top = sorted(raw.items(), key=lambda kv: -kv[1])[:5]
    detail = {"model": MODEL, "licence": licence,
              "top_labels": [[k, round(v, 3)] for k, v in top],
              "labels_not_in_model": {k: v for k, v in missing.items() if v}}
    if best is None or scores[best] < MIN_SCORE:
        return {"genre": None, "scores": scores, "source": "default", "detail": detail}
    total = sum(scores.values()) or 1.0
    return {"genre": best, "scores": {k: v / total for k, v in scores.items()},
            "source": "tagger", "detail": detail}
