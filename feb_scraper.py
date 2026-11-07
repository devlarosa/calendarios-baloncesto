#!/usr/bin/env python3
"""Scraper del calendario y resultados de un equipo en las competiciones de la FEB (feb.es).

Por defecto: Cultural y Deportiva Leonesa, Segunda FEB, temporada actual.

Ejemplos:
    python feb_scraper.py                         # Leonesa, Segunda FEB 2026/27 -> CSV, JSON e ICS en ./salida
    python feb_scraper.py --temporada 2025        # temporada 2025/2026
    python feb_scraper.py --equipo ponferrada     # otro equipo de la misma liga
    python feb_scraper.py --liga 1 --equipo 1009588 --formatos csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://www.feb.es/competiciones"
CALENDARIO_URL = BASE + "/calendario.aspx"
PARTIDO_URL = BASE + "/Partido.aspx?p={}"
MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = "Mozilla/5.0 (compatible; feb-scraper/1.0)"
CTL = "_ctl0:MainContentPlaceHolderMaster:"

LIGAS = {1: "Primera FEB", 2: "Segunda FEB", 3: "Tercera FEB", 4: "Liga Femenina Endesa",
         9: "Liga Femenina 2", 67: "Liga Femenina Challenge", 73: "Copa España", 74: "Liga U"}


@dataclass
class Partido:
    id: int
    temporada: str
    competicion: str
    grupo: str
    jornada: str
    fecha: str | None          # ISO 8601 con zona horaria si se conoce la hora; solo fecha si no
    local: str
    local_id: int | None
    visitante: str
    visitante_id: int | None
    puntos_local: int | None
    puntos_visitante: int | None
    jugado: bool
    condicion: str             # "Local" / "Visitante" respecto al equipo buscado
    rival: str
    resultado: str             # "V" / "D" / "" respecto al equipo buscado
    pabellon: str
    url: str


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def _id_de(href: str | None, param: str) -> int | None:
    m = re.search(rf"[?&]{param}=(\d+)", href or "")
    return int(m.group(1)) if m else None


class FebScraper:
    def __init__(self, pausa: float = 0.5):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.pausa = pausa

    def _get(self, url: str, **kw) -> BeautifulSoup:
        r = self.s.get(url, timeout=30, **kw)
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

    # ------------------------------------------------------------------ calendario
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
    def parse_calendario(soup: BeautifulSoup, temporada: str, competicion: str, grupo: str) -> list[dict]:
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
                    "temporada": temporada, "competicion": competicion, "grupo": grupo,
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

    # ------------------------------------------------------------------ detalle
    def detalle_partido(self, pid: int) -> dict:
        soup = self._get(PARTIDO_URL.format(pid))
        out = {}
        txt = soup.get_text("\n", strip=True)
        if m := re.search(r"Fecha\n(\d{2}/\d{2}/\d{4})\s*-\s*(\d{1,2}:\d{2})", txt):
            out["fecha"] = datetime.strptime(f"{m[1]} {m[2]}", "%d/%m/%Y %H:%M").replace(tzinfo=MADRID)
        if pab := soup.select_one(".pabellon"):
            out["pabellon"] = pab.get_text(" ", strip=True)
        return out

    # ------------------------------------------------------------------ alto nivel
    def calendario_equipo(self, equipo: str, liga: int, temporada: int, detalles: bool = True,
                          solo_casa: bool = False, solo_fuera: bool = False) -> list[Partido]:
        competicion = LIGAS.get(liga, f"Competición {liga}")
        tempo_txt = f"{temporada}/{temporada + 1}"
        es_id = equipo.isdigit()
        clave = _norm(equipo)

        def es_mio(nombre, eid):
            return eid == int(equipo) if es_id else clave in _norm(nombre)

        encontrados = []
        for grupo, soup in self.paginas_por_grupo(liga, temporada):
            todos = self.parse_calendario(soup, tempo_txt, competicion, grupo)
            mios = [p for p in todos if (not solo_fuera and es_mio(p["local"], p["local_id"]))
                    or (not solo_casa and es_mio(p["visitante"], p["visitante_id"]))]
            if mios:
                encontrados.extend(mios)
                break  # un equipo solo está en un grupo de liga regular
        if not encontrados:
            raise SystemExit(f"No se ha encontrado el equipo '{equipo}' en {competicion} {tempo_txt}.")

        resultado = []
        for p in encontrados:
            det = {}
            if detalles and p["id"]:
                try:
                    det = self.detalle_partido(p["id"])
                except requests.RequestException as e:
                    print(f"Aviso: no se pudo leer el partido {p['id']}: {e}", file=sys.stderr)
            fecha = det.get("fecha") or p["fecha"]
            if fecha:
                fecha_iso = fecha.isoformat()
            elif p["fecha_jornada"]:
                fecha_iso = datetime.strptime(p["fecha_jornada"], "%d/%m/%Y").date().isoformat()
            else:
                fecha_iso = None
            local = es_mio(p["local"], p["local_id"])
            jugado = p["puntos_local"] is not None
            res = ""
            if jugado:
                propios, ajenos = ((p["puntos_local"], p["puntos_visitante"]) if local
                                   else (p["puntos_visitante"], p["puntos_local"]))
                res = "V" if propios > ajenos else "D"
            resultado.append(Partido(
                id=p["id"], temporada=tempo_txt, competicion=competicion, grupo=grupo, jornada=p["jornada"],
                fecha=fecha_iso, local=p["local"], local_id=p["local_id"], visitante=p["visitante"],
                visitante_id=p["visitante_id"], puntos_local=p["puntos_local"], puntos_visitante=p["puntos_visitante"],
                jugado=jugado, condicion="Local" if local else "Visitante",
                rival=p["visitante"] if local else p["local"], resultado=res,
                pabellon=det.get("pabellon", ""), url=PARTIDO_URL.format(p["id"]) if p["id"] else "",
            ))
        resultado.sort(key=lambda x: x.fecha or "")
        return resultado


# ---------------------------------------------------------------------- exportadores
def exportar_csv(partidos: list[Partido], ruta: Path):
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel abre bien los acentos
        w = csv.DictWriter(f, fieldnames=list(asdict(partidos[0]).keys()), delimiter=";")
        w.writeheader()
        w.writerows(asdict(p) for p in partidos)


def exportar_json(partidos: list[Partido], ruta: Path):
    ruta.write_text(json.dumps([asdict(p) for p in partidos], ensure_ascii=False, indent=2), encoding="utf-8")


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def exportar_ics(partidos: list[Partido], ruta: Path, nombre_cal: str, duracion_min: int = 120, aviso_min: int = 0):
    ahora = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//feb-scraper//ES", "CALSCALE:GREGORIAN",
              f"X-WR-CALNAME:{_ics_escape(nombre_cal)}", "X-WR-TIMEZONE:Europe/Madrid"]
    for p in partidos:
        if not p.fecha:
            continue
        titulo = f"{p.local} - {p.visitante}"
        if p.jugado:
            titulo = f"{p.local} {p.puntos_local}-{p.puntos_visitante} {p.visitante}"
        lineas += ["BEGIN:VEVENT", f"UID:feb-{p.id}@feb.es", f"DTSTAMP:{ahora}"]
        if "T" in p.fecha:
            ini = datetime.fromisoformat(p.fecha).astimezone(timezone.utc)
            fin = ini + timedelta(minutes=duracion_min)
            lineas += [f"DTSTART:{ini:%Y%m%dT%H%M%SZ}", f"DTEND:{fin:%Y%m%dT%H%M%SZ}"]
        else:  # sin hora conocida: evento de día completo
            d = datetime.fromisoformat(p.fecha).date()
            lineas += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        desc = f"{p.competicion} {p.temporada} - {p.grupo} - {p.jornada}\n{p.url}"
        lineas += [f"SUMMARY:{_ics_escape(titulo)}", f"DESCRIPTION:{_ics_escape(desc)}"]
        if p.pabellon:
            lineas.append(f"LOCATION:{_ics_escape(p.pabellon)}")
        if p.url:
            lineas.append(f"URL:{p.url}")
        if aviso_min > 0 and not p.jugado:
            lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(titulo)}",
                       f"TRIGGER:-PT{aviso_min}M", "END:VALARM"]
        lineas.append("END:VEVENT")
    lineas.append("END:VCALENDAR")
    ruta.write_text("\r\n".join(lineas) + "\r\n", encoding="utf-8")


def _temporada_actual() -> int:
    hoy = datetime.now(MADRID)
    return hoy.year if hoy.month >= 8 else hoy.year - 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Calendario y resultados de un equipo en competiciones FEB.")
    ap.add_argument("--equipo", default="LEONESA", help="Texto del nombre o ID FEB del equipo (def.: LEONESA)")
    ap.add_argument("--liga", type=int, default=2, help="ID de competición: 1=Primera, 2=Segunda, 3=Tercera FEB... (def.: 2)")
    ap.add_argument("--temporada", type=int, default=_temporada_actual(), help="Año de inicio, p.ej. 2026 = 2026/2027")
    ap.add_argument("--formatos", default="csv,json,ics", help="Lista separada por comas: csv,json,ics")
    ap.add_argument("--salida", default="salida", help="Carpeta de salida (def.: ./salida)")
    filtro = ap.add_mutually_exclusive_group()
    filtro.add_argument("--solo-casa", action="store_true", help="Solo los partidos en los que el equipo juega como local")
    filtro.add_argument("--solo-fuera", action="store_true", help="Solo los partidos en los que el equipo juega como visitante")
    ap.add_argument("--aviso", type=int, default=0, metavar="MIN",
                    help="Añade un recordatorio al calendario MIN minutos antes de cada partido (0 = sin aviso)")
    ap.add_argument("--sin-detalles", action="store_true",
                    help="No entrar en cada partido (más rápido, pero sin hora exacta de los jugados ni pabellón)")
    args = ap.parse_args(argv)

    scraper = FebScraper()
    partidos = scraper.calendario_equipo(args.equipo, args.liga, args.temporada, detalles=not args.sin_detalles,
                                         solo_casa=args.solo_casa, solo_fuera=args.solo_fuera)

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", _norm(args.equipo).lower()).strip("_")
    sufijo = "_casa" if args.solo_casa else "_fuera" if args.solo_fuera else ""
    etiqueta = "en casa " if args.solo_casa else "fuera " if args.solo_fuera else ""
    base = out / f"{slug}_{LIGAS.get(args.liga, args.liga)}_{args.temporada}{sufijo}".replace(" ", "_").lower()
    formatos = {f.strip().lower() for f in args.formatos.split(",")}
    if "csv" in formatos:
        exportar_csv(partidos, base.with_suffix(".csv"))
    if "json" in formatos:
        exportar_json(partidos, base.with_suffix(".json"))
    if "ics" in formatos:
        nombre = f"{args.equipo.title()} {etiqueta}- {partidos[0].competicion} {partidos[0].temporada}"
        exportar_ics(partidos, base.with_suffix(".ics"), nombre, aviso_min=args.aviso)

    v = sum(p.resultado == "V" for p in partidos)
    d = sum(p.resultado == "D" for p in partidos)
    print(f"{len(partidos)} partidos ({partidos[0].competicion} {partidos[0].temporada}, {partidos[0].grupo}) - balance {v}V-{d}D")
    for p in partidos:
        marcador = f"{p.puntos_local}-{p.puntos_visitante} {p.resultado}" if p.jugado else "pendiente"
        print(f"  {p.jornada:<12} {(p.fecha or '')[:16]:<16} {p.condicion:<9} {p.rival:<40} {marcador}")
    print(f"Ficheros en {out.resolve()}/ ({', '.join(sorted(formatos))})")


if __name__ == "__main__":
    main()
