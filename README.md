# calendarios-baloncesto

Calendarios de partidos de baloncesto en formato ICS, para suscribirse desde el móvil o Google Calendar,
actualizados automáticamente dos veces al día. También exporta CSV y JSON.

## Calendarios publicados

| Calendario | URL de suscripción |
|---|---|
| Cultural y Deportiva Leonesa, en casa (aviso 3 h antes) | `https://devlarosa.github.io/calendarios-baloncesto/leonesa_casa.ics` |
| Cultural y Deportiva Leonesa, fuera | `https://devlarosa.github.io/calendarios-baloncesto/leonesa_fuera.ics` |
| Real Madrid (Liga Endesa, Copa del Rey, Supercopa y Euroliga) | `https://devlarosa.github.io/calendarios-baloncesto/real_madrid.ics` |

## Fuentes

| Fuente | Módulo | Competiciones | Cómo se obtiene |
|---|---|---|---|
| `feb` | `calendarios/feb.py` | Primera, Segunda y Tercera FEB, ligas femeninas… | HTML de feb.es (calendario + ficha de cada partido) |
| `acb` | `calendarios/acb.py` | Liga Endesa, Copa del Rey, Supercopa | Datos incrustados en las páginas de calendario de acb.com |
| `euroliga` | `calendarios/euroliga.py` | Euroliga (todas las fases) | API pública `api-live.euroleague.net` |

## Uso

```bash
pip install -r requirements.txt
python calendario.py                               # todos los calendarios -> ./salida (CSV, JSON, ICS)
python calendario.py real_madrid                   # solo uno
python calendario.py --temporada 2025              # otra temporada
python calendario.py --formatos ics --salida docs  # lo que hace la tarea programada
```

## Añadir un calendario

Edita `calendarios.json`:

```json
{
  "archivo": "valencia",
  "nombre": "Valencia Basket",
  "solo": "casa",
  "aviso": 120,
  "fuentes": [
    {"fuente": "acb", "equipo": "Valencia Basket"},
    {"fuente": "euroliga", "equipo": "PAM"}
  ]
}
```

- `equipo`: en FEB y ACB, el nombre o parte de él tal como aparece en su web (en FEB también vale el ID numérico); en la Euroliga, el código de club (`MAD`, `BAR`, `PAM`…).
- `liga` (solo FEB): 1 Primera FEB, 2 Segunda FEB, 3 Tercera FEB, 4 LF Endesa, 9 LF2, 67 LF Challenge.
- `solo` (opcional): `casa` o `fuera`. `aviso` (opcional): minutos de antelación del recordatorio.

La tarea `.github/workflows/calendario.yml` genera todos los calendarios en `docs/` y GitHub Pages los publica.
