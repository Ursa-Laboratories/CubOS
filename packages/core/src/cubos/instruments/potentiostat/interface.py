"""Generic potentiostat instrument interface."""

from abc import abstractmethod

from cubos.instruments.base_instrument import BaseInstrument
from cubos.instruments.potentiostat.models import (
    CAParams,
    CAResult,
    CPParams,
    CPResult,
    CVParams,
    CVResult,
    OCPParams,
    OCPResult,
)


class PotentiostatInstrument(BaseInstrument):
    """Base class for potentiostat implementations."""

    @abstractmethod
    def run_CV(self, params: CVParams) -> CVResult:
        """Run cyclic voltammetry and return the measured trace."""

    @abstractmethod
    def run_OCP(self, params: OCPParams) -> OCPResult:
        """Run open-circuit potential and return the measured trace."""

    @abstractmethod
    def run_CA(self, params: CAParams) -> CAResult:
        """Run chronoamperometry and return the measured trace."""

    @abstractmethod
    def run_CP(self, params: CPParams) -> CPResult:
        """Run chronopotentiometry and return the measured trace."""
