from dataclasses import dataclass

@dataclass(frozen=True)
class Finding:
    text:str
    start:int
    end:int
    entity_type:str
    detector:str
    confidence: float
    validated: bool