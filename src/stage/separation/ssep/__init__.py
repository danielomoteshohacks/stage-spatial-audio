"""SoundStage Separator (ssep): our own compact band-split, dual-domain separation engine.

Decision 0015. Layout:

* `config`  - sizes, stems and the band split, shared by training, export and inference.
* `dsp`     - the numpy STFT pair used at inference and the DSP back end (multichannel Wiener
              refinement, mixture consistency, bleed reduction, leakage estimates).
* `model`   - the PyTorch network with its spatial, HPSS and f0 front end (training and export;
              imported only when torch is installed).
* `infer`   - ONNX Runtime inference on the CPU, chunked, with the back end.

Nothing here downloads anything; weights come from the Hugging Face model repository named in
`config.WEIGHTS_REPO` through `infer.find_weights`, and only when a caller asks for them.
"""
