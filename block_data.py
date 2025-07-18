from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class BlockData:
    block: dict[str, any]   # {"user": "...", "assistant": "..."}
    universe: int
    connections: Optional[List[str]] = None
    attachments: Optional[List[str]] = None
    data: Optional[any] = None
    layers: dict[int, dict[str, any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, any]:
        result = {
            "block": self.block,
            "universe": self.universe
        }
        if self.attachments is not None:
            result["attachments"] = self.attachments
        if self.data is not None:
            result["data"] = self.data
        if self.layers:
            result["layers"] = self.layers
        if self.connections is not None:
            result["connections"] = self.connections
        return result
