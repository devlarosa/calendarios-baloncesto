"""Calendarios de baloncesto: scrapers de FEB, ACB y Euroliga con exportación a CSV, JSON e ICS."""
from .acb import ACB
from .euroliga import Euroliga
from .feb import FEB
from .modelo import Partido

FUENTES = {"feb": FEB, "acb": ACB, "euroliga": Euroliga}

__all__ = ["ACB", "Euroliga", "FEB", "FUENTES", "Partido"]
