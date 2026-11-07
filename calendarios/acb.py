"""Fuente: ACB (acb.com) — Liga Endesa, Copa del Rey y Supercopa Endesa.

Las páginas de calendario de acb.com (Next.js) llevan incrustada la temporada completa de cada competición.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from .modelo import MADRID, Partido, incluir, norm, resultado, sesion, slug

COMPETICIONES = {  # slug de la URL -> nombre
    "liga": "Liga Endesa",
    "copa-del-rey": "Copa del Rey",
    "supercopa": "Supercopa Endesa",
}


def _fecha_madrid(utc_iso: str, con_hora: bool) -> str:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).astimezone(MADRID)
    return dt.isoformat() if con_hora else dt.date().isoformat()


def _buscar(o):
    """Busca recursivamente el objeto de datos que contiene 'teams' y 'rounds'."""
    if isinstance(o, dict):
        if isinstance(o.get("teams"), list) and isinstance(o.get("rounds"), list):
            return o
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            if r := _buscar(v):
                return r
    return None


class ACB:
    def __init__(self):
        self.s = sesion()

    def _datos(self, comp: str, temporada_id: int | None) -> dict | None:
        r = self.s.get(f"https://acb.com/es/{comp}/calendario",
                       params={"temporada": temporada_id} if temporada_id else None, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        trozos = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', r.text)
        payload = "".join(json.loads(f'"{t}"') for t in trozos)
        for linea in payload.split("\n"):
            if '"rounds"' in linea and '"teams"' in linea:
                try:
                    if datos := _buscar(json.loads(linea.partition(":")[2])):
                        return datos
                except json.JSONDecodeError:
                    continue
        return None

    def _temporada_id(self, anio: int) -> int:
        for t in ((self._datos("liga", None) or {}).get("availableFilters", {}).get("seasons", [])):
            if t.get("startYear") == anio:
                return t["id"]
        raise SystemExit(f"ACB: no encuentro la temporada {anio}/{anio + 1}.")

    def partidos(self, equipo: str, temporada: int, solo: str | None = None) -> list[Partido]:
        """equipo: nombre (o parte) tal como aparece en acb.com, p.ej. 'Real Madrid'."""
        tid = self._temporada_id(temporada)
        clave = norm(equipo)
        out = []
        for comp, competicion in COMPETICIONES.items():
            datos = self._datos(comp, tid)
            if not datos or datos.get("selectedFilters", {}).get("season") != tid:
                continue  # competición aún no publicada para esta temporada
            equipos = datos["teams"]

            def eq(ref):
                return equipos[int(ref.rsplit(":", 1)[1])] if isinstance(ref, str) else ref

            for ronda in datos["rounds"]:
                fase = ronda.get("subphase")
                fase = (fase.get("name") or "") if isinstance(fase, dict) else (fase or "")
                for m in ronda["matches"]:
                    local, visit = eq(m["homeTeam"]), eq(m["awayTeam"])
                    es_local = clave in norm(local["fullName"])
                    if not (es_local or clave in norm(visit["fullName"])) or not incluir(es_local, solo):
                        continue
                    estado = m.get("matchStatus", "")
                    jugado = estado == "FINALIZED"
                    pl, pv = (m["homeTeamScore"], m["awayTeamScore"]) if jugado else (None, None)
                    tv = [c["name"] for c in (m.get("broadcastChannels") or {}).get("primary", [])]
                    out.append(Partido(
                        id=m["id"], temporada=f"{temporada}/{temporada + 1}", competicion=competicion, grupo=fase,
                        jornada=f"Jornada {ronda['roundNumber']}" if comp == "liga" and not fase else "",
                        fecha=_fecha_madrid(m["startDateTime"], con_hora=estado != "UNSCHEDULED"),
                        local=local["fullName"], local_id=local.get("clubId"),
                        visitante=visit["fullName"], visitante_id=visit.get("clubId"),
                        puntos_local=pl, puntos_visitante=pv, jugado=jugado,
                        condicion="Local" if es_local else "Visitante",
                        rival=visit["fullName"] if es_local else local["fullName"],
                        resultado=resultado(es_local, pl, pv), pabellon="",
                        url=f"https://live.acb.com/es/partidos/{slug(local['fullName'])}-vs-"
                            f"{slug(visit['fullName'])}-{m['id']}/{'resumen' if jugado else 'previa'}",
                        uid=f"acb-{m['id']}@acb.com",
                        notas=("TV: " + ", ".join(tv)) if tv else "",
                    ))
        return out
