"""Fuente: Wherevents (wherevents.com) — torneos y ligas locales que publica la app Wherevents.

La ficha de cada equipo (https://wherevents.com/equipo/<id>) lleva sus próximos partidos en JSON-LD
(schema.org SportsEvent: fecha, pabellón y enlace al partido) y, en el HTML, el torneo y la jornada.
Como la ficha solo enseña los partidos que faltan por jugar, lo encontrado se guarda en estado/ para
no perder los ya jugados."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from .modelo import MADRID, Partido, incluir, norm, sesion

BASE = "https://wherevents.com"
REGISTROS = Path(__file__).resolve().parent.parent / "estado"


class Wherevents:
    def __init__(self):
        self.s = sesion()

    def partidos(self, equipo: str | int, temporada: int, solo: str | None = None) -> list[Partido]:
        """equipo: ID numérico de la ficha del equipo (el número de https://wherevents.com/equipo/<id>)."""
        eid = int(equipo)
        ruta = REGISTROS / f"wherevents_equipo_{eid}.json"
        guardados = {p["id"]: Partido(**p) for p in
                     (json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else [])}
        try:
            actuales = {p.id: p for p in self._ficha(eid, temporada)}
        except Exception as e:  # la web no responde: se tira de lo guardado
            print(f"Aviso: Wherevents equipo {eid} no responde ({e}); se usa solo {ruta.name}.", file=sys.stderr)
            actuales = None

        if actuales is not None:
            hoy = datetime.now(MADRID).date().isoformat()
            # Se conservan los guardados ya pasados; uno futuro que desaparece de la ficha se ha anulado
            todos = {i: p for i, p in guardados.items() if i not in actuales and (p.fecha or "")[:10] < hoy}
            todos.update(actuales)
            if todos != guardados:
                ruta.parent.mkdir(parents=True, exist_ok=True)
                datos = [asdict(p) for p in sorted(todos.values(), key=lambda p: (p.fecha or "", p.id))]
                ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            todos = guardados

        inicio = date(temporada, 8, 1).isoformat()
        fin = date(temporada + 1, 8, 1).isoformat()
        return [p for p in todos.values() if inicio <= (p.fecha or "")[:10] < fin
                and incluir(p.condicion == "Local", solo)]

    def _ficha(self, eid: int, temporada: int) -> list[Partido]:
        r = self.s.get(f"{BASE}/equipo/{eid}", timeout=30)
        r.raise_for_status()
        sopa = BeautifulSoup(r.text, "html.parser")
        ld = None
        for t in sopa.find_all("script", type="application/ld+json"):
            datos = json.loads(t.string or "{}")
            if datos.get("@type") == "SportsTeam":
                ld = datos
                break
        if ld is None:
            raise ValueError("la ficha no trae los datos del equipo (JSON-LD SportsTeam)")
        nombre = ld["name"]

        out = []
        for ev in ld.get("event", []):
            url = ev["url"]
            m = re.search(r"/torneo/(\d+)#partido-(\d+)$", url)
            if not m:
                continue
            torneo_id, pid = int(m.group(1)), int(m.group(2))
            local, visitante, torneo, jornada = self._tarjeta(sopa, url) or (None, None, "", "")
            if not local:  # sin tarjeta en el HTML: el nombre del evento es "Local - Visitante"
                local, _, visitante = ev.get("name", "").partition(" - ")
            es_local = norm(local) == norm(nombre)
            fecha = ev.get("startDate") or ""
            if "T" in fecha:
                fecha = datetime.fromisoformat(fecha).replace(tzinfo=MADRID).isoformat()
            out.append(Partido(
                id=pid, temporada=f"{temporada}/{temporada + 1}", competicion=nombre, grupo=torneo,
                jornada=jornada, fecha=fecha or None,
                local=local, local_id=eid if es_local else None,
                visitante=visitante, visitante_id=None if es_local else eid,
                puntos_local=None, puntos_visitante=None, jugado=False,
                condicion="Local" if es_local else "Visitante",
                rival=visitante if es_local else local, resultado="",
                pabellon=(ev.get("location") or {}).get("name", ""),
                url=f"{BASE}/torneo/{torneo_id}#partido-{pid}",
                uid=f"wherevents-partido-{pid}@wherevents.com",
            ))
        return out

    @staticmethod
    def _tarjeta(sopa: BeautifulSoup, url: str) -> tuple[str, str, str, str] | None:
        """(local, visitante, torneo, jornada) de la tarjeta del partido en el HTML de la ficha."""
        a = sopa.find("a", href=url.removeprefix(BASE))
        if not a:
            return None
        equipos = [s.get_text(strip=True) for s in a.select("span.truncate.text-sm")]
        pie = a.select("span.block.truncate")
        torneo, _, jornada = (pie[-1].get_text(strip=True) if pie else "").rpartition(" · ")
        if not torneo:  # sin " · ": todo es el torneo
            torneo, jornada = jornada, ""
        return (equipos[0], equipos[1], torneo, jornada) if len(equipos) == 2 else None
