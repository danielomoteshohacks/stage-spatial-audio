// Cover art from the file's own tags, without a tag library: ID3v2 APIC/PIC (MP3, and WAV files
// that carry an "id3 " chunk), FLAC PICTURE blocks and MP4/M4A "covr" atoms. Only the bytes that
// hold the tags are read (File.slice), so a 400 MB WAV costs a few kilobytes of reading.

export interface Artwork {
  mime: string;
  bytes: Uint8Array;
}

export interface TagInfo {
  title?: string;
  artist?: string;
  artwork?: Artwork;
}

type Source = Pick<Blob, "size" | "slice">;

async function read(src: Source, start: number, end: number): Promise<Uint8Array> {
  return new Uint8Array(await src.slice(start, Math.min(end, src.size)).arrayBuffer());
}

const ascii = (b: Uint8Array, s: number, n: number) => String.fromCharCode(...b.subarray(s, s + n));
const u32 = (b: Uint8Array, o: number) => ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0;
const u24 = (b: Uint8Array, o: number) => (b[o] << 16) | (b[o + 1] << 8) | b[o + 2];
const synchsafe = (b: Uint8Array, o: number) => (b[o] << 21) | (b[o + 1] << 14) | (b[o + 2] << 7) | b[o + 3];

function sniffMime(bytes: Uint8Array, fallback = "image/jpeg"): string {
  if (bytes[0] === 0x89 && bytes[1] === 0x50) return "image/png";
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return "image/jpeg";
  if (ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") return "image/webp";
  return fallback;
}

function decodeText(bytes: Uint8Array, encoding: number): string {
  const label = encoding === 1 ? "utf-16" : encoding === 2 ? "utf-16be" : encoding === 3 ? "utf-8" : "latin1";
  const text = new TextDecoder(label).decode(bytes);
  const nul = text.indexOf(String.fromCharCode(0));
  return (nul < 0 ? text : text.slice(0, nul)).trim();
}

/** End of a null-terminated string in an ID3 frame; UTF-16 encodings end with two zero bytes. */
function textEnd(b: Uint8Array, start: number, encoding: number): number {
  if (encoding === 1 || encoding === 2) {
    for (let i = start; i + 1 < b.length; i += 2) if (b[i] === 0 && b[i + 1] === 0) return i;
    return b.length;
  }
  const i = b.indexOf(0, start);
  return i < 0 ? b.length : i;
}

/** Parse an ID3v2 tag that starts at offset 0 of `b`. */
export function parseId3(b: Uint8Array): TagInfo {
  const out: TagInfo = {};
  if (ascii(b, 0, 3) !== "ID3") return out;
  const major = b[3];
  const flags = b[5];
  const size = synchsafe(b, 6);
  let p = 10;
  if (flags & 0x40 && major >= 3) p += major === 4 ? synchsafe(b, 10) : u32(b, 10) + 4; // extended header
  const end = Math.min(b.length, 10 + size);
  const idLen = major === 2 ? 3 : 4;
  while (p + idLen * 2 < end) {
    const id = ascii(b, p, idLen);
    if (!/^[A-Z0-9]+$/.test(id)) break;
    const fsize = major === 2 ? u24(b, p + 3) : major === 4 ? synchsafe(b, p + 4) : u32(b, p + 4);
    const head = major === 2 ? 6 : 10;
    const body = b.subarray(p + head, p + head + fsize);
    p += head + fsize;
    if (fsize <= 0) break;
    if (id === "TIT2" || id === "TT2") out.title = decodeText(body.subarray(1), body[0]);
    else if (id === "TPE1" || id === "TP1") out.artist = decodeText(body.subarray(1), body[0]);
    else if ((id === "APIC" || id === "PIC") && !out.artwork) {
      const enc = body[0];
      let q = 1;
      let mime: string;
      if (id === "PIC") {
        const fmt = ascii(body, 1, 3).toLowerCase();
        mime = fmt === "png" ? "image/png" : "image/jpeg";
        q = 4;
      } else {
        const z = body.indexOf(0, 1);
        mime = ascii(body, 1, z - 1) || "image/jpeg";
        q = z + 1;
      }
      q += 1; // picture type
      q = textEnd(body, q, enc) + (enc === 1 || enc === 2 ? 2 : 1); // description
      const bytes = body.slice(q);
      if (bytes.length > 16) out.artwork = { mime: mime.includes("/") ? mime : sniffMime(bytes), bytes };
    }
  }
  return out;
}

/** Parse the metadata blocks of a FLAC file: PICTURE (type 6) and VORBIS_COMMENT (type 4). */
export function parseFlac(b: Uint8Array): TagInfo {
  const out: TagInfo = {};
  if (ascii(b, 0, 4) !== "fLaC") return out;
  let p = 4;
  for (;;) {
    if (p + 4 > b.length) break;
    const last = (b[p] & 0x80) !== 0;
    const type = b[p] & 0x7f;
    const len = u24(b, p + 1);
    const body = b.subarray(p + 4, p + 4 + len);
    if (type === 6 && !out.artwork && body.length >= 32) {
      let q = 4;
      const mimeLen = u32(body, q);
      const mime = ascii(body, q + 4, mimeLen);
      q += 4 + mimeLen;
      q += 4 + u32(body, q); // description
      q += 16; // width, height, depth, colours
      const dataLen = u32(body, q);
      const bytes = body.slice(q + 4, q + 4 + dataLen);
      if (bytes.length > 16) out.artwork = { mime: mime || sniffMime(bytes), bytes };
    } else if (type === 4) {
      const le = (o: number) => body[o] | (body[o + 1] << 8) | (body[o + 2] << 16) | (body[o + 3] << 24);
      let q = 4 + le(0);
      const n = le(q);
      q += 4;
      const dec = new TextDecoder("utf-8");
      for (let i = 0; i < n && q + 4 <= body.length; i++) {
        const l = le(q);
        const s = dec.decode(body.subarray(q + 4, q + 4 + l));
        q += 4 + l;
        const eq = s.indexOf("=");
        const key = s.slice(0, eq).toUpperCase();
        if (key === "TITLE") out.title = s.slice(eq + 1);
        if (key === "ARTIST") out.artist = s.slice(eq + 1);
      }
    }
    p += 4 + len;
    if (last) break;
  }
  return out;
}

/** Walk MP4 atoms in `b` (already the payload of a container) looking for a path of names. */
function findAtom(b: Uint8Array, path: string[]): Uint8Array | null {
  let p = 0;
  while (p + 8 <= b.length) {
    let size = u32(b, p);
    const name = ascii(b, p + 4, 4);
    let head = 8;
    if (size === 1) {
      size = Number((BigInt(u32(b, p + 8)) << 32n) | BigInt(u32(b, p + 12)));
      head = 16;
    }
    if (size === 0) size = b.length - p;
    if (size < head) return null;
    if (name === path[0]) {
      // "meta" is a full atom: four bytes of version and flags before its children.
      const inner = b.subarray(p + head + (name === "meta" ? 4 : 0), p + size);
      return path.length === 1 ? inner : findAtom(inner, path.slice(1));
    }
    p += size;
  }
  return null;
}

export function parseMp4Moov(moov: Uint8Array): TagInfo {
  const out: TagInfo = {};
  const ilst = findAtom(moov, ["udta", "meta", "ilst"]);
  if (!ilst) return out;
  const data = (name: string) => findAtom(ilst, [name, "data"]);
  const covr = data("covr");
  if (covr && covr.length > 24) {
    const kind = u32(covr, 0);
    const bytes = covr.slice(8);
    out.artwork = { mime: kind === 14 ? "image/png" : kind === 13 ? "image/jpeg" : sniffMime(bytes), bytes };
  }
  const nam = data("©nam");
  if (nam) out.title = new TextDecoder().decode(nam.subarray(8));
  const art = data("©ART");
  if (art) out.artist = new TextDecoder().decode(art.subarray(8));
  return out;
}

/** Read the tags of an audio file, touching only the bytes that hold them. */
export async function readTags(file: Source): Promise<TagInfo> {
  try {
    const head = await read(file, 0, 16);
    const magic = ascii(head, 0, 4);
    if (magic.startsWith("ID3")) {
      const size = synchsafe(head, 6) + 10;
      return parseId3(await read(file, 0, size));
    }
    if (magic === "fLaC") return parseFlac(await read(file, 0, 4 * 1024 * 1024));
    if (ascii(head, 4, 4) === "ftyp") {
      let p = 0;
      while (p + 8 <= file.size) {
        const h = await read(file, p, p + 16);
        let size = u32(h, 0);
        if (size === 1) size = Number((BigInt(u32(h, 8)) << 32n) | BigInt(u32(h, 12)));
        if (size === 0) size = file.size - p;
        if (ascii(h, 4, 4) === "moov") return parseMp4Moov(await read(file, p + 8, p + Math.min(size, 64 * 1024 * 1024)));
        if (size < 8) break;
        p += size;
      }
      return {};
    }
    if (magic === "RIFF") {
      let p = 12;
      while (p + 8 <= file.size) {
        const h = await read(file, p, p + 8);
        const id = ascii(h, 0, 4);
        const len = h[4] | (h[5] << 8) | (h[6] << 16) | (h[7] << 24);
        if (id.toLowerCase() === "id3 ") return parseId3(await read(file, p + 8, p + 8 + len));
        p += 8 + len + (len & 1);
      }
    }
  } catch {
    // Damaged or unusual tags: the player falls back to the brand artwork.
  }
  return {};
}

export function artworkUrl(art: Artwork | undefined): string | null {
  if (!art) return null;
  const copy = new Uint8Array(art.bytes);
  return URL.createObjectURL(new Blob([copy.buffer], { type: art.mime }));
}
