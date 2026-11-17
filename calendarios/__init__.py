"""Calendarios de baloncesto: scrapers de FEB, ACB, Euroliga y Wherevents con exportación a CSV, JSON e ICS."""
from .acb import ACB
from .euroliga import Euroliga
from .feb import FEB
from .modelo import Partido
from .wherevents import Wherevents

FUENTES = {"feb": FEB, "acb": ACB, "euroliga": Euroliga, "wherevents": Wherevents}

__all__ = ["ACB", "Euroliga", "FEB", "FUENTES", "Partido", "Wherevents"]
