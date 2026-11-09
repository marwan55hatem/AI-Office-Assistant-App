"""/tasks: personal to-dos and tasks a manager assigns.

* Employees see and create only their own tasks; ``assigned_by`` stays empty.
* Managers may create a task for any employee of the company (``assigned_by`` is
  set to them) and see or change any task of the company.
* A task can be ticked, re-dated or deleted by its owner or by a manager.
* An urgent task given by a manager is e-mailed to the employee (always; see Phase 5).
"""
import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.deps import CurrentUser, invalidate_reports_after_write
from app.db.models import Task
from app.repositories.tenant import TaskRepository
from app.routers.common import NOT_FOUND, target_user
from app.services.email.outbox import queue_urgent_task

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(invalidate_reports_after_write)])

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID | None = None
    title: Title
    priority: Literal["normal", "urgent"] = "normal"
    description: Annotated[str, Field(max_length=5000)] | None = None
    deadline_date: date | None = None
    deadline_time: time | None = None


class DeadlineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deadline_date: date | None = None
    deadline_time: time | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    assigned_by: uuid.UUID | None
    title: str
    description: str | None
    priority: str
    is_done: bool
    deadline_date: date | None
    deadline_time: time | None
    created_at: datetime
    completed_at: datetime | None


def _order():
    return (Task.is_done.asc(), Task.created_at.desc())


@router.get("", response_model=list[TaskOut])
def list_tasks(principal: CurrentUser, user_id: uuid.UUID | None = None,
               kind: Literal["all", "assigned", "self"] = "all",
               everyone: bool = False, limit: int = Query(500, ge=1, le=2000)):
    """A user's tasks (default: your own). ``everyone=true`` lists the whole company (managers)."""
    tasks = TaskRepository(principal.session, principal.company_id)
    conditions = []
    if not (everyone and principal.is_manager):
        conditions.append(Task.user_id == target_user(principal, user_id).id)
    if kind == "assigned":
        conditions.append(Task.assigned_by.is_not(None))
    elif kind == "self":
        conditions.append(Task.assigned_by.is_(None))
    statement = tasks.query().where(*conditions).order_by(*_order()).limit(limit)
    return list(principal.session.scalars(statement))


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskIn, principal: CurrentUser):
    owner = target_user(principal, body.user_id)
    assigned_by = principal.user.id if owner.id != principal.user.id else None
    task = TaskRepository(principal.session, principal.company_id).add(
        user_id=owner.id, assigned_by=assigned_by, title=body.title, priority=body.priority,
        description=body.description, deadline_date=body.deadline_date,
        deadline_time=body.deadline_time if body.deadline_date else None)
    queue_urgent_task(principal.session, principal.company_id, task, principal.user)
    return task


def _editable(principal, task_id: uuid.UUID) -> Task:
    task = TaskRepository(principal.session, principal.company_id).get(task_id)
    if task is None or (not principal.is_manager and task.user_id != principal.user.id):
        raise NOT_FOUND
    return task


@router.post("/{task_id}/toggle", response_model=TaskOut)
def toggle(task_id: uuid.UUID, principal: CurrentUser):
    task = _editable(principal, task_id)
    done = not task.is_done
    return TaskRepository(principal.session, principal.company_id).update(
        task, is_done=done, completed_at=datetime.now(UTC) if done else None)


@router.patch("/{task_id}/deadline", response_model=TaskOut)
def set_deadline(task_id: uuid.UUID, body: DeadlineIn, principal: CurrentUser):
    task = _editable(principal, task_id)
    return TaskRepository(principal.session, principal.company_id).update(
        task, deadline_date=body.deadline_date,
        deadline_time=body.deadline_time if body.deadline_date else None)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(task_id: uuid.UUID, principal: CurrentUser):
    task = _editable(principal, task_id)
    if not principal.is_manager and task.assigned_by is not None:
        raise NOT_FOUND                     # an employee cannot delete an assigned task
    TaskRepository(principal.session, principal.company_id).delete(task)
