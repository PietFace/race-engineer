"""AI-laag via de Claude API: race-updates, vragen beantwoorden, nabespreking."""
import json
import os
import threading

SYSTEM = """Je bent de race engineer van {naam}, een simracer in iRacing. Je praat via de boordradio.
Regels:
- Nederlands, kort en krachtig zoals een echte race engineer. Geen opsommingstekens, geen markdown, geen emoji.
- Je tekst wordt voorgelezen tijdens het racen: maximaal 4 korte zinnen, tenzij om een nabespreking wordt gevraagd.
- Getallen uitspreekbaar: "1,3 seconde", rondetijd als "1 32,4". Posities als "P5".
- Baseer je alleen op de data. Verzin niets. Als data ontbreekt, zeg dat kort.
- Geef bij strategie een duidelijk advies (bijv. wanneer stoppen, wel/niet zuinig rijden, undercut kans) met de reden in een paar woorden.
- Belangrijkste eerst: gevaar/actie > positie en gaps > tempo > brandstof.
- In de data staan ook incidenten (spins, van de baan, incidentpunten en de limiet). Gebruik die als het relevant is,
  bijv. herhaalde fouten in dezelfde bocht of als de coureur dicht bij de incidentlimiet zit."""


class AI:
    def __init__(self, cfg, log):
        self.cfg = cfg["ai"]
        self.log = log
        self.client = None
        key = self.cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if self.cfg.get("enabled") and key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
                log("AI actief (Claude: %s)" % self.cfg["model"])
            except Exception as e:
                log(f"AI niet beschikbaar: {e}")
        elif self.cfg.get("enabled"):
            log("Geen ANTHROPIC_API_KEY gevonden: race-updates worden regel-gebaseerd.")
        self.busy = False
        naam = (cfg.get("driver", {}) or {}).get("name") or "de coureur"
        self.system = SYSTEM.replace("{naam}", naam)

    @property
    def available(self):
        return self.client is not None

    def _ask(self, prompt, max_tokens=300):
        msg = self.client.messages.create(
            model=self.cfg["model"], max_tokens=max_tokens, system=self.system,
            messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    def run_async(self, fn, callback, fallback=None):
        """Voer AI-aanroep uit op de achtergrond zodat de telemetrie doorloopt."""
        if not self.available:
            if fallback:
                callback(fallback())
            return
        if self.busy:
            return

        def worker():
            self.busy = True
            try:
                callback(fn())
            except Exception as e:
                self.log(f"AI-fout: {e}")
                if fallback:
                    callback(fallback())
            finally:
                self.busy = False
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------
    def race_update(self, snapshot):
        return self._ask("Geef een volledige race-update op basis van deze data. Noem positie, de auto voor en achter "
                         "(gap en trend), je tempo vergeleken met hen, en het strategie-advies.\n\n"
                         + json.dumps(snapshot, ensure_ascii=False))

    def answer(self, question, snapshot):
        return self._ask(f"De coureur vraagt via de radio: \"{question}\"\nBeantwoord kort op basis van deze data:\n\n"
                         + json.dumps(snapshot, ensure_ascii=False))

    def setup_advice(self, snapshot):
        return self._ask("De coureur vraagt om setup-advies. Gebruik 'auto_balans' (onder/overstuur per bocht en fase), "
                         "de auto en de baan. Noem het belangrijkste probleem en maximaal twee concrete setup-wijzigingen "
                         "die in deze auto in iRacing instelbaar zijn, plus één rijtechniek-tip. Wees eerlijk als de data "
                         "te dun is. Maximaal 5 zinnen.\n\n" + json.dumps(snapshot, ensure_ascii=False), max_tokens=400)

    def debrief(self, snapshot, laps_log):
        return self._ask("De race is voorbij. Schrijf een nabespreking van maximaal 12 zinnen: resultaat, tempo-ontwikkeling, "
                         "gevechten, strategie, en 3 concrete verbeterpunten (gebruik de coaching-data per bocht). "
                         "Data:\n\n" + json.dumps({"eind": snapshot, "ronden": laps_log}, ensure_ascii=False),
                         max_tokens=900)
