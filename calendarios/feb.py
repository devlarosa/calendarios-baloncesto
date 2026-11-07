"""Fuente: Federación Española de Baloncesto (feb.es) — Primera, Segunda, Tercera FEB, ligas femeninas..."""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .modelo import MADRID, Partido, incluir, norm, resultado, sesion

BASE = "https://www.feb.es/competiciones"
CALENDARIO_URL = BASE + "/calendario.aspx"
PARTIDO_URL = BASE + "/Partido.aspx?p={}"
CTL = "_ctl0:MainContentPlaceHolderMaster:"

LIGAS = {1: "Primera FEB", 2: "Segunda FEB", 3: "Tercera FEB", 4: "Liga Femenina Endesa",
         9: "Liga Femenina 2", 67: "Liga Femenina Challenge", 73: "Copa España", 74: "Liga U"}


def _id_de(href: str | None, param: str) -> int | None:
    m = re.search(rf"[?&]{param}=(\d+)", href or "")
    return int(m.group(1)) if m else None


class FEB:
    def __init__(self, pausa: float = 0.5):
        self.s = sesion()
        self.pausa = pausa

    def _get(self, url: str) -> BeautifulSoup:
        r = self.s.get(url, timeout=30)
        r.raise_for_status()
        time.sleep(self.pausa)
        return BeautifulSoup(r.text, "html.parser")

    def _postback(self, url: str, soup: BeautifulSoup, target: str, valores: dict) -> BeautifulSoup:
        """Simula el cambio de un desplegable ASP.NET (__doPostBack)."""
        form = soup.find("form")
        data = {i["name"]: i.get("value", "") for i in form.find_all("input") if i.get("name")}
        for sel in form.find_all("select"):
            op = sel.find("option", selected=True) or sel.find("option")
            if op is not None:
                data[sel["name"]] = op.get("value", "")
        data.update(valores)
        data["__EVENTTARGET"] = target.replace(":", "$")
        data["__EVENTARGUMENT"] = ""
        r = self.s.post(url, data=data, timeout=30)
        r.raise_for_status()
        time.sleep(self.pausa)
        return BeautifulSoup(r.text, "html.parser")

    def paginas_por_grupo(self, liga: int, temporada: int):
        """Devuelve (nombre_grupo, soup) para cada grupo de la competición."""
        url = f"{CALENDARIO_URL}?g={liga}&t={temporada}"
        soup = self._get(url)
        sel_t = soup.find("select", {"name": CTL + "temporadasDropDownList"})
        if sel_t is not None:
            actual = (sel_t.find("option", selected=True) or {}).get("value")
            if actual != str(temporada):
                soup = self._postback(url, soup, CTL + "temporadasDropDownList",
                                      {CTL + "temporadasDropDownList": str(temporada)})
        sel_g = soup.find("select", {"name": CTL + "gruposDropDownList"})
        if sel_g is None:
            yield "", soup
            return
        grupos = [(o["value"], o.get_text(strip=True)) for o in sel_g.find_all("option")]
        actual = (sel_g.find("option", selected=True) or sel_g.find("option"))["value"]
        for valor, nombre in grupos:
            pag = soup if valor == actual else self._postback(
                url, soup, CTL + "gruposDropDownList", {CTL + "gruposDropDownList": valor})
            yield nombre, pag

    @staticmethod
    def parse_calendario(soup: BeautifulSoup) -> list[dict]:
        partidos = []
        for tabla in soup.select('table[id$="_DataGrid3"]'):
            h1 = tabla.find_previous("h1")
            cab = h1.get_text(" ", strip=True) if h1 else ""
            m = re.match(r"(.*?)\s*(\d{2}/\d{2}/\d{4})?$", cab)
            jornada, fecha_jornada = (m.group(1), m.group(2)) if m else (cab, None)
            for tr in tabla.find_all("tr"):
                loc = tr.find("td", class_="local")
                vis = tr.find("td", class_="visitante")
                centro = tr.find("td", class_=["resultado", "fecha"])
                if not (loc and vis and centro):
                    continue
                a_loc, a_vis, a_c = loc.find("a"), vis.find("a"), centro.find("a")
                texto = centro.get_text(" ", strip=True)
                p = {
                    "id": _id_de(a_c.get("href") if a_c else None, "p"),
                    "jornada": jornada, "fecha_jornada": fecha_jornada,
                    "local": loc.get_text(" ", strip=True), "local_id": _id_de(a_loc and a_loc.get("href"), "i"),
                    "visitante": vis.get_text(" ", strip=True), "visitante_id": _id_de(a_vis and a_vis.get("href"), "i"),
                    "puntos_local": None, "puntos_visitante": None, "fecha": None,
                }
                if m_res := re.fullmatch(r"(\d+)\s*-\s*(\d+)", texto):
                    p["puntos_local"], p["puntos_visitante"] = int(m_res[1]), int(m_res[2])
                elif m_f := re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})", texto):
                    p["fecha"] = datetime.strptime(f"{m_f[1]} {m_f[2]}", "%d/%m/%Y %H:%M").replace(tzinfo=MADRID)
                elif m_f := re.search(r"\d{2}/\d{2}/\d{4}", texto):
                    p["fecha_jornada"] = m_f[0]
                partidos.append(p)
        return partidos

    def detalle_partido(self, pid: int) -> dict:
        """Ficha del partido: fecha/hora exacta (también de los ya jugados) y pabellón."""
        soup = self._get(PARTIDO_URL.format(pid))
        out = {}
        txt = soup.get_text("\n", strip=True)
        if m := re.search(r"Fecha\n(\d{2}/\d{2}/\d{4})\s*-\s*(\d{1,2}:\d{2})", txt):
            out["fecha"] = datetime.strptime(f"{m[1]} {m[2]}", "%d/%m/%Y %H:%M").replace(tzinfo=MADRID)
        if pab := soup.select_one(".pabellon"):
            out["pabellon"] = pab.get_text(" ", strip=True)
        return out

    def partidos(self, equipo: str, temporada: int, solo: str | None = None, liga: int = 2,
                 detalles: bool = True) -> list[Partido]:
        """equipo: texto del nombre o ID FEB. liga: ID de competición (ver LIGAS)."""
        competicion = LIGAS.get(liga, f"Competición {liga}")
        tempo_txt = f"{temporada}/{temporada + 1}"
        es_id = str(equipo).isdigit()
        clave = norm(str(equipo))

        def es_mio(nombre, eid):
            return eid == int(equipo) if es_id else clave in norm(nombre)

        encontrados, grupo = [], ""
        for grupo, soup in self.paginas_por_grupo(liga, temporada):
            mios = [p for p in self.parse_calendario(soup)
                    if es_mio(p["local"], p["local_id"]) or es_mio(p["visitante"], p["visitante_id"])]
            if mios:
                encontrados = [p for p in mios if incluir(es_mio(p["local"], p["local_id"]), solo)]
                break  # un equipo solo está en un grupo de liga regular
        else:
            raise SystemExit(f"FEB: no se ha encontrado el equipo '{equipo}' en {competicion} {tempo_txt}.")

        out = []
        for p in encontrados:
            det = {}
            if detalles and p["id"]:
                try:
                    det = self.detalle_partido(p["id"])
                except requests.RequestException as e:
                    print(f"Aviso: no se pudo leer el partido FEB {p['id']}: {e}", file=sys.stderr)
            fecha = det.get("fecha") or p["fecha"]
            if fecha:
                fecha_iso = fecha.isoformat()
            elif p["fecha_jornada"]:
                fecha_iso = datetime.strptime(p["fecha_jornada"], "%d/%m/%Y").date().isoformat()
            else:
                fecha_iso = None
            local = es_mio(p["local"], p["local_id"])
            jugado = p["puntos_local"] is not None
            out.append(Partido(
                id=p["id"], temporada=tempo_txt, competicion=competicion, grupo=grupo, jornada=p["jornada"],
                fecha=fecha_iso, local=p["local"], local_id=p["local_id"], visitante=p["visitante"],
                visitante_id=p["visitante_id"], puntos_local=p["puntos_local"], puntos_visitante=p["puntos_visitante"],
                jugado=jugado, condicion="Local" if local else "Visitante",
                rival=p["visitante"] if local else p["local"],
                resultado=resultado(local, p["puntos_local"], p["puntos_visitante"]),
                pabellon=det.get("pabellon", ""), url=PARTIDO_URL.format(p["id"]) if p["id"] else "",
                uid=f"feb-{p['id']}@feb.es",
            ))
        return out
