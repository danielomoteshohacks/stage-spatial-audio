// What the screens list and play: a catalogue track or one of the listener's own uploads.
import type { LibrarySummary } from "./library";
import type { Track } from "./v3";

export interface Item {
  id: string;
  /** What the cover tint is derived from: the track, even for a saved copy of it. */
  artId?: string;
  title: string;
  artist: string;
  artworkUrl: string;
  durationS: number;
  kind: "catalog" | "upload";
  licence?: string;
  track?: Track;
  libraryId?: string;
}

export function fromTrack(t: Track): Item {
  return {
    id: t.id,
    title: t.title,
    artist: t.artist,
    artworkUrl: t.artwork_url,
    durationS: t.duration_s,
    kind: "catalog",
    licence: t.licence.label,
    track: t,
  };
}

export function fromLibrary(e: LibrarySummary, artworkUrl = ""): Item {
  return {
    id: `upload:${e.id}`,
    title: e.title || e.name.replace(/\.[^.]+$/, ""),
    artist: e.artist || "Your upload",
    artworkUrl,
    durationS: e.durationS,
    kind: "upload",
    libraryId: e.id,
  };
}

export function greeting(hour: number): string {
  if (hour < 5) return "Late night";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
