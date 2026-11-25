// Client for the v3 backend: whole-song jobs that stream segments while they render, and the
// catalogue. The job runs inside a Gradio event (so a ZeroGPU visitor's quota is charged to them)
// and streams state snapshots over server-sent events; the segments themselves are plain HTTP
// files under /v3/jobs/<id>/seg/, fetched as they appear in the snapshot.

import { BackendError, SseParser } from "./api";
import type { SegmentMeta } from "./stream";

export interface Licence {
  code: string;
  version: string;
  label: string;
  url: string;
  share_alike: boolean;
}

export interface Track {
  id: string;
  title: string;
  artist: string;
  audio_url: string;
  landing_url: string;
  licence: Licence;
  source: string;
  duration_s: number;
  artist_url: string;
  album: string;
  artwork_url: string;
  genres: string[];
  shelves: string[];
  attribution: string;
  prerendered?: { manifest: string } | null;
}

export interface Shelf {
  key: string;
  title: string;
  tracks: Track[];
}

export interface JobState {
  id?: string;
  status?: "queued" | "running" | "done" | "failed";
  stage?: string;
  done: boolean;
  error?: string | null;
  duration_s?: number;
  chunks_total?: number;
  chunks_done?: number;
  segments?: SegmentMeta[];
  time_to_first_sound_s?: number;
  tempo_bpm?: number;
  genre?: string;
  plan?: unknown;
  guard?: { verdict: "pass" | "review" | "fail"; reasons: string[] };
  run?: { rtf: number; wall_s: number; audio_s: number; chunks: number; format: string };
  files?: Record<string, string>;
  track?: Track;
}

export interface JobOptions {
  preset?: "fast" | "best" | "cpu";
  genre?: string | null;
  motion?: number;
  character?: "intimate" | "balanced" | "immersive";
  head?: string;
  space?: string | null;
  fmt?: "opus" | "aac" | "flac";
  start_s?: number;
  seconds?: number | null;
}

export function trim(base: string): string {
  return base.replace(/\/+$/, "");
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { signal });
  } catch {
    throw new BackendError("No answer from the server.", "unreachable");
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = (await res.json()) as { detail?: string };
      if (j.detail) detail = j.detail;
    } catch {
      // The body was not JSON; the status is the message.
    }
    throw new BackendError(detail, "server");
  }
  return (await res.json()) as T;
}

export const catalog = {
  shelves: (base: string, signal?: AbortSignal) =>
    getJson<{ shelves: Shelf[]; built_utc: string | null }>(`${trim(base)}/catalog/shelves`, signal),
  search: (base: string, q: string, signal?: AbortSignal) =>
    getJson<{ tracks: Track[] }>(`${trim(base)}/catalog/search?q=${encodeURIComponent(q)}`, signal),
  genre: (base: string, key: string, page = 1, signal?: AbortSignal) =>
    getJson<{ key: string; title: string; tracks: Track[] }>(`${trim(base)}/catalog/genre/${key}?page=${page}`, signal),
  artist: (base: string, name: string, signal?: AbortSignal) =>
    getJson<{ name: string; tracks: Track[] }>(`${trim(base)}/catalog/artist?name=${encodeURIComponent(name)}`, signal),
  track: (base: string, id: string, signal?: AbortSignal) =>
    getJson<Track>(`${trim(base)}/catalog/track/${encodeURIComponent(id).replace(/%3A/g, ":")}`, signal),
  legal: (base: string, signal?: AbortSignal) =>
    getJson<Record<string, unknown>>(`${trim(base)}/catalog/legal`, signal),
  audioUrl: (base: string, id: string) => `${trim(base)}/audio/${encodeURIComponent(id).replace(/%3A/g, ":")}`,
};

export const jobs = {
  state: (base: string, id: string, signal?: AbortSignal) => getJson<JobState>(`${trim(base)}/v3/jobs/${id}`, signal),
  segmentUrl: (base: string, id: string, file: string) => `${trim(base)}/v3/jobs/${id}/seg/${file}`,
  fileUrl: (base: string, id: string, name: string) => `${trim(base)}/v3/jobs/${id}/file/${name}`,
  health: (base: string, signal?: AbortSignal) =>
    getJson<{ version: string; formats: string[]; neural: boolean }>(`${trim(base)}/v3/health`, signal),
};

/** The formats this browser can decode, best first: Opus where it plays Ogg Opus, else AAC. */
export function pickFormat(serverFormats: string[], audio?: HTMLAudioElement): "opus" | "aac" | "flac" {
  const a = audio ?? document.createElement("audio");
  const opus = a.canPlayType('audio/ogg; codecs="opus"') !== "";
  if (opus && serverFormats.includes("opus")) return "opus";
  if (serverFormats.includes("aac") && a.canPlayType('audio/mp4; codecs="mp4a.40.2"') !== "") return "aac";
  return "flac";
}

/** Run a Gradio event that yields job-state JSON strings; calls onState for each snapshot. */
export async function streamJob(
  base: string,
  endpoint: "v3_process" | "v3_catalog",
  data: unknown[],
  onState: (s: JobState) => void,
  signal?: AbortSignal,
): Promise<JobState> {
  let start: Response;
  try {
    start = await fetch(`${trim(base)}/gradio_api/call/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data }),
      signal,
    });
  } catch {
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("The server stopped answering.", "unreachable");
  }
  if (!start.ok) throw new BackendError(`The server refused the job (HTTP ${start.status}).`, "server");
  const { event_id: eventId } = (await start.json()) as { event_id?: string };
  if (!eventId) throw new BackendError("The server did not start a job.", "protocol");
  const stream = await fetch(`${trim(base)}/gradio_api/call/${endpoint}/${eventId}`, { signal });
  if (!stream.ok || !stream.body) throw new BackendError("The server did not stream progress.", "protocol");
  const reader = stream.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  let last: JobState = { done: false };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const ev of parser.push(value)) {
        if (ev.event === "error") throw new BackendError("The server reported an error.", "server");
        if (ev.event === "generating" || ev.event === "complete") {
          const arr = JSON.parse(ev.data) as unknown[];
          if (typeof arr[0] === "string") {
            last = JSON.parse(arr[0]) as JobState;
            onState(last);
            if (last.done) return last;
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof BackendError) throw err;
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("Lost the connection to the server while it was working.", "unreachable");
  }
  return last;
}

export function optionsJson(o: JobOptions): string {
  return JSON.stringify(Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null)));
}
