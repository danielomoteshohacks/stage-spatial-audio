<script lang="ts">
  // The player's centrepiece: the listener seen from above, the cover art as the listener's disc,
  // and every part of the song as a light around it where SoundStage placed it. This replaces a
  // flat album square, which made the player look like any other music app, with the one thing
  // only this app has: where each sound is.
  //
  // Original stereo: the lights sit on one line through the head (that is where headphone stereo
  // puts sound). Spatial: they travel out to their places in the plan, the single orchestrated
  // motion of the app, so the switch is something you see as well as hear. While playing, the disc
  // turns slowly and the lights breathe; with reduced motion both stay still.
  import type { Plan3 } from "../lib/scene3";
  import { placeObjects, ROLE_LABELS } from "../lib/scene3";
  import type { Side } from "../lib/stream";
  import Art from "./Art.svelte";

  let {
    plan,
    side,
    playing,
    time,
    artId,
    artworkUrl,
    title,
  }: {
    plan: Plan3 | null;
    side: Side;
    playing: boolean;
    time: number;
    artId: string;
    artworkUrl: string;
    title: string;
  } = $props();

  const SIZE = 320;
  const C = SIZE / 2;
  const RING = 136; // outer ring radius: a part at the listener's side or behind sits here
  const DISC = 66; // the cover disc

  // One colour per family of parts, chosen to stay distinct from each other on both themes.
  const ROLE_COLOUR: Record<string, string> = {
    lead_vocal: "var(--orb-voice)",
    backing_vocal: "var(--orb-voice-2)",
    kick: "var(--orb-drums)",
    snare: "var(--orb-drums)",
    drums: "var(--orb-drums)",
    toms: "var(--orb-drums)",
    cymbals: "var(--orb-air)",
    bass: "var(--orb-bass)",
    guitar: "var(--orb-strings)",
    keys: "var(--orb-keys)",
    pad: "var(--orb-air)",
    fx: "var(--orb-fx)",
    other: "var(--orb-keys)",
  };

  // Before a plan exists (while the first part renders) the parts a four-stem split always has
  // are shown in the middle, waiting, so the screen is never empty.
  const PLACEHOLDER: Plan3 = {
    version: 3,
    stems: [
      { name: "voice", leaf: "voice", kind: "object", role: "lead_vocal", mode: "mono", az: 0, el: 7, dist: 1, feeds: [{ ch: "M", az: 0, el: 7 }] },
      { name: "drums", leaf: "drums", kind: "object", role: "drums", mode: "upmix", az: 70, el: 10, dist: 1.6, feeds: [{ ch: "C", az: 0, el: 0 }, { ch: "Ls", az: 70, el: 10 }, { ch: "Rs", az: -70, el: 10 }] },
      { name: "bass", leaf: "bass", kind: "object", role: "bass", mode: "mono", az: 0, el: 0, dist: 1.2, feeds: [{ ch: "M", az: 0, el: 0 }] },
      { name: "other", leaf: "other", kind: "object", role: "other", mode: "upmix", az: 85, el: 10, dist: 2, feeds: [{ ch: "C", az: 0, el: 10 }, { ch: "Ls", az: 85, el: 10 }, { ch: "Rs", az: -85, el: 10 }] },
    ],
  };

  const placed = $derived(placeObjects(plan ?? PLACEHOLDER, time).filter((p) => p.kind === "object"));

  interface Light {
    key: string;
    role: string;
    label: string;
    x: number;
    y: number;
    r: number;
    delay: number;
  }

  // Spatial: top view, front up, positive azimuth to the left. Height pulls a light inwards (it
  // is above you, not beside you) and distance pushes it out. Original: a line through the head,
  // left side, centre and right side of each part where headphone stereo puts them.
  const lights = $derived.by((): Light[] => {
    const out: Light[] = [];
    placed.forEach((p, i) => {
      p.feeds.forEach((f, j) => {
        const feedCh = (plan ?? PLACEHOLDER).stems[i]?.feeds[j]?.ch ?? "M";
        let x: number;
        let y: number;
        if (side === "spatial" && plan) {
          const a = (f.az * Math.PI) / 180;
          const lift = Math.cos((Math.max(0, f.el) * Math.PI) / 180);
          const reach = (DISC + 18 + (RING - DISC - 18) * Math.min(1, p.dist / 2.4)) * (0.55 + 0.45 * lift);
          x = C - Math.sin(a) * reach;
          y = C - Math.cos(a) * reach;
        } else {
          const lane = feedCh === "Ls" || feedCh === "L" ? -1 : feedCh === "Rs" || feedCh === "R" ? 1 : 0;
          x = C + lane * (DISC + 26);
          y = C + (i - (placed.length - 1) / 2) * 9;
        }
        out.push({
          key: `${p.name}:${j}`,
          role: p.role,
          label: ROLE_LABELS[p.role] ?? p.role,
          x,
          y,
          r: feedCh === "C" || feedCh === "M" ? 7.5 : 5.5,
          delay: (i * 0.23 + j * 0.11) % 1.6,
        });
      });
    });
    return out;
  });

  const parts = $derived([...new Set(placed.map((p) => ROLE_LABELS[p.role] ?? p.role))].join(", "));
