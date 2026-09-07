import { useUi } from "@/stores/ui";

/**
 * A short bell for the moment the application starts waiting on the person.
 *
 * Synthesised rather than shipped: an interview can sit for minutes while a model thinks, and the
 * person is very reasonably doing something else in another window. A sound is the only channel that
 * reaches them there — but it is a courtesy, never the message. The question is always on screen too,
 * and nothing here is allowed to throw.
 *
 * No audio file means nothing to download, nothing to cache and nothing that breaks offline; two
 * struck sine tones with a bell-like inharmonic partial are enough to be recognisable and short.
 */

let shared: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  // One context for the life of the tab: browsers cap how many a page may open.
  if (!shared) shared = new Ctor();
  return shared;
}

const PEAK = 0.14; // quiet enough to live with all day
const DECAY_S = 0.9;
// B5 then E6, a rising fourth: short, unmistakable, and not the sound of an error.
const STRIKES: { after: number; hz: number }[] = [
  { after: 0, hz: 987.77 },
  { after: 0.13, hz: 1318.51 },
];

function strike(audio: AudioContext, at: number, hz: number): void {
  // The 2.76 partial is what stops a sine sounding like a test tone and starts it sounding struck.
  for (const [ratio, level] of [
    [1, 1],
    [2.76, 0.3],
  ] as const) {
    const osc = audio.createOscillator();
    const envelope = audio.createGain();
    osc.type = "sine";
    osc.frequency.value = hz * ratio;
    envelope.gain.setValueAtTime(0.0001, at);
    envelope.gain.linearRampToValueAtTime(PEAK * level, at + 0.008);
    envelope.gain.exponentialRampToValueAtTime(0.0001, at + DECAY_S);
    osc.connect(envelope).connect(audio.destination);
    osc.start(at);
    osc.stop(at + DECAY_S + 0.05);
  }
}

/** Ring, unless the person has turned the sound off. Silent on any failure, by design. */
export function alertChime(): void {
  if (!useUi.getState().soundOn) return;
  const audio = audioContext();
  if (!audio) return;
  try {
    // Until the page has been interacted with, browsers keep the context suspended. Resuming is a
    // promise that may simply be rejected, and that is a fine outcome: no sound, no error, no fuss.
    if (audio.state === "suspended") void audio.resume().catch(() => undefined);
    const start = audio.currentTime + 0.02;
    for (const s of STRIKES) strike(audio, start + s.after, s.hz);
  } catch {
    /* a sound is never worth an exception */
  }
}
