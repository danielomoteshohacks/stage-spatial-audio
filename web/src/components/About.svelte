<script lang="ts">
  // The About sheet: why SoundStage exists, in the owner's words, then how to use it and the
  // credits every dataset and model requires.
</script>

<article class="about">
  <section>
    <p class="lede">I listen on a Samsung Galaxy S21 FE. Apple Music shows the Dolby Atmos badge on a song either way, but it only renders the song spatially when the phone's own Dolby toggle is on. So whether I hear spatial audio depends on the phone, not on the app.</p>
    <p>SoundStage is my answer: the app owns the renderer. It takes any stereo song, keeps every sound where the mix put it, keeps the bass and the vocal exactly where the artist left them, and builds a stage around you that works on any phone with any headphones.</p>
    <p class="faint">Daniel Olumide Omotesho</p>
  </section>

  <section>
    <h3>How it works</h3>
    <ul>
      <li>Your track is split into vocals, drums, bass and the rest, then each part is placed around you through measured human-ear filters in a room you choose.</li>
      <li>Everything below 120 Hz passes through untouched, so the bass stays the record's bass.</li>
      <li>Every render is checked against the original for loudness, tone, timing, bass and audible artifacts. The badge on the player says what the check found.</li>
      <li>Your track is processed on the server and deleted after 30 minutes. Renders you keep stay on this phone.</li>
    </ul>
  </section>

  <section>
    <h3>Keys</h3>
    <dl class="keys">
      <div><dt>Space</dt><dd>Play or pause</dd></div>
      <div><dt>S</dt><dd>Original or spatial</dd></div>
      <div><dt>Left, Right</dt><dd>Back or forward 5 seconds</dd></div>
      <div><dt>[ and ]</dt><dd>Set the loop start and end</dd></div>
      <div><dt>L</dt><dd>Clear the loop</dd></div>
    </dl>
  </section>

  <section>
    <h3>Credits</h3>
    <ul class="credits">
      <li><strong>Head-related filters:</strong> SADIE II Database, subject D1 (Neumann KU100), The Audio Lab, University of York. C. Armstrong, L. Thresh, D. Murphy and G. Kearney, "A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study of the SADIE II Database", Applied Sciences 8(11), 2029, 2018. Copyright 2018 University of York, Apache License 2.0.</li>
      <li><strong>Stem separation:</strong> Demucs (htdemucs) by Meta AI Research, MIT licence, used until the SoundStage Separator passes it on the MUSDB18-HQ test set.</li>
      <li><strong>Genre tags:</strong> Audio Spectrogram Transformer fine-tuned on AudioSet (MIT/ast-finetuned-audioset-10-10-0.4593), loaded only under a permissive licence; AudioSet labels by Google, CC BY 4.0.</li>
      <li><strong>Type:</strong> Instrument Sans and Instrument Serif, SIL Open Font Licence 1.1.</li>
      <li><strong>Separator training data:</strong> MUSDB18-HQ (Rafii et al. 2019), research use only.</li>
    </ul>
    <p class="faint">SoundStage is independent and is not affiliated with Apple, Spotify, Samsung or Dolby. Source code: <a href="https://github.com/danielomoteshohacks/stage-spatial-audio">github.com/danielomoteshohacks/stage-spatial-audio</a>.</p>
  </section>
</article>

<style>
  .about {
    display: grid;
    gap: var(--gap-6);
  }

  section {
    display: grid;
    gap: var(--gap-3);
  }

  .lede {
    font-family: var(--font-display);
    font-size: var(--text-xl);
    line-height: 1.25;
  }

  h3 {
    font-size: var(--text-lg);
  }

  ul {
    margin: 0;
    padding-left: 1.1em;
    display: grid;
    gap: var(--gap-2);
    color: var(--ivory-2);
  }

  .credits {
    font-size: var(--text-sm);
  }

  .keys {
    display: grid;
    gap: 6px;
    margin: 0;
  }

  .keys div {
    display: flex;
    gap: var(--gap-4);
  }

  dt {
    min-width: 7.5rem;
    font-weight: 600;
  }

  dd {
    margin: 0;
    color: var(--ivory-2);
  }
</style>
