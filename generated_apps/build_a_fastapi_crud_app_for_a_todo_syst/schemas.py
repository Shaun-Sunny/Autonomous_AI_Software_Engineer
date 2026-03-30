from pydantic import BaseModel


class TodoBase(BaseModel):
    title: str
    status: bool = False


class TodoCreate(TodoBase):
    pass


class TodoUpdate(TodoBase):
    pass


class TodoOut(TodoBase):
    id: int

    class Config:
        from_attributes = True