</script>

<figure class="orbit" class:playing class:spatial={side === "spatial" && !!plan}>
  <svg viewBox="0 0 {SIZE} {SIZE}" role="img" aria-label={side === "spatial" && plan ? `Where each part plays: ${parts}` : `Original stereo: ${parts} between your ears`}>
    <defs>
      <radialGradient id="orb-floor" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--orb-floor)" stop-opacity="0.9" />
        <stop offset="100%" stop-color="var(--orb-floor)" stop-opacity="0" />
      </radialGradient>
    </defs>
    <circle cx={C} cy={C} r={RING + 18} fill="url(#orb-floor)" />
    <circle class="ring" cx={C} cy={C} r={RING} />
    <circle class="ring inner" cx={C} cy={C} r={(RING + DISC) / 2 + 4} />
    <!-- Where "in front of you" is: the one fixed reference, so the picture reads as a top view. -->
    <path class="front" d="M {C - 7} {C - RING - 9} L {C} {C - RING - 16} L {C + 7} {C - RING - 9}" />
    {#each lights as l (l.key)}
      <g class="light" style="transform: translate({l.x}px, {l.y}px); --c:{ROLE_COLOUR[l.role] ?? 'var(--orb-keys)'}; --d:{l.delay}s">
        <circle class="halo" r={l.r * 2.6} />
        <circle class="core" r={l.r} />
        <title>{l.label}</title>
      </g>
    {/each}
  </svg>
  <div class="disc" style="--disc:{DISC * 2}px">
    <Art id={artId} src={artworkUrl} size={DISC * 2} radius={DISC} label={`Cover of ${title}`} eager />
  </div>
</figure>

<style>
  .orbit {
    position: relative;
    margin: 0 auto;
    width: min(340px, 86vw);
    aspect-ratio: 1;
    --orb-voice: #ff6b6b;
    --orb-voice-2: #ff9f7a;
    --orb-drums: #ffc145;
    --orb-bass: #8f7bff;
    --orb-strings: #36c5f0;
    --orb-keys: #2ed3b7;
    --orb-air: #b8e986;
    --orb-fx: #f78fd3;
    --orb-floor: color-mix(in oklab, var(--tint-1, var(--lagoon)) 30%, transparent);
  }
  svg {
    width: 100%;
    height: 100%;
    overflow: visible;
  }
  .ring {
    fill: none;
    stroke: var(--text);
    stroke-opacity: 0.14;
    stroke-width: 1;
  }
  .ring.inner {
    stroke-dasharray: 2 6;
    stroke-opacity: 0.12;
  }
  .front {
    fill: none;
    stroke: var(--text);
    stroke-opacity: 0.45;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  /* The lights travel between the stereo line and their places: one long, settling move. */
  .light {
    transition: transform 1100ms var(--spring);
  }
  .core {
    fill: var(--c);
    stroke: rgb(255 255 255 / 0.85);
    stroke-width: 1.5;
  }
  .halo {
    fill: var(--c);
    opacity: 0.18;
    transform-box: fill-box;
    transform-origin: center;
  }
  .playing .halo {
    animation: breathe 1.6s ease-in-out infinite;
    animation-delay: var(--d);
  }
  @keyframes breathe {
    50% {
      transform: scale(1.35);
      opacity: 0.32;
    }
  }
  .disc {
    position: absolute;
    left: 50%;
    top: 50%;
    width: var(--disc);
    height: var(--disc);
    transform: translate(-50%, -50%);
    border-radius: 50%;
    box-shadow: 0 10px 30px rgb(0 0 0 / 0.25), 0 0 0 6px color-mix(in oklab, var(--bg) 70%, transparent);
  }
  .disc :global(.art) {
    width: 100%;
    height: 100%;
  }
  .playing .disc :global(.art) {
    animation: turn 40s linear infinite;
  }
  @keyframes turn {
    to {
      transform: rotate(1turn);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .light {
      transition: none;
    }
    .playing .halo,
    .playing .disc :global(.art) {
      animation: none;
    }
  }
</style>
