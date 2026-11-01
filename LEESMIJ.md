# AI Race Engineer voor iRacing

Een race engineer die via je headset met je praat terwijl je rijdt, in een eigen programma.

## Zelf online zetten als download

Alles staat klaar om via GitHub een echte installer (`RaceEngineer-Setup.exe`) en een downloadpagina te maken:
`.github/workflows/release.yml` (bouwknop), `installer/` (installer), `docs/` (downloadpagina).
Volg het stappenplan *AI Race Engineer – stappenplan downloadbaar programma*.

## Installeren op je eigen pc zonder GitHub (±5 minuten)

1. Installeer **Python** via python.org/downloads en vink *Add python.exe to PATH* aan.
   (Alleen nodig om het programma één keer te bouwen.)
2. Pak deze zip uit en dubbelklik **installeren.bat**.
3. Klaar: **AI Race Engineer** staat op je bureaublad en in het Startmenu. De uitgepakte map mag weg.

## Gebruiken

Open het programma vóór of tijdens iRacing. De engineer start vanzelf en meldt zich zodra je in de auto zit.
Met **Testrace** en **Testtraining** probeer je alles uit zonder iRacing.

- **Race**: positie, ronde, laptijden, de auto voor en achter je (gap + trend), brandstof en strategie,
  coaching per bocht, en alles wat de engineer zegt.
- **Instellingen**: stem, API-sleutel, hoeveel hij praat, coaching.
- **Knoppen**: toetsen en stuurknoppen koppelen (klik *Stuurknop toewijzen* en druk op je stuur).

## Tijdens de race

- **Spotter**: "Links", "Rechts", "Drie breed, jij in het midden", "Vrij". Vooraf ingesproken, dus zonder vertraging.
  Terwijl er iemand naast je zit, wacht de rest van de engineer even.
- **Tegenstander per bocht** (ook met F6): "Jansen is sneller in bocht 5 en 6. Jij bent sneller in bocht 2.
  Je beste kans: blijf dicht achter hem uit bocht 2 en val aan in bocht 3."

- **Pitstop klaarzetten**: zodra het pitvenster open is zet hij de juiste hoeveelheid brandstof en de banden klaar
  in iRacing. Na zwaar contact (4x) zet hij fast repair klaar.
- **Andere klassen**: "GTP komt eraan, 3 seconde. Laat ruimte."
- **Vlaggen en safety car**: gele, blauwe en zwarte vlag; bij een safety car advies of je moet stoppen, en
  "Pits zijn open. Box, box deze ronde."
- **Tegenstanders**: iRating, licentie en waarschuwing als iemand al veel incidenten heeft.
- **iRating-voorspelling**: "Als je zo finisht: plus 38 iRating" (schatting volgens de bekende formule).
- **Baan en weer**: baantemperatuur, regen, natte baan, nat verklaard. (iRacing geeft nattigheid voor de hele baan,
  niet per sector.)

## Training

- **Setup**: hij leest je echte setup uit. Advies met jouw waarden ("rembalans naar 53,5 procent, nu 54,0").
  Pas je de setup aan in de garage, dan meldt hij de wijziging en vertelt hij na een paar ronden of het geholpen heeft.

- **Nieuwe baan leren**: na je eerste schone ronde zegt hij vóór elke bocht hoe hard je remt, in welke versnelling
  en hoe snel je door de top gaat.
- **Onder- en overstuur per bocht**, met een setup- en rijtechniek-tip. Met F7 (Setup-advies) en een API-sleutel
  krijg je advies dat past bij jouw auto.
- **Analyse**: rem-, gas- en snelheidslijnen per bocht, jouw ronde tegen je beste ronde, en een balanstabel.

## Tweede scherm

Open *Tweede scherm* in het programma en scan de QR-code met je telefoon of iPad (zelfde wifi).
Je ziet live je positie, gaps, brandstof, vlaggen en de boordradio. Werkt ook op een andere pc.

## Spins en incidenten

- **Spin**: hij herkent het meteen ("Spin. Rem vast, ik kijk naar het verkeer"), waarschuwt voor naderende auto's
  ("Wacht! Bos komt nu langs, Kok erachter") en zegt wanneer het veilig is ("Vrij. Je kunt gaan").
- **Daarna**: hoeveel plekken en tijd je kwijt bent, en aan wie.
- **Van de baan / incidentpunten**: "1x, vier wielen eraf in bocht 3. Totaal 3x."
- **Incidentlimiet**: waarschuwing als je de limiet van de sessie nadert.
- **Patronen**: spin je vaker in dezelfde bocht, dan zegt hij dat (en het komt in de nabespreking).

## AI-sleutel (optioneel)

Klik bij Instellingen op *Sleutel maken*, maak een sleutel op console.anthropic.com en plak hem in het veld.
Daarmee krijg je slimme race-updates, een nabespreking na de race en kun je vragen stellen via je microfoon.
Zonder sleutel werkt al het andere ook.

## Goed om te weten

- Bandenslijtage geeft iRacing niet live door, dus daar kan hij niets over zeggen.
- De coaching begint na je eerste schone ronde en onthoudt je beste ronde per baan + auto.
- Werken de sneltoetsen niet terwijl iRacing op de voorgrond staat? Start het programma dan als administrator.
- Logs en nabesprekingen: Instellingen → *Open map met logs*.
- Bijwerken naar een nieuwe versie: nieuwe zip uitpakken en opnieuw installeren.bat. Je instellingen blijven bewaard.
