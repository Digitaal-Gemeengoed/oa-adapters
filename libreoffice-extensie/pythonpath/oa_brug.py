# -*- coding: utf-8 -*-
"""De lokale brug tussen het webpaneel en één document in Writer.

Een kleine webserver op 127.0.0.1 (alleen deze computer). Het webpaneel,
in de browser of in de webweergave in de zijbalk, praat met de
integratielaag zoals altijd, en met het document via deze brug. De brug:

- luistert alleen op 127.0.0.1, op een willekeurige vrije poort;
- eist bij elke vraag een sleutel die alleen in het adres van het paneel
  staat (na het #-teken, dus niet naar een server gestuurd);
- antwoordt alleen aan het adres van de eigen integratielaag (CORS);
- werkt alleen met het document waarvoor hij is geopend.

Elke bewerking van het document gaat via de hoofdthread van LibreOffice
(AsyncCallback), niet vanuit de thread van de webserver.
"""

import json
import secrets
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import unohelper
from com.sun.star.awt import XCallback

import oa_bladen as ob
import oa_document as od
import oa_tekst as ot
import oa_pii as op


def _versie():
    """De versie uit description.xml van de extensie zelf."""
    import os
    import re
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "description.xml"), encoding="utf-8") as f:
            return re.search(r'<version value="([^"]+)"', f.read()).group(1)
    except Exception:
        return "onbekend"


VERSIE = _versie()


def office_versie(ctx):
    """"LibreOffice 24.2.7.2": naam en versie van het programma (Archiefregeling 2026, art. 2.8)."""
    try:
        from com.sun.star.beans import PropertyValue
        p = PropertyValue()
        p.Name, p.Value = "nodepath", "/org.openoffice.Setup/Product"
        cp = ctx.ServiceManager.createInstanceWithContext("com.sun.star.configuration.ConfigurationProvider", ctx)
        n = cp.createInstanceWithArguments("com.sun.star.configuration.ConfigurationAccess", (p,))
        return ("%s %s" % (n.getByName("ooName"), n.getByName("ooSetupVersionAboutBox"))).strip()
    except Exception:
        return None


def besturingssysteem():
    """Het besturingssysteem, zoals "Windows-11-10.0.26100-SP0" of "Linux-6.8.0-x86_64"."""
    import platform
    try:
        return platform.platform(terse=False)[:120]
    except Exception:
        return None
from oa_kern import NietUitvoerbaar


class _Hoofdthread(unohelper.Base, XCallback):
    """Voert een functie uit op de hoofdthread van LibreOffice en wacht op de uitkomst."""

    def __init__(self, ctx):
        self.async_ = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.AsyncCallback", ctx)
        self.taken = {}
        self.teller = 0
        self.slot = threading.Lock()

    def notify(self, nummer):
        # UNO geeft alleen eenvoudige waarden door; de taak zelf staat hier.
        with self.slot:
            taak = self.taken.pop(nummer, None)
        if taak:
            taak()

    def voer_uit(self, functie, tijd=30):
        uitkomst = {}
        klaar = threading.Event()

        def taak():
            try:
                uitkomst["waarde"] = functie()
            except Exception as e:  # doorgeven aan de webserver
                uitkomst["fout"] = e
            finally:
                klaar.set()

        if self.async_ is None:
            taak()
        else:
            with self.slot:
                self.teller += 1
                nummer = self.teller
                self.taken[nummer] = taak
            self.async_.addCallback(self, nummer)
            if not klaar.wait(tijd):
                raise TimeoutError("LibreOffice reageert niet.")
        if "fout" in uitkomst:
            raise uitkomst["fout"]
        return uitkomst.get("waarde")


