// Plain-language names for the engine's technical settings. The technical names stay visible in
// the advanced drawer and in the run report, so nothing is hidden, only translated.

export interface ProfileInfo {
  label: string;
  detail: string;
}

const PROFILE_INFO: Record<string, ProfileInfo> = {
  "space:studio": { label: "Studio", detail: "Measured ears in a treated control room: close, dry, faithful" },
  "space:living_room": { label: "Living room", detail: "Measured ears in a furnished room at home" },
  "space:car": { label: "Car", detail: "A small cabin with close glass reflections" },
  "space:club": { label: "Club", detail: "A treated club room, about a second of reverb" },
  "space:concert_hall": { label: "Concert hall", detail: "A large hall, two seconds of reverb" },
  "space:cinema": { label: "Cinema", detail: "An auditorium with a short, even decay" },
  max: { label: "v1 full stage", detail: "The v1 engine: analytic head, front arc, bass-safe room" },
  V0: { label: "Wide only", detail: "Head model only: positions widened around you" },
  V1: { label: "Front arc", detail: "Wide, kept within 60 degrees in front of you" },
  V2: { label: "Ear shape", detail: "Front arc plus a pinna (outer ear) model" },
  V3: { label: "Front/back tone", detail: "Ear shape plus directional tone bands" },
  V4: { label: "Room", detail: "Adds early room reflections (failed its bass gate; for comparison)" },
  V4b: { label: "Room, bass-safe", detail: "Early reflections high-passed at 200 Hz" },
  V5: { label: "Room and tail", detail: "Adds a reverb tail (failed its gates; for comparison)" },
  V5b: { label: "Room and tail, bass-safe", detail: "Bass-safe reflections plus a reverb tail" },
};

export function profileInfo(name: string): ProfileInfo {
  return PROFILE_INFO[name] ?? { label: name, detail: "Profile reported by the backend" };
}

/** Order the backend's profile names: the recommended one first, then the ablation chain. */
export function orderProfiles(names: string[]): string[] {
  const known = Object.keys(PROFILE_INFO); // the v2 spaces first, studio first of all
  const rank = (n: string) => (known.includes(n) ? known.indexOf(n) : known.length);
  return [...names].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

export function widthLabel(beta: number): string {
  if (beta < 1.25) return "Close to the original";
  if (beta < 1.75) return "A little wider";
  if (beta < 2.15) return "Wide";
  return "Widest";
}

export const SPACES = ["studio", "living_room", "car", "club", "concert_hall", "cinema"] as const;
export type SpaceName = (typeof SPACES)[number];

export const SPACE_INFO: Record<SpaceName, ProfileInfo> = {
  studio: { label: "Studio", detail: "A treated control room: close, dry and exact" },
  living_room: { label: "Living room", detail: "A furnished room at home, warm and near" },
  car: { label: "Car", detail: "A small cabin with close glass" },
  club: { label: "Club", detail: "A treated room with about a second of reverb" },
  concert_hall: { label: "Concert hall", detail: "Two seconds of hall around and above you" },
  cinema: { label: "Cinema", detail: "A big room with a short, even decay" },
};

export const CHARACTERS = ["intimate", "balanced", "immersive"] as const;
export type Character = (typeof CHARACTERS)[number];

export const CHARACTER_INFO: Record<Character, ProfileInfo> = {
  intimate: { label: "Intimate", detail: "Less room, a closer stage" },
  balanced: { label: "Balanced", detail: "The genre's scene as written" },
  immersive: { label: "Immersive", detail: "More room and more height around you" },
};

export const GENRES: { id: string; label: string }[] = [
  { id: "auto", label: "Detect" },
  { id: "afrobeats", label: "Afrobeats" },
  { id: "amapiano", label: "Amapiano" },
  { id: "hiphop", label: "Hip-hop and rap" },
  { id: "rnb", label: "R&B and soul" },
  { id: "gospel", label: "Gospel and choir" },
  { id: "house", label: "House and EDM" },
  { id: "pop", label: "Pop" },
  { id: "rock", label: "Rock" },
  { id: "acoustic", label: "Acoustic" },
  { id: "classical", label: "Classical" },
];

export function motionLabel(m: number): string {
  if (m <= 0.01) return "Still";
  if (m < 0.35) return "Subtle";
  if (m < 0.7) return "Moving";
  return "Full motion";
}

export const MODE_INFO: Record<string, ProfileInfo> = {
  lite: { label: "Lite", detail: "Spatialises the whole mix. Fast, runs on a CPU." },
  stems: {
    label: "Stems",
    detail: "Separates vocals, drums, bass and other first, then places each. Needs Demucs.",
  },
};

export const STAGE_LABELS: Record<string, string> = {
  load: "Reading the track",
  separate: "Separating stems",
  analyse: "Reading the music",
  render: "Rendering the stage",
  levels: "Matching loudness",
  guard: "Checking fidelity",
  write: "Writing files",
};

export const STEM_LABELS: Record<string, string> = {
  vocals: "Vocals",
  drums: "Drums",
  bass: "Bass",
  other: "Other",
  low_end: "Low end",
  lead_vocal: "Lead vocal",
  backing_vocals: "Backing vocals",
  vocal_stack: "Vocal stack",
  harmonies: "Harmonies",
  harmony: "Harmony",
  adlibs: "Ad-libs",
  choir: "Choir",
  chorus: "Chorus",
  soloist: "Soloist",
  vocal_fx: "Vocal effects",
  backing: "Backing vocals",
  kit: "Drum kit",
  percussion: "Percussion",
  shakers: "Shakers",
  hats: "Hats",
  hats_overhead: "Hats overhead",
  cymbals: "Cymbals",
  shaker: "Shaker",
  guitars_keys: "Guitars and keys",
  keys: "Keys",
  keys_guitar: "Keys and guitar",
  guitars: "Guitars",
  instruments: "Instruments",
  synths: "Synths",
  beat: "Beat",
  band: "Band",
  orchestra: "Orchestra",
  low_strings: "Low strings",
  pads: "Pads",
  ambience: "Ambience",
  room: "Room",
  hall: "Hall",
  front: "Front stage",
};
