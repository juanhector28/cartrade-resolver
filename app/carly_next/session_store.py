from typing import Protocol
from .contracts import BuyerState

class StateStore(Protocol):
    def get(self, session_id: str) -> BuyerState | None: ...
    def put(self, session_id: str, state: BuyerState) -> None: ...

class MemorySessionStore:
    def __init__(self):
        self.states: dict[str, BuyerState] = {}

    def get(self, session_id: str) -> BuyerState | None:
        return self.states.get(session_id)

    def put(self, session_id: str, state: BuyerState) -> None:
        self.states[session_id] = state
