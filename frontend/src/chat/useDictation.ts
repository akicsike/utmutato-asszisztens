// Diktálás a böngésző beépített beszédfelismerésével (Web Speech API – Chrome, Edge), a demo projekt
// DoksiChat.Dictation osztályának React-hook változata. A Chrome a hangot a Google, az Edge a Microsoft
// szerverén ismeri fel; a mikrofon csak biztonságos oldalon (https:// vagy localhost) engedélyezhető.
import { useCallback, useEffect, useRef, useState } from "react";

// A TypeScript DOM-típusai nem tartalmazzák a Web Speech API-t – a szükséges rész:
interface RecognitionResult { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

const ERRORS: Record<string, string> = {
  "not-allowed": "A mikrofon nincs engedélyezve. Engedélyezd a böngésző címsorában a mikrofon ikonnál.",
  "service-not-allowed": "A böngésző ezen az oldalon nem engedi a beszédfelismerést (https vagy localhost kell).",
  "audio-capture": "Nem található mikrofon.",
  network: "A beszédfelismerő szolgáltatás nem érhető el (hálózati hiba).",
  "no-speech": "Nem hallottam beszédet, próbáld újra.",
  "language-not-supported": "A böngésző nem támogatja a magyar beszédfelismerést.",
};

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

interface Options {
  /** a beviteli mező teljes új szövege: a diktálás előtti szöveg + a felismert (végleges + köztes) szöveg */
  onText: (text: string) => void;
  onError: (message: string) => void;
  lang?: string;
}

export function useDictation({ onText, onError, lang = "hu-HU" }: Options) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<Recognition | null>(null);
  const baseRef = useRef("");
  const abortedRef = useRef(false);
  const cb = useRef({ onText, onError });
  cb.current = { onText, onError };
  const supported = recognitionCtor() !== null;

  const start = useCallback((currentText: string) => {
    const Ctor = recognitionCtor();
    if (!Ctor) return cb.current.onError("Ez a böngésző nem támogatja a diktálást (Chrome vagy Edge kell).");
    if (window.isSecureContext === false)
      return cb.current.onError("A diktáláshoz biztonságos kapcsolat kell: https:// vagy localhost.");

    // a már beírt szöveg után folytatja (szóközzel elválasztva)
    baseRef.current = currentText && !/\s$/.test(currentText) ? `${currentText} ` : currentText;
    abortedRef.current = false;
    let finalText = "";

    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;      // a szünetek után is figyel, amíg le nem állítják
    rec.interimResults = true;  // a köztes (még javuló) szöveg is megjelenik gépelés közben
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      if (!abortedRef.current) cb.current.onText(baseRef.current + finalText + interim);
    };
    rec.onerror = (e) => {
      if (e.error !== "aborted") cb.current.onError(ERRORS[e.error] ?? `Diktálási hiba: ${e.error}`);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      if (!abortedRef.current) cb.current.onText(baseRef.current + finalText);
    };
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch (err) {
      recRef.current = null;
      cb.current.onError(`A diktálás nem indítható: ${(err as Error).message}`);
    }
  }, [lang]);

  const stop = useCallback(() => recRef.current?.stop(), []);

  /** Küldéskor: azonnal leállít, és a későbbi (késve érkező) felismert szöveg már nem írja vissza a mezőt. */
  const abort = useCallback(() => {
    abortedRef.current = true;
    recRef.current?.abort();
  }, []);

  const toggle = useCallback((currentText: string) => {
    if (recRef.current) stop();
    else start(currentText);
  }, [start, stop]);

  useEffect(() => () => recRef.current?.abort(), []);

  return { supported, listening, toggle, stop, abort };
}
