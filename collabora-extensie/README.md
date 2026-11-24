# Office Assistent als extensie in Collabora Online (proef)

Proef naast de gewone Collabora-pagina (`/collabora`, paneel ernaast). Hier
staat de assistent *in* Collabora: **Extensies → Office Assistent**. Ontwerp
en afwegingen: `oa-uitrol/docs/ontwerp/collabora-extensie.md`.

| Onderdeel | Waar | Wat |
|---|---|---|
| `pakket/` | in Collabora: `browser/dist/extensions/nl.digitaalgemeengoed.office-assistent/` | manifest, pictogram, `index.html`, `brug.js`, `kit.js` |
| `pakket/kit.js` | in de kit van het document (QuickJS, JS-UNO) | `oaKit(opdracht, a)`: de documentlogica van `oa_document.py`/`oa_tekst.py`, via `cool.callRemote` |
| `pakket/brug.js` | in de extensie (browser) | geeft vaste opdrachten van het paneel door aan `cool.callRemote(oaKit, …)`; gebeurtenissen terug |
| `index.html`, `main.ts` | `oa.<domein>/collabora-extensie/` | het paneel (oa-paneel) met `CollaboraKitTekstverwerker` en de gewone `StructuurAdapter` |
| `../collabora-proef/` | `oa.<domein>/collabora-proef` | werkbestand kiezen en openen, zonder paneel ernaast |

Wat de proef kan (Writer): lezen en beoordelen, herstellen op een plek (kopniveau,
kopregel van een tabel, alternatieve tekst, linktekst), tonen, selectie lezen,
tekst vervangen (anonimiseren bij de bron) en documenteigenschappen. Nog niet:
anonimiseren in het document (plaatshouders, klikken), rekenbladen en
presentaties, de taal van het document zetten, het bestand zelf vastleggen.

## Testen

`kit.js` draait in de test ook in QuickJS, met een `uno` dat via JSON aan PyUNO
doorgeeft, tegen een echte LibreOffice; de uitkomst moet gelijk zijn aan die van
de Python-extensie:

    soffice --headless --accept="socket,host=127.0.0.1,port=2002;urp;" &
    python3.12 -m pip install --break-system-packages quickjs pytest
    python3.12 -m pytest collabora-extensie/test

Wat dit niet toetst: hoe JS-UNO in Collabora zelf waarden aanbiedt. Daarom staan
eigenschappen in `kit.js` achter `getPropertyValue`/`setPropertyValue` met
terugval op `getX`/`setX` en directe toegang.

## Aanzetten (VPS 1)

Standaard aan sinds oa-uitrol 0.35.1 (`COLLABORA_EXPERIMENTEEL=true` in
`/opt/oa-uitrol/.env`; `false` zet de experimentele functies van Collabora, en
daarmee de proef, uit). Na `bijwerken.sh`:
Open `https://oa.<domein>/collabora-proef`, kies een tekstbestand en kies in
Collabora **Extensies → Office Assistent** (tabweergave: tabblad Extensies).
Meldt het paneel zich niet, dan staat in de extensie een melding met de
waarschijnlijke oorzaak; zie ook de console van de browser.
