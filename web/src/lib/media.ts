// Lock-screen and notification controls through the Media Session API, with the cover art.

export interface MediaHandlers {
  play: () => void;
  pause: () => void;
  seek: (t: number) => void;
  position: () => { t: number; duration: number };
}

export function setMediaSession(meta: { title: string; artist?: string; artworkUrl?: string | null }, h: MediaHandlers): void {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  const ms = navigator.mediaSession;
  ms.metadata = new MediaMetadata({
    title: meta.title,
    artist: meta.artist ?? "SoundStage",
    album: "SoundStage spatial render",
    artwork: meta.artworkUrl ? [{ src: meta.artworkUrl, sizes: "512x512" }] : [{ src: "/icon-512.png", sizes: "512x512", type: "image/png" }],
  });
  const safe = (action: MediaSessionAction, fn: MediaSessionActionHandler) => {
    try {
      ms.setActionHandler(action, fn);
    } catch {
      // Older browsers reject actions they do not know.
    }
  };
  safe("play", () => h.play());
  safe("pause", () => h.pause());
  safe("seekto", (d) => d.seekTime !== undefined && h.seek(d.seekTime));
  safe("seekbackward", () => h.seek(Math.max(0, h.position().t - 10)));
  safe("seekforward", () => h.seek(Math.min(h.position().duration, h.position().t + 10)));
}

export function setPlaybackState(playing: boolean, t: number, duration: number): void {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  navigator.mediaSession.playbackState = playing ? "playing" : "paused";
  try {
    navigator.mediaSession.setPositionState({ duration, position: Math.min(t, duration), playbackRate: 1 });
  } catch {
    // Not supported or duration not known yet.
  }
}
