"""
Модели БД: Order, TechProcess, Task, Operation, Worker, Equipment.

MVP планирования: у Task — sequence_number, duration_minutes, profession, equipment_model
(сопоставление с Worker.profession и Equipment.model); у Order — profit и окно planned_start/planned_end;
у Operation — фактические worker_id, equipment_id, start_time, end_time после расчёта.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from backend.database import Base


class TechProcess(Base):
    """Технологический процесс (последовательность операций)."""
    __tablename__ = "tech_processes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)

    tasks = relationship("Task", back_populates="tech_process", order_by="Task.sequence_number")
    orders = relationship("Order", back_populates="tech_process")


class Task(Base):
    """Операция в технологическом процессе (шаблон)."""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    tech_process_id = Column(
        Integer, ForeignKey("tech_processes.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number = Column(Integer, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    profession = Column(String(100), nullable=False)
    equipment_model = Column(String(100), nullable=False)
    name = Column(String(255), nullable=True)

    tech_process = relationship("TechProcess", back_populates="tasks")
    scheduled_operations = relationship("Operation", back_populates="task")


class Order(Base):
    """Заказ на производство: прибыль при полном включении и желаемое окно дат (UTC)."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    profit = Column(Numeric(12, 2), nullable=False)
    planned_start = Column(DateTime(timezone=True), nullable=False)
    planned_end = Column(DateTime(timezone=True), nullable=False)
    tech_process_id = Column(
        Integer, ForeignKey("tech_processes.id", ondelete="RESTRICT"), nullable=False
    )

    tech_process = relationship("TechProcess", back_populates="orders")
    operations = relationship("Operation", back_populates="order")


class Worker(Base):
    """Рабочий."""
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    profession = Column(String(100), nullable=False)

    operations = relationship("Operation", back_populates="worker")


class Equipment(Base):
    """Оборудование."""
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    model = Column(String(100), nullable=False)

    operations = relationship("Operation", back_populates="equipment")


class Operation(Base):
    """Запланированная операция (привязка к рабочему и оборудованию, время)."""
    __tablename__ = "operations"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    task_id = Column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    worker_id = Column(
        Integer, ForeignKey("workers.id", ondelete="RESTRICT"), nullable=False
    )
    equipment_id = Column(
        Integer, ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False
    )
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)

    order = relationship("Order", back_populates="operations")
    task = relationship("Task", back_populates="scheduled_operations")
    worker = relationship("Worker", back_populates="operations")
    equipment = relationship("Equipment", back_populates="operations")
