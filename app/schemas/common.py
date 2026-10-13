from pydantic import BaseModel, ConfigDict


class InputModel(BaseModel):
    # extra="forbid": campos como tenant_id ou id no corpo são rejeitados (422),
    # em vez de ignorados silenciosamente.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OutputModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
