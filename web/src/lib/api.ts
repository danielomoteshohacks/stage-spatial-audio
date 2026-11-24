// Client for the SoundStage backend's Gradio HTTP API (space/app.py). Written against the raw
// protocol rather than @gradio/client so the first load stays small on mobile data:
//   POST /gradio_api/upload              multipart "files"     -> ["<server path>"]
//   POST /gradio_api/call/process        {"data": [...]}       -> {"event_id": "..."}
//   GET  /gradio_api/call/process/<id>   server-sent events: generating*, then complete | error
//   GET  /gradio_api/file=<server path>  a returned file

export type StageStatus = "pending" | "running" | "ok" | "failed" | "skipped";

export interface StageState {
  stage: string;
  status: StageStatus;
  duration_s: number;
  error: string | null;
}

export interface RunReport {
  app: string;
  stage_version: string;
  created_utc: string;
  input: {
    name: string;
    start_s: number;
    start_mode?: "auto" | "manual" | "file";
    auto_start?: { loudness_lufs: number } | null;
    requested_seconds: number | null;
    sample_rate?: number;
    channels?: number;
    duration_s?: number;
  };
  requested_mode: "lite" | "stems";
  mode: "lite" | "stems";
  profile: string;
  beta: number;
  fallback: { from: string; to: string; reason: string } | null;
  separation: {
    model: string;
    device: string;
    stems: string[];
    residual_snr_db: number | null;
    residual_is_zero: boolean;
    notes: string[];
  } | null;
  levels: {
    original_rms_dbfs: number | null;
    spatial_raw_rms_dbfs: number | null;
    spatial_rms_dbfs: number | null;
    peak_gain_db: number;
    peak_limited: boolean;
  } | null;
  stages: { name: string; status: StageStatus; duration_s: number; error: string | null }[];
  outputs: Record<string, unknown>;
  ok: boolean;
}

export interface GuardReport {
  verdict: "pass" | "review" | "fail";
  reasons: string[];
  loudness_lufs: { original: number; render: number };
  timbre_deviation_db?: number;
  low_end_corr: number;
  artifact_flags?: { kind: string; start_s: number; end_s: number; detail?: string }[];
  [key: string]: unknown;
}

export interface Progress {
  stages: StageState[];
  done: boolean;
  error: string | null;
  run?: RunReport;
  notes?: string[];
  expires_in_s?: number;
  report?: GuardReport | null;
  plan?: import("./scene").Plan | null;
  track_id?: string | null;
  files?: Record<string, string>;
}

export interface FileData {
  path: string;
  url?: string | null;
  orig_name?: string | null;
  size?: number | null;
}

export type ProcessOutput = [Progress, FileData | null, FileData | null, FileData[] | null, FileData | null];

export interface ProcessRequest {
  mode: "lite" | "stems";
  profile: string;
  beta: number;
  /** Seconds into the track, or null for "auto": the backend picks the loudest window. */
  start: number | null;
  seconds: number | null;
  /** A template name, or "auto" for the backend's tagger. */
  genre?: string;
  /** Motion depth, 0 (still) to 1. */
  motion?: number;
  /** An edited plan to render instead of building one. */
  plan?: unknown;
  /** Also write the 7.1.4 bed for producers. */
  exportBed?: boolean;
  /** How far the scene opens: intimate, balanced or immersive. */
  character?: "intimate" | "balanced" | "immersive";
}

export interface BackendInfo {
  profiles: string[];
  modes: string[];
}

export class BackendError extends Error {
  constructor(
    message: string,
    readonly kind: "unreachable" | "protocol" | "server" | "cancelled",
  ) {
    super(message);
  }
}

export interface Diagnosis {
  title: string;
  detail: string;
  fixes: string[];
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]);

/**
 * Explain why a backend cannot be reached from this page, with the exact fix. Browsers report all
 * of these as the same opaque network error, so the cause is inferred from the two addresses.
 */
