/*
 * De brug tussen het paneel van de Office Assistent (op oa.<domein>, in een
 * iframe hieronder) en het document in Collabora Online (via cool.js).
 *
 * - Het paneel staat op het adres van de integratielaag: inloggen, code en
 *   versies blijven daar. Het adres komt uit instellingen.json naast dit
 *   bestand, of volgt uit het eigen adres (office.<domein> → oa.<domein>).
 * - Het paneel vraagt via postMessage een vaste opdracht ("blokken",
 *   "opdracht" …); de brug voert die uit met cool.callRemote(oaKit, …) in de
 *   kit van het document. Geen vrije code uit het paneel: alleen oaKit, en
 *   alleen berichten van het paneel zelf (bron en herkomst).
 * - Gebeurtenissen van het document (selectie, gewijzigd) gaan naar het paneel.
 */
(function () {
  "use strict";
  var TOEGESTAAN = ["status", "blokken", "opdracht", "toon", "eigenschap", "schrijf-eigenschap", "eigenschappen", "standaardeigenschap", "tekst-vervangen", "selectie"];
  var melding = document.getElementById("melding");
  var paneel = document.getElementById("paneel");
  var paneelHerkomst = null;
  var klaar = false;

  function meld(html) {
    melding.innerHTML = html;
    melding.hidden = false;
  }

  function naarPaneel(bericht) {
    if (paneel.contentWindow && paneelHerkomst) paneel.contentWindow.postMessage(bericht, paneelHerkomst);
  }

  function basisAdres() {
    return fetch("instellingen.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (i) {
        if (i && typeof i.basis === "string" && /^https?:\/\//.test(i.basis)) return i.basis.replace(/\/+$/, "");
        // office.voorbeeld.nl → oa.voorbeeld.nl
        var u = new URL(location.href);
        if (/^office\./.test(u.hostname)) return u.protocol + "//" + u.hostname.replace(/^office\./, "oa.") + (u.port ? ":" + u.port : "");
        return null;
      });
  }

  function voerUit(opdracht, a) {
    if (typeof cool === "undefined" || typeof cool.callRemote !== "function")
      return Promise.resolve({ ok: false, fout: "intern", melding: "cool.js ontbreekt: staan de extensies van Collabora aan (experimental_features)?" });
    return Promise.resolve(cool.callRemote(oaKit, opdracht, a === undefined ? null : a)).then(
      function (r) { return r && typeof r === "object" && "ok" in r ? r : { ok: true, waarde: r }; },
      function (e) { return { ok: false, fout: "intern", melding: String((e && e.message) || e) }; }
    );
  }

  window.addEventListener("message", function (e) {
    if (e.source !== paneel.contentWindow || e.origin !== paneelHerkomst) return;
    var b = e.data;
    if (!b || typeof b !== "object") return;
    if (b.oa === "klaar") {
      klaar = true;
      melding.hidden = true;
      return;
    }
    if (b.oa !== "vraag" || typeof b.id !== "number") return;
    if (TOEGESTAAN.indexOf(b.opdracht) < 0) {
      naarPaneel({ oa: "antwoord", id: b.id, r: { ok: false, fout: "niet-uitvoerbaar", melding: "Onbekende vraag." } });
      return;
    }
    voerUit(b.opdracht, b.a).then(function (r) { naarPaneel({ oa: "antwoord", id: b.id, r: r }); });
  });

  function luister() {
    try {
      cool.document.onSelectionChanged = function () { naarPaneel({ oa: "gebeurtenis", soort: "selectie" }); };
      cool.document.onModified = function () { naarPaneel({ oa: "gebeurtenis", soort: "gewijzigd" }); };
    } catch (e) {
      /* oudere cool.js: dan zonder gebeurtenissen */
    }
  }

  basisAdres().then(function (basis) {
    if (!basis) {
      meld("Het adres van de Office Assistent is niet bekend. Zet <code>instellingen.json</code> met <code>{\"basis\": \"https://oa.&lt;domein&gt;\"}</code> naast deze extensie.");
      return;
    }
    paneelHerkomst = new URL(basis).origin;
    paneel.src = basis + "/collabora-extensie?herkomst=" + encodeURIComponent(location.origin);
    paneel.hidden = false;
    luister();
    setTimeout(function () {
      if (klaar) return;
      meld(
        "Het paneel van de Office Assistent meldt zich niet. Mogelijke oorzaken: je bent niet ingelogd op " +
          paneelHerkomst + ", of Collabora staat een pagina van dat adres hier niet toe (Content-Security-Policy, <code>frame-src</code>). " +
          "Zie de console van de browser."
      );
    }, 20000);
  });
})();
