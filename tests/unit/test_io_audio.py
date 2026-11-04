import numpy as np
import pytest
import soundfile as sf

from stage.io import read_audio, to_stereo


def test_read_audio_layout_and_excerpt(tmp_path):
    sr = 8000
    data = np.random.default_rng(0).uniform(-0.5, 0.5, size=(sr * 2, 2))
    path = tmp_path / "clip.wav"
    sf.write(path, data, sr, subtype="PCM_24")

    full, rate = read_audio(path)
    assert rate == sr
    assert full.shape == (2, sr * 2)

    part, _ = read_audio(path, start_s=0.5, duration_s=0.25)
    assert part.shape == (2, sr // 4)
    assert np.allclose(part, full[:, sr // 2 : sr // 2 + sr // 4])


def test_mono_is_duplicated_and_multichannel_rejected():
    mono = np.ones((1, 10))
    assert to_stereo(mono).shape == (2, 10)
    with pytest.raises(ValueError):
        to_stereo(np.ones((3, 10)))
