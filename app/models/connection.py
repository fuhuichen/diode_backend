import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id"), nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_keepalive: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application = relationship("Application")
    node = relationship("Node")

    __table_args__ = (
        Index("idx_connections_app_active", "app_id", postgresql_where=(status == "active")),
        Index("idx_connections_last_keepalive", "last_keepalive", postgresql_where=(status == "active")),
    )
