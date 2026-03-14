"""Saved research routes — save, list, load, update, delete research trees."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ui.backend.auth.db import get_async_session
from ui.backend.auth.models import SavedResearch, User
from ui.backend.auth.schemas import (
    SavedResearchCreate,
    SavedResearchListItem,
    SavedResearchRead,
    SavedResearchUpdate,
)
from ui.backend.auth.users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _count_nodes(tree: dict) -> int:
    """Recursively count nodes in a drilldown tree dict."""
    count = 1
    for child in tree.get("children", []):
        count += _count_nodes(child)
    return count


def _to_list_item(research: SavedResearch) -> SavedResearchListItem:
    """Convert ORM object to list item (no tree data)."""
    return SavedResearchListItem(
        id=research.id,
        title=research.title,
        query=research.query,
        data_source=research.data_source,
        node_count=_count_nodes(research.drilldown_tree),
        created_at=research.created_at,
        updated_at=research.updated_at,
    )


@router.post("/", response_model=SavedResearchRead, tags=["research"])
async def save_research(
    body: SavedResearchCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Save a new research tree."""
    research = SavedResearch(
        user_id=user.id,
        title=body.title,
        query=body.query,
        filters=body.filters,
        data_source=body.data_source,
        drilldown_tree=body.drilldown_tree,
    )
    session.add(research)
    await session.commit()
    await session.refresh(research)
    return SavedResearchRead.model_validate(research)


@router.get("/", tags=["research"])
async def list_research(
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List all saved research for the current user (compact, no tree data)."""
    result = await session.execute(
        select(SavedResearch)
        .where(SavedResearch.user_id == user.id)
        .order_by(SavedResearch.updated_at.desc())
    )
    items = result.scalars().all()
    return [_to_list_item(r) for r in items]


@router.get("/{research_id}", response_model=SavedResearchRead, tags=["research"])
async def get_research(
    research_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Load a single saved research with full tree."""
    result = await session.execute(
        select(SavedResearch).where(
            SavedResearch.id == research_id,
            SavedResearch.user_id == user.id,
        )
    )
    research = result.scalars().first()
    if not research:
        raise HTTPException(status_code=404, detail="Research not found")
    return SavedResearchRead.model_validate(research)


@router.put("/{research_id}", response_model=SavedResearchRead, tags=["research"])
async def update_research(
    research_id: uuid.UUID,
    body: SavedResearchUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update an existing saved research."""
    result = await session.execute(
        select(SavedResearch).where(
            SavedResearch.id == research_id,
            SavedResearch.user_id == user.id,
        )
    )
    research = result.scalars().first()
    if not research:
        raise HTTPException(status_code=404, detail="Research not found")
    if body.title is not None:
        research.title = body.title
    if body.drilldown_tree is not None:
        research.drilldown_tree = body.drilldown_tree
    if body.filters is not None:
        research.filters = body.filters
    await session.commit()
    await session.refresh(research)
    return SavedResearchRead.model_validate(research)


@router.delete("/{research_id}", status_code=204, tags=["research"])
async def delete_research(
    research_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a saved research."""
    result = await session.execute(
        select(SavedResearch).where(
            SavedResearch.id == research_id,
            SavedResearch.user_id == user.id,
        )
    )
    research = result.scalars().first()
    if not research:
        raise HTTPException(status_code=404, detail="Research not found")
    await session.delete(research)
    await session.commit()
