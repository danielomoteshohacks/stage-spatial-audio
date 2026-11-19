/** Browser-only helpers around AudioContext creation and decoding. */

type AudioSessionNavigator = Navigator & { audioSession?: { type: string } };

let ctx: AudioContext | null = null;

/** One shared context, created lazily from a user gesture. */
export function getContext(): AudioContext {
  if (!ctx) {
    // Safari mutes Web Audio with the ringer switch unless the session is marked as playback.
    const nav = navigator as AudioSessionNavigator;
    if (nav.audioSession) {
      try {
        nav.audioSession.type = "playback";
      } catch {
        // Older Safari: not supported, the ringer switch may mute playback.
      }
    }
    ctx = new AudioContext({ latencyHint: "interactive" });
  }
  return ctx;
}

export async function decodeFile(context: BaseAudioContext, file: File): Promise<AudioBuffer> {
  const bytes = await file.arrayBuffer();
  try {
    return await context.decodeAudioData(bytes);
  } catch (err) {
    const reason = err instanceof Error && err.message ? `: ${err.message}` : "";
    throw new Error(`This browser could not decode ${file.name}${reason}.`, { cause: err });
  }
}
