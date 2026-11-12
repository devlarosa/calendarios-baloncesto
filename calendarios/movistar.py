"""Guía de TV de Movistar Plus+ (movistarplus.es/programacion-tv/<canal>/<fecha>).

La guía solo cubre unos pocos días alrededor de hoy, así que quien la use debe guardar lo que encuentre
(ver Euroliga con la opción 'canal')."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html import unescape

from .modelo import MADRID, sesion

GUIA = "https://www.movistarplus.es/programacion-tv/{canal}/{fecha}"
# código de la URL -> nombre visible
CANALES = {"vamosd": "M+ Vamos", "vam2sd": "M+ Vamos 2", "mplus": "Movistar Plus+", "mbalct": "M+ Baloncesto"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

_ENTRADA = re.compile(r'<div id="ele-\d+" class="container_box[^"]*">\s*<a href="([^"]*)">.*?'
                      r'class="title">([^<]*)</li>.*?class="time">\s*(\d{1,2}):(\d{2})', re.S)
_TITULO_DIA = re.compile(r"<title>Programación TV de .*? (\d{1,2}) de (\w+) \|")


@dataclass
class Emision:
    inicio: datetime   # hora de Madrid
    titulo: str
    url: str


def nombre_canal(canal: str) -> str:
    return CANALES.get(canal, canal)


def guia(canal: str, dias_antes: int = 5, dias_despues: int = 8) -> tuple[list[Emision], set[date]]:
    """Programas del canal en los días que publica la guía. Devuelve también qué días se han leído.

    Para un día fuera de su rango la web devuelve la guía de hoy; esos días se descartan."""
    s = sesion()
    hoy = datetime.now(MADRID).date()
    emisiones, leidos = [], set()
    for n in range(-dias_antes, dias_despues + 1):
        dia = hoy + timedelta(days=n)
        try:
            r = s.get(GUIA.format(canal=canal, fecha=dia.isoformat()), timeout=30)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 - un día que falla no debe tirar el calendario
            print(f"Aviso: no se pudo leer la guía de {canal} del {dia}: {e}", file=sys.stderr)
            continue
        m = _TITULO_DIA.search(r.text)
        if not m or int(m[1]) != dia.day or m[2].lower() != MESES[dia.month - 1]:
            continue
        leidos.add(dia)
        actual, previa = dia, None
        for url, titulo, hh, mm in _ENTRADA.findall(r.text):
            hora = (int(hh), int(mm))
            if previa is not None and hora < previa:  # la parrilla pasa de medianoche
                actual += timedelta(days=1)
            previa = hora
            inicio = datetime(actual.year, actual.month, actual.day, *hora, tzinfo=MADRID)
            emisiones.append(Emision(inicio, unescape(titulo).strip(), unescape(url)))
    return emisiones, leidos
