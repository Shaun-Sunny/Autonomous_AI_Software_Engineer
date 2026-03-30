from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Todo
from schemas import TodoCreate, TodoOut, TodoUpdate

Base.metadata.create_all(bind=engine)

app = FastAPI(title="build_a_fastapi_crud_app_for_a_todo_syst")


@app.post("/todos", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
def create_item(payload: TodoCreate, db: Session = Depends(get_db)):
    item = Todo(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/todos", response_model=list[TodoOut])
def list_items(db: Session = Depends(get_db)):
    return db.query(Todo).all()


@app.get("/todos/{item_id}", response_model=TodoOut)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Todo).filter(Todo.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return item


@app.put("/todos/{item_id}", response_model=TodoOut)
def update_item(item_id: int, payload: TodoUpdate, db: Session = Depends(get_db)):
    item = db.query(Todo).filter(Todo.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.delete("/todos/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Todo).filter(Todo.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(item)
    db.commit()
