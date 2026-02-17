import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AppRegion(Base):
    __tablename__ = "app_regions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    app_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    region: Mapped[str] = mapped_column(String(50), nullable=False)

    application = relationship("Application", back_populates="regions")

    __table_args__ = (UniqueConstraint("app_id", "region"),)
