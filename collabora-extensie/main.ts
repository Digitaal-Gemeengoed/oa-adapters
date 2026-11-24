import { plaatsPaneel } from "@digitaalgemeengoed/oa-paneel";
import "@digitaalgemeengoed/oa-paneel/style.css";
import { StructuurAdapter } from "../src/structuur-adapter";
import { CollaboraKitTekstverwerker, extensieHerkomst } from "../src/collabora/kit-tekstverwerker";
import { statusbalk, toonProbleem, zorgVoorInlog } from "../src/host/statusbalk";
import "../libreoffice/libreoffice.css";

/**
 * Proef: het paneel van de Office Assistent in de extensie van Collabora
 * Online. Zie collabora-extensie/pakket (de extensie zelf) en
 * oa-uitrol/docs/ontwerp/collabora-extensie.md.
 */
const meld = statusbalk(document.getElementById("status")!, "");

async function start() {
  const herkomst = extensieHerkomst(location.search);
  if (window.parent === window || !herkomst) {
    document.getElementById("uitleg")!.hidden = false;
    return;
  }
  if (!(await zorgVoorInlog())) return;
  const tv = new CollaboraKitTekstverwerker(window.parent, herkomst);
  tv.meldKlaar();
  const plek = document.getElementById("paneel")!;
  try {
    const s = await tv.status();
    if (s.soort !== "tekst") {
      toonProbleem(plek, "In deze proef werkt de assistent alleen in tekstdocumenten. Rekenbladen en presentaties: gebruik Collabora Online met het paneel ernaast.");
      return;
    }
    document.title = `${s.naam} — Office Assistent`;
  } catch (e) {
    toonProbleem(plek, `De assistent kan het document niet lezen: ${(e as Error).message}`);
    return;
  }
  plaatsPaneel(plek, new StructuurAdapter(tv, meld), { knoppen: "boven" });
}

start();