export function diagnose(backend: string, page: { protocol: string; hostname: string }): Diagnosis {
  let url: URL | null = null;
  try {
    url = new URL(backend);
  } catch {
    // Reported below as an unreachable address.
  }
  const backendLocal = url ? LOCAL_HOSTS.has(url.hostname) : false;
  const pageLocal = LOCAL_HOSTS.has(page.hostname);
  if (url && page.protocol === "https:" && url.protocol === "http:" && !backendLocal) {
    return {
      title: "This page cannot call an http:// backend",
      detail:
        "The page is served over HTTPS, and browsers block requests from it to a plain http:// address on your network.",
      fixes: [
        "Use the Hugging Face Space as the backend (its address starts with https://).",
        "Or run the web app from your laptop: cd web && npm run dev -- --host, then open the http:// Network address it prints on your phone.",
      ],
    };
  }
  if (url && backendLocal && !pageLocal) {
    return {
      title: `Cannot reach ${backend} from here`,
      detail:
        "127.0.0.1 always means the device you are holding. On a phone that is the phone itself, not your laptop. Gradio also only answers pages opened from localhost when it listens on localhost.",
      fixes: [
        "On the laptop: GRADIO_SERVER_NAME=0.0.0.0 python space/app.py",
        "Then set the backend to the laptop's Wi-Fi address, for example http://192.168.1.20:7860",
      ],
    };
  }
  return {
    title: `The backend at ${backend} is not answering`,
    detail: "Nothing responded at that address, or it is not a SoundStage backend.",
    fixes: [
      "On your laptop, from the repository: python -m pip install -e \".[backend]\" then python space/app.py",
      "Or set the backend to your Hugging Face Space, https://<user>-<space>.hf.space (a sleeping Space can take a minute to wake).",
      "Then press Check again.",
    ],
  };
}

