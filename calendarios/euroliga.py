"""Fuente: Euroliga — API pública api-live.euroleague.net (fase regular, play-in, playoffs y Final Four).

Con la opción 'canal' se quedan solo los partidos que Movistar Plus+ da en directo en ese canal
(p.ej. 'vamosd' = M+ Vamos), según su guía de TV."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import movistar
from .modelo import MADRID, Partido, incluir, norm, resultado, sesion, slug

API = "https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games"
REGISTROS = Path(__file__).resolve().parent.parent / "estado"

# Nombres que usa Movistar y que no se parecen a los de la Euroliga
ALIAS = {"ESTRELLA ROJA": "RED", "EFES": "IST", "OLIMPIA MILAN": "MIL", "MACABI": "TEL"}
# Palabras que comparten varios clubes y no sirven para distinguirlos
GENERICAS = {"FC", "BC", "KK", "BASKET", "BASKETBALL", "CLUB", "TEL", "AVIV", "ISTANBUL", "BELGRADE",
             "ATHENS", "DE", "VO"}


class Euroliga:
    def __init__(self):
        self.s = sesion()

    def partidos(self, equipo: str | None, temporada: int, solo: str | None = None,
                 canal: str | list[str] | None = None) -> list[Partido]:
        """equipo: código de club, p.ej. 'MAD' (Real Madrid), 'BAR', 'PAM' (Valencia); None = todos.
        canal: código(s) de canal de Movistar Plus+ ('vamosd' = M+ Vamos, 'mplus' = Movistar Plus+)
        para quedarse con los partidos que dan en directo."""
        params = {"teamCode": equipo} if equipo else {}
        r = self.s.get(API.format(year=temporada), params=params, timeout=30)
        r.raise_for_status()
        juegos = r.json().get("data", [])
        canales = [canal] if isinstance(canal, str) else canal
        emitidos = self._emitidos(juegos, temporada, canales) if canales else None

        out = []
        for g in juegos:
            loc, vis = g["local"], g["road"]
            if emitidos is not None and str(g["gameCode"]) not in emitidos:
                continue
            if equipo:
                es_local = loc["club"]["code"] == equipo
                if (not es_local and vis["club"]["code"] != equipo) or not incluir(es_local, solo):
                    continue
            jugado = bool(g.get("played"))
            pl, pv = (loc.get("score"), vis.get("score")) if jugado else (None, None)
            fase = g.get("phaseType") or {}
            if fase.get("code") == "RS":
                grupo, jornada = "Fase regular", f"Jornada {g['round']}"
            else:
                grupo, jornada = fase.get("name", ""), g.get("roundName", "")
            con_hora = bool(g.get("confirmedDate")) and bool(g.get("confirmedHour"))
            dt = datetime.fromisoformat(g["utcDate"].replace("Z", "+00:00")).astimezone(MADRID)
            notas = ""
            if emitidos is not None:
                emision = emitidos[str(g["gameCode"])]
                notas = f"TV: {movistar.nombre_canal(emision['canal'])}"
                if emision.get("ficha"):
                    notas += f"\n{emision['ficha']}"
            out.append(Partido(
                id=g["gameCode"], temporada=f"{temporada}/{temporada + 1}", competicion="Euroliga", grupo=grupo,
                jornada=jornada, fecha=dt.isoformat() if con_hora else dt.date().isoformat(),
                local=loc["club"]["name"], local_id=None, visitante=vis["club"]["name"], visitante_id=None,
                puntos_local=pl, puntos_visitante=pv, jugado=jugado,
                condicion=("Local" if es_local else "Visitante") if equipo else "",
                rival=(vis["club"]["name"] if es_local else loc["club"]["name"]) if equipo else "",
                resultado=resultado(es_local, pl, pv) if equipo else "",
                pabellon=(g.get("venue") or {}).get("name") or "",
                url=f"https://www.euroleaguebasketball.net/euroleague/game-center/{g['season']['alias']}/"
                    f"{slug(loc['club']['name'])}-{slug(vis['club']['name'])}/E{temporada}/{g['gameCode']}/",
                uid=f"euroliga-E{temporada}-{g['gameCode']}@euroleague.net",
                notas=notas,
            ))
        return out

    # ------------------------------------------------------------------------------ Movistar Plus+
    def _emitidos(self, juegos: list[dict], temporada: int, canales: list[str]) -> dict[str, dict]:
        """gameCode -> datos de la emisión en directo en el canal.

        La guía solo abarca unos días, así que lo encontrado se guarda en estado/ y se conserva. Para los
        días que la guía sí ha publicado, manda la guía (si Movistar cambia de partido, se corrige)."""
        ruta = REGISTROS / f"euroliga_E{temporada}_{'_'.join(canales)}.json"
        registro = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
        emisiones, dias = [], None
        for canal in canales:  # solo se dan por leídos los días que ha publicado la guía de todos los canales
            ems, leidos = movistar.guia(canal)
            emisiones += [(canal, e) for e in ems]
            dias = leidos if dias is None else dias & leidos
        por_codigo = {str(g["gameCode"]): g for g in juegos}

        def dia(g):
            return datetime.fromisoformat(g["utcDate"].replace("Z", "+00:00")).astimezone(MADRID).date()

        nuevo = {c: v for c, v in registro.items() if c not in por_codigo or dia(por_codigo[c]) not in dias}
        for canal, e in emisiones:
            g = self._casar(e, juegos)
            if g and (str(g["gameCode"]) not in nuevo or dia(g) in dias):
                nuevo.setdefault(str(g["gameCode"]), {"canal": canal, "inicio": e.inicio.isoformat(),
                                                      "titulo": e.titulo, "ficha": e.url})
        if dias and nuevo != registro:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ordenado = dict(sorted(nuevo.items(), key=lambda kv: int(kv[0])))
            ruta.write_text(json.dumps(ordenado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not dias:
            print(f"Aviso: la guía de Movistar no ha respondido; se usa solo {ruta.name}.", file=sys.stderr)
        return nuevo

    @staticmethod
    def _casar(e: movistar.Emision, juegos: list[dict]) -> dict | None:
        """Partido de la Euroliga que corresponde a una emisión en directo, o None (redifusión, previa...)."""
        titulo = e.titulo
        if not titulo.startswith("Euroliga de baloncesto") or ":" not in titulo:
            return None
        equipos = titulo.split(":", 1)[1].replace("(VO)", "").split(" - ")
        if len(equipos) != 2:
            return None
        mejor, puntos = None, 0
        for g in juegos:
            ini = datetime.fromisoformat(g["utcDate"].replace("Z", "+00:00"))
            # Directo: la emisión empieza entre 40 min antes y 15 min después del salto inicial
            if not timedelta(minutes=-40) <= e.inicio - ini <= timedelta(minutes=15):
                continue
            pl, pv = _parecido(equipos[0], g["local"]["club"]), _parecido(equipos[1], g["road"]["club"])
            if pl and pv and pl + pv > puntos:
                mejor, puntos = g, pl + pv
        return mejor


def _parecido(nombre: str, club: dict) -> int:
    n = norm(nombre)
    if ALIAS.get(n) == club["code"]:
        return 10
    propias = set(n.split()) - GENERICAS
    del_club = set()
    for campo in ("name", "abbreviatedName", "editorialName"):
        del_club |= set(norm(club.get(campo) or "").split())
    return len(propias & (del_club - GENERICAS))
