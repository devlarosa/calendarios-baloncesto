# feb_scrap

Scraper del calendario y resultados de un equipo en las competiciones de la FEB (feb.es).
Por defecto: **Cultural y Deportiva Leonesa** (ID FEB `1008857`) en **Segunda FEB**, temporada actual.

```bash
pip install -r requirements.txt
python feb_scraper.py                      # CSV + JSON + ICS en ./salida
python feb_scraper.py --temporada 2025     # temporada 2025/2026
python feb_scraper.py --equipo ponferrada  # otro equipo (texto del nombre o ID FEB)
python feb_scraper.py --liga 1 --equipo 1009588 --formatos ics
python feb_scraper.py --solo-casa --aviso 180 --formatos ics   # solo partidos en casa, aviso 3 h antes
python feb_scraper.py --solo-fuera --formatos ics              # solo partidos de visitante
python feb_scraper.py --sin-detalles       # más rápido: sin hora exacta de partidos jugados ni pabellón
```

Ligas (`--liga`): 1 Primera FEB, 2 Segunda FEB, 3 Tercera FEB, 4 LF Endesa, 9 LF2, 67 LF Challenge, 73 Copa España, 74 Liga U.

- **CSV** separado por `;` y en UTF-8 con BOM (se abre bien en Excel).
- **ICS** se importa en Google Calendar / Outlook / Apple Calendar; los partidos jugados llevan el marcador en el título.
- Fuente: `calendario.aspx?g=<liga>&t=<temporada>` (temporada y grupo se cambian enviando el formulario ASP.NET) y `Partido.aspx?p=<id>` para fecha/hora exacta y pabellón.
