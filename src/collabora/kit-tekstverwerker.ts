import type { Documenteigenschappen, Standaardeigenschap } from "@digitaalgemeengoed/oa-contract";
import type { Tekstverwerker } from "../structuur-adapter.js";
import { groepeer, NietUitvoerbaar, type Blok, type Doel, type Opdracht, type RuweAlinea, type Tabel } from "../semantisch.js";

/** Antwoord van oaKit (collabora-extensie/pakket/kit.js). */
type KitAntwoord = { ok: true; waarde: unknown } | { ok: false; fout: "gewijzigd" | "niet-uitvoerbaar" | "intern"; melding: string };

/**
 * Proef: Collabora Online met de Office Assistent als extensie *in* Collabora.
 * Dit paneel staat in een iframe van de extensie (collabora-extensie/pakket);
 * elke vraag gaat via postMessage naar brug.js, die haar met cool.callRemote
 * in de kit van het document uitvoert (oaKit). Zelfde vorm als de
 * LibreOffice-tekstverwerker, dus onder de gewone StructuurAdapter.
 */
export class CollaboraKitTekstverwerker implements Tekstverwerker {
  readonly id = "collabora-online-extensie";
  readonly naam = "Collabora Online (extensie, proef)";
  readonly versie = "Collabora Online";
  private volgnummer = 0;
  private readonly wachtend = new Map<number, { klaar: (w: unknown) => void; fout: (e: Error) => void }>();
  private readonly luisteraars = new Map<string, Set<() => void>>();

  constructor(
    private readonly ouder: Window,
    /** De herkomst van de extensie (de Collabora-server); alleen daarheen en daarvandaan. */
    private readonly herkomst: string,
  ) {
    window.addEventListener("message", (e) => {
      if (e.source !== this.ouder || e.origin !== this.herkomst) return;
      const b = e.data as { oa?: string; id?: number; r?: KitAntwoord; soort?: string };
      if (b?.oa === "antwoord" && typeof b.id === "number") {
        const w = this.wachtend.get(b.id);
        if (!w) return;
        this.wachtend.delete(b.id);
        const r = b.r;
        if (r?.ok) w.klaar(r.waarde);
        else if (r?.fout === "niet-uitvoerbaar") w.fout(new NietUitvoerbaar(r.melding));
        else w.fout(new Error(r?.melding ?? "Collabora gaf geen antwoord."));
      } else if (b?.oa === "gebeurtenis" && b.soort) {
        for (const f of this.luisteraars.get(b.soort) ?? []) f();
      }
    });
  }

  /** Het paneel is klaar: de extensie haalt dan haar melding weg. */
  meldKlaar(): void {
    this.ouder.postMessage({ oa: "klaar" }, this.herkomst);
  }

  /** Selectie verplaatst of document gewijzigd (cool.document.onSelectionChanged / onModified). */
  bij(soort: "selectie" | "gewijzigd", f: () => void): () => void {
    const s = this.luisteraars.get(soort) ?? new Set();
    s.add(f);
    this.luisteraars.set(soort, s);
    return () => s.delete(f);
  }

  private vraag<T>(opdracht: string, a?: unknown): Promise<T> {
    const id = ++this.volgnummer;
    return new Promise<T>((klaar, fout) => {
      const tijd = setTimeout(() => {
        this.wachtend.delete(id);
        fout(new Error("Collabora antwoordt niet. Sluit het paneel van de assistent en open het opnieuw."));
      }, 60_000);
      this.wachtend.set(id, {
        klaar: (w) => {
          clearTimeout(tijd);
          klaar(w as T);
        },
        fout: (e) => {
          clearTimeout(tijd);
          fout(e);
        },
      });
      this.ouder.postMessage({ oa: "vraag", id, opdracht, a: a ?? null }, this.herkomst);
    });
  }

  status() {
    return this.vraag<{ naam: string; soort: "tekst" | "rekenblad" | "presentatie" | "onbekend" }>("status");
  }

  async leesBlokken(): Promise<Blok[]> {
    return groepeer(await this.vraag<(RuweAlinea | Tabel)[]>("blokken"));
  }

  async voerUit(o: Opdracht): Promise<void> {
    await this.vraag("opdracht", o);
  }

  async toon(doel: Doel): Promise<void> {
    await this.vraag("toon", doel);
  }

  async vervangAlles(): Promise<void> {
    throw new NietUitvoerbaar("Het hele document vervangen kan in deze proef niet. Pas het met de hand aan.");
  }

  leesEigenschap(naam: string): Promise<string | null> {
    return this.vraag<string | null>("eigenschap", { naam });
  }

  async schrijfEigenschap(naam: string, waarde: string): Promise<void> {
    await this.vraag("schrijf-eigenschap", { naam, waarde });
  }

  schrijfDocumenteigenschap(naam: string, waarde: string): Promise<void> {
    return this.schrijfEigenschap(naam, waarde);
  }

  leesEigenschappen(): Promise<Documenteigenschappen> {
    return this.vraag<Documenteigenschappen>("eigenschappen");
  }

  async schrijfStandaardeigenschap(naam: Standaardeigenschap, waarde: string): Promise<void> {
    await this.vraag("standaardeigenschap", { naam, waarde });
  }

  vervangTekst(paren: { van: string; naar: string }[]): Promise<number> {
    return this.vraag<number>("tekst-vervangen", { paren });
  }

  leesSelectie(): Promise<string> {
    return this.vraag<string>("selectie");
  }
}

/**
 * De herkomst van de extensie, uit ?herkomst= (brug.js zet daar zijn eigen
 * adres). Alleen een https-adres op hetzelfde domein als deze pagina
 * (office.<domein> naast oa.<domein>); lokaal ook http://localhost.
 */
export function extensieHerkomst(zoek: string, hier: Location = location): string | null {
  const w = new URLSearchParams(zoek).get("herkomst");
  if (!w) return null;
  let u: URL;
  try {
    u = new URL(w);
  } catch {
    return null;
  }
  if (u.origin !== w.replace(/\/+$/, "")) return null;
  const lokaal = (h: string) => h === "localhost" || h === "127.0.0.1";
  if (lokaal(u.hostname) && lokaal(hier.hostname)) return u.origin;
  if (u.protocol !== "https:") return null;
  const domein = hier.hostname.split(".").slice(1).join(".");
  return domein.includes(".") && u.hostname.endsWith("." + domein) ? u.origin : null;
}
