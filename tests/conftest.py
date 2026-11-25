"""Configuración común de las pruebas.

Se fija la locale «C» para que los mensajes de error del sistema (por ejemplo
«Permission denied») no dependan del idioma del equipo ni del orden en que se
importen PySide6/Qt durante la recolección de pruebas.
"""

from __future__ import annotations

import locale

locale.setlocale(locale.LC_ALL, "C")
