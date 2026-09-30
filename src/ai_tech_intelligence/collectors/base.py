from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Candidate


class SourceAdapter(ABC):
    @abstractmethod
    def discover(self, *args: object, **kwargs: object) -> list[Candidate]:
        raise NotImplementedError

