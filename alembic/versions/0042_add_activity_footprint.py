"""Store each activity's estimated environmental footprint.

The recorder estimates every LLM call's energy, greenhouse gas emissions and
water with EcoLogits as it records the call's usage, and adds them up on the
activity row like its cost: each as a min and a max, because EcoLogits gives
ranges. Each row also records which models its estimate rests on, so the
admin screen can show every figure's source and flag assumptions, and counts
the output tokens of calls with no estimate.
Existing rows stay empty: their calls can't be split by model afterwards.

Revision ID: 0042_add_activity_footprint
Revises: 0041_add_ai_daily_spend
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0042_add_activity_footprint"
down_revision = "0041_add_ai_daily_spend"
branch_labels = None
depends_on = None

_FLOAT_COLUMNS = (
    "energy_kwh_min",
    "energy_kwh_max",
    "gwp_kgco2eq_min",
    "gwp_kgco2eq_max",
    "water_l_min",
    "water_l_max",
)


def upgrade() -> None:
    for name in _FLOAT_COLUMNS:
        op.add_column("user_activity", sa.Column(name, sa.Float(), nullable=True))
    op.add_column(
        "user_activity",
        sa.Column("footprint_unestimated_tokens", sa.Integer(), nullable=True),
    )
    # Each estimated model's output tokens: what the row's figures rest on.
    op.add_column("user_activity", sa.Column("footprint_basis", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_activity", "footprint_basis")
    op.drop_column("user_activity", "footprint_unestimated_tokens")
    for name in reversed(_FLOAT_COLUMNS):
        op.drop_column("user_activity", name)
