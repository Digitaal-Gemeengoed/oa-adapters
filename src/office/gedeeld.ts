/// <reference types="office-js" />
import type { Afdruk, Documenteigenschappen, Inhoud, Standaardeigenschap } from "@digitaalgemeengoed/oa-contract";

/**
 * Wat Word, Excel en PowerPoint delen: het bestand opleveren, de afdruk in
 * het bestand, en de html van een rekenblad of presentatie (dezelfde vorm
 * als de LibreOffice-extensie en Collabora: secties per blad of dia).
 */

/** Het bestand zoals Office het bewaart (docx, xlsx, pptx), in stukken gelezen. */
export function leesOfficeBestand(formaat: "docx" | "xlsx" | "pptx", mediaType: string, app: string): Promise<Inhoud> {
  return new Promise((klaar, mis) => {
    Office.context.document.getFileAsync(Office.FileType.Compressed, { sliceSize: 4 * 1024 * 1024 }, (r) => {
      if (r.status !== Office.AsyncResultStatus.Succeeded) return mis(new Error(`${app} kon het bestand niet opleveren: ${r.error.message}`));
      const bestand = r.value;
      const stukken: Uint8Array[] = [];
      const lees = (i: number) =>
        bestand.getSliceAsync(i, (s) => {
          if (s.status !== Office.AsyncResultStatus.Succeeded) {
            bestand.closeAsync();
            return mis(new Error(`${app} kon het bestand niet opleveren: ${s.error.message}`));
          }
          stukken.push(new Uint8Array(s.value.data as number[]));
          if (i + 1 < bestand.sliceCount) return lees(i + 1);
          bestand.closeAsync();
          klaar({ formaat, mediaType, codering: "base64", data: naarBase64(stukken) });
        });
      lees(0);
    });
  });
}

export function naarBase64(stukken: Uint8Array[]): string {
  let binair = "";
  for (const s of stukken) for (let i = 0; i < s.length; i += 0x8000) binair += String.fromCharCode(...s.subarray(i, i + 0x8000));
  return btoa(binair);
}

const AFDRUK = "oa-afdruk";

/**
 * De afdruk in de instellingen van de invoegtoepassing: Office bewaart die
 * in het bestand zelf (Excel, PowerPoint en Word), dus het stuk blijft
 * herkenbaar als het het platform verlaat.
 */
export async function schrijfAfdrukInBestand(afdruk: Afdruk): Promise<void> {
  Office.context.document.settings.set(AFDRUK, JSON.stringify(afdruk));
  await new Promise<void>((klaar, mis) =>
    Office.context.document.settings.saveAsync((r) => (r.status === Office.AsyncResultStatus.Succeeded ? klaar() : mis(new Error(r.error.message)))),
  );
}

export async function leesAfdrukUitBestand(): Promise<Afdruk | null> {
  const w = Office.context.document.settings.get(AFDRUK) as string | null;
  if (!w) return null;
  try {
    return JSON.parse(w) as Afdruk;
  } catch {
    return null;
  }
}

export const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escAttr = (s: string) => esc(s).replace(/"/g, "&quot;");

export function img(alt: string | null | undefined, grafiek = false): string {
  const extra = grafiek ? ' data-oa="grafiek"' : "";
  return alt ? `<img${extra} alt="${escAttr(alt)}">` : `<img${extra}>`;
}

/** Het eerste element van een stukje html: genoeg om een herstelling te lezen. */
export function eersteElement(html: string): { tag: string; attrs: Record<string, string>; tekst: string } | null {
  const doc = new DOMParser().parseFromString(`<!doctype html><html><body><template>${html}</template></body></html>`, "text/html");
  const t = doc.querySelector("template");
  const e = (t as HTMLTemplateElement | null)?.content?.firstElementChild ?? t?.firstElementChild;
  if (!e) return null;
  const attrs: Record<string, string> = {};
  for (const a of Array.from(e.attributes)) attrs[a.name] = a.value;
  return { tag: e.tagName.toLowerCase(), attrs, tekst: (e.textContent ?? "").replace(/\s+/g, " ").trim() };
}

export function padDelen(pad: string): number[] {
  const d = pad.split("/");
  if (d[0] !== "body") throw new Error(`Onbekend pad: ${pad}`);
  return d.slice(1).map(Number);
}

export const NIET_GEVONDEN = "Dit deel van het document is niet meer gevonden. Beoordeel opnieuw.";
export const HANDMATIG = "Deze wijziging kan hier nog niet automatisch. Pas het met de hand aan.";

// ---------------------------------------------------------------------------
// Documenteigenschappen (Excel en PowerPoint; Word heeft dezelfde velden)
// ---------------------------------------------------------------------------

/** Welk veld van Office.js bij een standaardeigenschap hoort. Taal en status kent Office.js niet. */
export const OFFICE_VELD: Partial<Record<Standaardeigenschap, "title" | "subject" | "keywords" | "author" | "comments" | "category">> = {
  titel: "title",
  onderwerp: "subject",
  trefwoorden: "keywords",
  auteur: "author",
  omschrijving: "comments",
  categorie: "category",
};

/** Taal en status kent Office.js niet als eigenschap: die gaan als eigen eigenschap mee (zoals in LibreOffice categorie en status). */
export const ALS_EIGEN: Partial<Record<Standaardeigenschap, string>> = { taal: "Taal", status: "Status" };

/** De standaardeigenschappen en de eigen eigenschappen (zonder die van de assistent zelf, zoals oa-afdruk). */
export function gedeeldeEigenschappen(
  p: { title?: string; subject?: string; keywords?: string; author?: string; comments?: string; category?: string },
  eigen: { key: string; value: unknown }[],
): Documenteigenschappen {
  const standaard: Documenteigenschappen["standaard"] = {};
  for (const [naam, veld] of Object.entries(OFFICE_VELD) as [Standaardeigenschap, keyof typeof p][]) {
    const w = p[veld];
    if (typeof w === "string" && w.trim()) standaard[naam] = w.trim();
  }
  const eigenWaarden: Record<string, string> = Object.fromEntries(eigen.filter((e) => !e.key.startsWith("oa-")).map((e) => [e.key, String(e.value)]));
  for (const [naam, label] of Object.entries(ALS_EIGEN) as [Standaardeigenschap, string][]) {
    if (eigenWaarden[label]?.trim()) standaard[naam] = eigenWaarden[label]!.trim();
  }
  return { standaard, eigen: eigenWaarden };
}
