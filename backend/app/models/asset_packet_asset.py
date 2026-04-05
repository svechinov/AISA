"""Junction: which library assets belong to an asset packet (canonical; ``packet_json`` does not store the list)."""

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AssetPacketAsset(Base):
    __tablename__ = "asset_packet_assets"
    __table_args__ = (UniqueConstraint("packet_id", "asset_id", name="uq_asset_packet_assets_packet_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    packet_id: Mapped[int] = mapped_column(
        ForeignKey("asset_packets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Order within the packet (API exposes this order as ``AssetPacketRead.assets``).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