async function fetchWithTimeout(input: string, init: RequestInit, ms: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  const outer = init.signal;
  outer?.addEventListener("abort", () => ctrl.abort(), { once: true });
  try {
    return await fetch(input, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

interface ApiInfoParameter {
  parameter_name?: string;
  type?: { enum?: string[] };
}

/** Read the backend's API description; the profile list comes from the backend, not this page. */
export function parseInfo(info: unknown): BackendInfo {
  const endpoints = (info as { named_endpoints?: Record<string, { parameters?: ApiInfoParameter[] }> })
    ?.named_endpoints;
  const params = endpoints?.["/process"]?.parameters;
  if (!params) throw new BackendError("That server has no /process endpoint; is it a SoundStage backend?", "protocol");
  const enumOf = (name: string) => params.find((p) => p.parameter_name === name)?.type?.enum ?? [];
  const profiles = enumOf("profile");
  const modes = enumOf("mode");
  if (!profiles.length) throw new BackendError("The backend did not list any profiles.", "protocol");
  return { profiles, modes: modes.length ? modes : ["lite", "stems"] };
}

export async function checkBackend(base: string, signal?: AbortSignal): Promise<BackendInfo> {
  let res: Response;
  try {
    res = await fetchWithTimeout(`${base}/gradio_api/info`, { signal }, 8000);
  } catch {
    throw new BackendError(`No answer from ${base}`, "unreachable");
  }
  if (!res.ok) throw new BackendError(`${base} answered with HTTP ${res.status}`, "unreachable");
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new BackendError(`${base} did not answer like a Gradio backend`, "protocol");
  }
  return parseInfo(body);
}

/** Upload with XMLHttpRequest because fetch still cannot report upload progress. */
export function uploadFile(
  base: string,
  file: File,
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${base}/gradio_api/upload`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new BackendError("The upload was interrupted.", "unreachable"));
    xhr.onabort = () => reject(new BackendError("Cancelled.", "cancelled"));
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new BackendError(`The backend refused the upload (HTTP ${xhr.status}).`, "server"));
        return;
      }
      try {
        const paths = JSON.parse(xhr.responseText) as string[];
        if (!Array.isArray(paths) || typeof paths[0] !== "string") throw new Error("no path");
        resolve(paths[0]);
      } catch {
        reject(new BackendError("The backend's upload answer was not understood.", "protocol"));
      }
    };
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    form.append("files", file, file.name);
    xhr.send(form);
  });
}

export interface SseEvent {
  event: string;
  data: string;
}

/** Incremental server-sent-events parser: feed text chunks, get whole events back. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const events: SseEvent[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length || event !== "message") events.push({ event, data: data.join("\n") });
    }
    return events;
  }
}

export function buildPayload(serverPath: string, fileName: string, req: ProcessRequest): unknown {
  return {
    data: [
      { path: serverPath, orig_name: fileName, meta: { _type: "gradio.FileData" } },
      req.mode,
      req.profile,
      req.beta,
      // Sent as text: the backend reads an empty field as its default ("auto" start, 30 s).
      req.start === null ? "" : String(req.start),
      req.seconds === null ? "" : String(req.seconds),
      req.genre ?? "auto",
      req.motion ?? 0.5,
      req.plan === undefined ? "" : JSON.stringify(req.plan),
      req.exportBed ?? false,
      req.character ?? "balanced",
    ],
  };
}

/** The /rerender payload: a cached track id instead of a file. */
export function buildRerenderPayload(trackId: string, req: ProcessRequest): unknown {
  return {
    data: [
      trackId,
      req.mode,
      req.profile,
      req.beta,
      req.genre ?? "auto",
      req.motion ?? 0.5,
      req.plan === undefined ? "" : JSON.stringify(req.plan),
      req.exportBed ?? false,
      req.character ?? "balanced",
    ],
  };
}

/** Start a /process job and stream its updates; resolves with the final output. */
export function runProcess(
  base: string,
  serverPath: string,
  fileName: string,
  req: ProcessRequest,
  onUpdate: (out: ProcessOutput) => void,
  signal?: AbortSignal,
): Promise<ProcessOutput> {
  return runEndpoint(base, "process", buildPayload(serverPath, fileName, req), onUpdate, signal);
}

/** Re-render a cached track (no upload) and stream its updates. */
export function runRerender(
  base: string,
  trackId: string,
  req: ProcessRequest,
  onUpdate: (out: ProcessOutput) => void,
  signal?: AbortSignal,
): Promise<ProcessOutput> {
  return runEndpoint(base, "rerender", buildRerenderPayload(trackId, req), onUpdate, signal);
}

async function runEndpoint(
  base: string,
  endpoint: "process" | "rerender",
  payload: unknown,
  onUpdate: (out: ProcessOutput) => void,
  signal?: AbortSignal,
): Promise<ProcessOutput> {
  let start: Response;
  try {
    start = await fetch(`${base}/gradio_api/call/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch {
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("The backend stopped answering.", "unreachable");
  }
  if (!start.ok) throw new BackendError(`The backend refused the job (HTTP ${start.status}).`, "server");
  const { event_id: eventId } = (await start.json()) as { event_id?: string };
  if (!eventId) throw new BackendError("The backend did not start a job.", "protocol");

  let stream: Response;
  try {
    stream = await fetch(`${base}/gradio_api/call/${endpoint}/${eventId}`, { signal });
  } catch {
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("Lost the connection to the backend.", "unreachable");
  }
  if (!stream.ok || !stream.body) throw new BackendError("The backend did not stream progress.", "protocol");
  const reader = stream.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  let last: ProcessOutput | null = null;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const ev of parser.push(value)) {
        if (ev.event === "heartbeat") continue;
        if (ev.event === "error") {
          let message = "The backend reported an error.";
          try {
            const parsed = JSON.parse(ev.data);
            if (typeof parsed === "string" && parsed) message = parsed;
          } catch {
            if (ev.data && ev.data !== "null") message = ev.data;
          }
          throw new BackendError(message, "server");
        }
        if (ev.event === "generating" || ev.event === "complete") {
          const out = JSON.parse(ev.data) as ProcessOutput;
          last = out;
          onUpdate(out);
          if (ev.event === "complete") return out;
        }
      }
    }
  } catch (err) {
    if (err instanceof BackendError) throw err;
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("Lost the connection to the backend while it was working.", "unreachable");
  }
  if (last && last[0]?.done) return last;
  throw new BackendError("The backend closed the stream before finishing.", "protocol");
}

export function fileUrl(base: string, file: FileData): string {
  return `${base}/gradio_api/file=${file.path}`;
}

export async function fetchArrayBuffer(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  let res: Response;
  try {
    res = await fetch(url, { signal });
  } catch {
    if (signal?.aborted) throw new BackendError("Cancelled.", "cancelled");
    throw new BackendError("Could not download the rendered audio.", "unreachable");
  }
  if (!res.ok) {
    throw new BackendError(
      res.status === 404
        ? "The rendered files have expired on the server. Process the track again."
        : `Could not download the rendered audio (HTTP ${res.status}).`,
      "server",
    );
  }
  return res.arrayBuffer();
}

export function stemName(file: FileData): string {
  const name = (file.orig_name || file.path.split("/").pop() || "").replace(/\.flac$/i, "");
  return name;
}
