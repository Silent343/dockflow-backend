"""Excepciones del dominio. No dependen de frameworks externos."""


class DomainError(Exception):
    """Error base del dominio."""


class InvalidRucError(DomainError):
    """El RUC no cumple las reglas de SUNAT."""


class InvalidDocumentError(DomainError):
    """El documento extraído no es coherente (totales no cuadran, etc.)."""
