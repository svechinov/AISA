from datetime import datetime

from pydantic import BaseModel, model_validator


class ProjectCreate(BaseModel):
    name: str
    type: str = "generic"


class ProjectRead(BaseModel):
    id: int
    project_id: int
    name: str
    type: str
    is_archived: bool
    created_at: datetime

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def copy_id_to_project_id(cls, data):
        if isinstance(data, dict):
            out = dict(data)
        else:
            out = {
                "id": data.id,
                "name": data.name,
                "type": data.type,
                "is_archived": getattr(data, "is_archived", False),
                "created_at": data.created_at,
            }
        if "project_id" not in out:
            out["project_id"] = out["id"]
        return out