class Brug:
    """De webserver op 127.0.0.1 voor één document."""

    def __init__(self, ctx, document, herkomst):
        self.ctx = ctx
        self.document = document
        self.herkomst = herkomst.rstrip("/")
        self.sleutel = secrets.token_urlsafe(24)
        self.hoofd = _Hoofdthread(ctx)
        # Klikken in plaatshouders en het rechtermuismenu (Writer). De brug ontstaat op de hoofdthread.
        self.klikken = None
        try:
            self.klikken = op.Klikken(document)
        except Exception:
            traceback.print_exc()
        brug = self

        class Afhandeling(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _kop(self, status, lichaam=None):
                data = json.dumps(lichaam if lichaam is not None else {}, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                if self.headers.get("Origin") == brug.herkomst:
                    self.send_header("Access-Control-Allow-Origin", brug.herkomst)
                    self.send_header("Vary", "Origin")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                if self.headers.get("Origin") != brug.herkomst:
                    self.send_response(403)
                    self.end_headers()
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", brug.herkomst)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT")
                self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Max-Age", "600")
                self.send_header("Vary", "Origin")
                self.end_headers()

            def _toegestaan(self):
                herkomst = self.headers.get("Origin")
                if herkomst is not None and herkomst != brug.herkomst:
                    return False
                kop = self.headers.get("Authorization", "")
                return secrets.compare_digest(kop, "Bearer " + brug.sleutel)

            def _lichaam(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 20 * 1024 * 1024:
                    raise ValueError("Te groot")
                return json.loads(self.rfile.read(n) or b"{}")

            def _behandel(self, methode):
                if not self._toegestaan():
                    return self._kop(401, {"fout": "geen-toegang", "melding": "Deze brug hoort bij een ander paneel."})
                try:
                    lichaam = self._lichaam() if self.command in ("POST", "PUT") else None
                except Exception:
                    return self._kop(400, {"fout": "ongeldig", "melding": "Onleesbaar verzoek."})
                return self._kop(*brug.antwoord(methode, self.path, lichaam))

            def do_GET(self):
                self._behandel("GET")

            def do_POST(self):
                self._behandel("POST")

            def do_PUT(self):
                self._behandel("PUT")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Afhandeling)
        self.poort = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="oa-brug", daemon=True)
        self.thread.start()

    def antwoord(self, methode, volledig, lichaam):
        """Eén vraag aan de brug, als (status, lichaam). Voor http en voor het kanaal van de webweergave."""
        pad = volledig.split("?", 1)[0]
        try:
            return 200, self.vraag(methode, pad, lichaam, volledig)
        except (od.Gewijzigd, ob.Gewijzigd) as e:
            return 409, {"fout": "gewijzigd", "melding": str(e)}
        except NietUitvoerbaar as e:
            return 422, {"fout": "niet-uitvoerbaar", "melding": str(e)}
        except _Onbekend:
            return 404, {"fout": "onbekend", "melding": "Deze vraag kent de brug niet."}
        except _Weg:
            return 410, {"fout": "document-weg", "melding": "Het document is gesloten. Open de assistent opnieuw vanuit LibreOffice."}
        except Exception as e:
            traceback.print_exc()
            return 500, {"fout": "intern", "melding": str(e)}

    def vraag(self, methode, pad, lichaam, volledig):
        doc = self.document
        h = self.hoofd.voer_uit
        # Bestaat het document nog? Ook dit op de hoofdthread: een UNO-aanroep
        # vanuit deze thread naast werk op de hoofdthread laat PyUNO soms de
        # eigenschappen van een nieuw object missen (AttributeError: Title).
        try:
            h(lambda: doc.getDocumentProperties())
        except TimeoutError:
            raise
        except Exception:
            raise _Weg()
        if methode == "GET" and pad == "/status":
            return {"naam": h(lambda: od.naam_van(doc)), "versie": VERSIE, "soort": h(lambda: ob.soort_van(doc)),
                    "office": h(lambda: office_versie(self.ctx)), "os": besturingssysteem()}
        # Rekenbladen en presentaties: html en herstellen op een plek (oa_bladen).
        if methode == "GET" and pad == "/html":
            return {"html": h(lambda: ob.html(doc))}
        if methode == "POST" and pad == "/segment":
            h(lambda: ob.vervang_segment(doc, lichaam["pad"], lichaam["html"]))
            return {}
        if methode == "POST" and pad == "/plek":
            h(lambda: ob.toon(doc, lichaam["pad"]))
            return {}
        if methode == "GET" and pad == "/blokken":
            return h(lambda: od.lees_blokken(doc))
        if methode == "GET" and pad == "/bestand":
            return h(lambda: od.bestand(doc))
        if methode == "GET" and pad == "/bestand-ooxml":
            return h(lambda: od.bestand(doc, ooxml=True))
        if methode == "POST" and pad == "/opdracht":
            h(lambda: od.voer_uit(doc, lichaam))
            return {}
        if methode == "POST" and pad == "/toon":
            h(lambda: od.toon(doc, lichaam))
            return {}
        if methode == "POST" and pad == "/vervang":
            h(lambda: od.vervang_alles(doc, lichaam["html"]))
            return {}
        # Anonimiseren bij de bron: vervangen door plaatshouders, en de selectie lezen.
        if methode == "POST" and pad == "/tekst-vervangen":
            return {"aantal": h(lambda: ot.vervang_tekst(doc, lichaam["paren"]))}
        if methode == "GET" and pad == "/selectie":
            return {"tekst": h(lambda: ot.lees_selectie(doc))}
        # Anonimiseren in het document (Writer): plaatshouders met bladwijzers, klikken, rechtermuismenu.
        if methode == "GET" and pad == "/pii/klik":
            # Vaak gevraagd (elke 0,7 s): alleen de eerste keer via de hoofdthread.
            if self.klikken is None:
                self.klikken = h(lambda: op.Klikken(doc))
            return self.klikken.stand() if self.klikken else {"n": 0}
        if pad.startswith("/pii"):
            # Writer: bladwijzers; Calc en Impress: de plaatshouder in de cel of het tekstvak.
            w = h(lambda: ob.soort_van(doc)) == "tekst"
            if methode == "POST" and pad == "/pii/markeer":
                return {"plekken": h(lambda: (op.markeer if w else op.markeer_bladen)(doc, lichaam["markeringen"]))}
            if methode == "GET" and pad == "/pii/plekken":
                return {"plekken": h(lambda: (op.lees_plekken if w else op.lees_plekken_bladen)(doc))}
            if methode == "POST" and pad == "/pii/herstel":
                h(lambda: (op.herstel if w else op.herstel_bladen)(doc, lichaam["plekken"]))
                return {}
            if methode == "POST" and pad == "/pii/herkleur":
                h(lambda: (op.herkleur if w else op.herkleur_bladen)(doc, lichaam["plaatshouder"], lichaam["ppl"]))
                return {}
            if methode == "POST" and pad == "/pii/definitief":
                h(lambda: (op.zet_definitief if w else op.zet_definitief_bladen)(doc))
                return {}
            if methode == "POST" and pad == "/pii/toon":
                h(lambda: (op.toon if w else op.toon_bladen)(doc, lichaam["plek"]))
                return {}
        if methode == "GET" and pad == "/eigenschappen":
            return h(lambda: od.lees_eigenschappen(doc))
        if methode == "PUT" and pad == "/standaardeigenschap":
            h(lambda: od.schrijf_standaardeigenschap(doc, lichaam["naam"], lichaam["waarde"]))
            return {}
        if pad == "/eigenschap":
            if methode == "GET":
                from urllib.parse import parse_qs, urlparse
                naam = parse_qs(urlparse(volledig).query).get("naam", [""])[0]
                return {"waarde": h(lambda: od.lees_eigenschap(doc, naam))}
            if methode == "PUT":
                h(lambda: od.schrijf_eigenschap(doc, lichaam["naam"], lichaam["waarde"]))
                return {}
        raise _Onbekend()

    def paneeladres(self):
        return "%s/libreoffice#brug=%d&sleutel=%s" % (self.herkomst, self.poort, self.sleutel)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class _Onbekend(Exception):
    pass


class _Weg(Exception):
    pass


