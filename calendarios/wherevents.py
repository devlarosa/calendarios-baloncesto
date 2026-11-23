"""Fuente: Wherevents (wherevents.com) — torneos y ligas locales que publica la app Wherevents.

La ficha de cada equipo (https://wherevents.com/equipo/<id>) lleva sus próximos partidos en JSON-LD
(schema.org SportsEvent: fecha, pabellón y enlace al partido) y, en el HTML, el torneo y la jornada.
Como la ficha solo enseña los partidos que faltan por jugar, lo encontrado se guarda en estado/ para
no perder los ya jugados. Los marcadores salen de la página pública de cada torneo (/torneo/<id>)."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from .modelo import MADRID, Partido, incluir, norm, resultado, sesion

BASE = "https://wherevents.com"
REGISTROS = Path(__file__).resolve().parent.parent / "estado"


class Wherevents:
    def __init__(self):
        self.s = sesion()

    def partidos(self, equipo: str | int, temporada: int, solo: str | None = None) -> list[Partido]:
        """equipo: ID numérico de la ficha del equipo (el número de https://wherevents.com/equipo/<id>)."""
        eid = int(equipo)
        ruta = REGISTROS / f"wherevents_equipo_{eid}.json"
        crudo = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
        guardados = {p["id"]: Partido(**p) for p in crudo}
        try:
            actuales = {p.id: p for p in self._ficha(eid, temporada)}
        except Exception as e:  # la web no responde: se tira de lo guardado
            print(f"Aviso: Wherevents equipo {eid} no responde ({e}); se usa solo {ruta.name}.", file=sys.stderr)
            actuales = None

        if actuales is not None:
            actuales = {i: self._con_resultado(p, guardados.get(i)) for i, p in actuales.items()}
            # Se conservan los guardados que ya han empezado (la ficha los quita en cuanto se juegan, a veces
            # el mismo día); uno futuro que desaparece de la ficha se ha anulado
            todos = {i: p for i, p in guardados.items() if i not in actuales and _empezado(p)}
            todos.update(actuales)
            todos = self._resultados(todos)
            datos = [asdict(p) for p in sorted(todos.values(), key=lambda p: (p.fecha or "", p.id))]
            if datos != crudo:
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            todos = guardados

        inicio = date(temporada, 8, 1).isoformat()
        fin = date(temporada + 1, 8, 1).isoformat()
        return [p for p in todos.values() if inicio <= (p.fecha or "")[:10] < fin
                and incluir(p.condicion == "Local", solo)]

    @staticmethod
    def _con_resultado(p: Partido, guardado: Partido | None) -> Partido:
        """La ficha no trae marcadores: se mantiene el que ya estuviera guardado."""
        if guardado and guardado.jugado:
            p.puntos_local, p.puntos_visitante = guardado.puntos_local, guardado.puntos_visitante
            p.jugado, p.resultado = True, guardado.resultado
        return p

    def _resultados(self, partidos: dict[int, Partido]) -> dict[int, Partido]:
        """Pone el marcador a los partidos jugados, sacado de la página pública de cada torneo."""
        torneos = {m.group(1) for p in partidos.values() if (m := re.search(r"/torneo/(\d+)", p.url))}
        marcadores: dict[int, tuple[int, int]] = {}
        for tid in torneos:
            try:
                r = self.s.get(f"{BASE}/torneo/{tid}", timeout=30)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001 - sin resultados no se pierde el calendario
                print(f"Aviso: no se pudieron leer los resultados del torneo {tid} de Wherevents: {e}",
                      file=sys.stderr)
                continue
            marcadores |= _marcadores(r.text)
        for p in partidos.values():
            if p.id in marcadores:
                p.puntos_local, p.puntos_visitante = marcadores[p.id]
                p.jugado = True
                p.resultado = resultado(p.condicion == "Local", p.puntos_local, p.puntos_visitante)
        return partidos

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


def _empezado(p: Partido) -> bool:
    """True si el partido ya ha empezado (o, sin hora conocida, si es de hoy o anterior)."""
    if not p.fecha:
        return False
    ahora = datetime.now(MADRID)
    if "T" in p.fecha:
        return datetime.fromisoformat(p.fecha) <= ahora
    return date.fromisoformat(p.fecha[:10]) <= ahora.date()


_MARCADOR = re.compile(r'\{"id":(\d+),"evento_id":(?:(?!\{"id":\d+,"evento_id").)*?'
                       r'"puntos_local":(\d+),"puntos_visitante":(\d+),"estado":"jugado"', re.S)


def _marcadores(html: str) -> dict[int, tuple[int, int]]:
    """id de partido -> (puntos local, puntos visitante) de los partidos jugados del torneo.

    Salen de los datos que la página del torneo lleva incrustados para la web (JSON con comillas escapadas)."""
    datos = html.replace('\\"', '"')
    return {int(m[1]): (int(m[2]), int(m[3])) for m in _MARCADOR.finditer(datos)}
