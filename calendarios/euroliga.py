"""Fuente: Euroliga — API pública api-live.euroleague.net (fase regular, play-in, playoffs y Final Four)."""
from __future__ import annotations

from datetime import datetime

from .modelo import MADRID, Partido, incluir, resultado, sesion, slug

API = "https://api-live.euroleague.net/v2/competitions/E/seasons/E{year}/games"


class Euroliga:
    def __init__(self):
        self.s = sesion()

    def partidos(self, equipo: str, temporada: int, solo: str | None = None) -> list[Partido]:
        """equipo: código de club de la Euroliga, p.ej. 'MAD' (Real Madrid), 'BAR', 'PAM' (Valencia)."""
        r = self.s.get(API.format(year=temporada), params={"teamCode": equipo}, timeout=30)
        r.raise_for_status()
        out = []
        for g in r.json().get("data", []):
            loc, vis = g["local"], g["road"]
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
            out.append(Partido(
                id=g["gameCode"], temporada=f"{temporada}/{temporada + 1}", competicion="Euroliga", grupo=grupo,
                jornada=jornada, fecha=dt.isoformat() if con_hora else dt.date().isoformat(),
                local=loc["club"]["name"], local_id=None, visitante=vis["club"]["name"], visitante_id=None,
                puntos_local=pl, puntos_visitante=pv, jugado=jugado,
                condicion="Local" if es_local else "Visitante",
                rival=vis["club"]["name"] if es_local else loc["club"]["name"],
                resultado=resultado(es_local, pl, pv),
                pabellon=(g.get("venue") or {}).get("name") or "",
                url=f"https://www.euroleaguebasketball.net/euroleague/game-center/{g['season']['alias']}/"
                    f"{slug(loc['club']['name'])}-{slug(vis['club']['name'])}/E{temporada}/{g['gameCode']}/",
                uid=f"euroliga-E{temporada}-{g['gameCode']}@euroleague.net",
            ))
        return out
