"""
Change detection service for monitoring source updates.
"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.models.source import Source
from app.models.document import Document
from app.models.change import Change
from app.models.watchlist import Watchlist
from app.services.scraper import scrape_with_retry
from app.services.llm import llm_service


class ChangeDetector:
    """Detects and analyzes changes in scraped content."""
    
    async def detect_change(
        self,
        source_id: int,
        db: AsyncSession,
    ) -> Optional[Change]:
        """
        Detect if a source has changed since last scrape.
        
        Args:
            source_id: Source to check
            db: Database session
            
        Returns:
            Change object if change detected, None otherwise
        """
        # Get source
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        
        if not source or not source.is_active:
            return None
        
        # Get latest document
        result = await db.execute(
            select(Document)
            .where(Document.source_id == source_id)
            .order_by(desc(Document.scraped_at))
            .limit(1)
        )
        old_document = result.scalar_one_or_none()
        
        # Scrape current version
        try:
            scraped_data = await scrape_with_retry(source.url)
        except Exception as e:
            print(f"Error scraping {source.url}: {e}")
            return None
        
        new_hash = scraped_data['content_hash']
        
        # No previous document - not a change
        if not old_document:
            return None
        
        old_hash = old_document.content_hash
        
        # No change detected
        if old_hash == new_hash:
            return None
        
        # Change detected! Create new document
        new_document = Document(
            source_id=source_id,
            content_hash=new_hash,
            raw_html=scraped_data.get('raw_html'),
            extracted_text=scraped_data['extracted_text'],
        )
        db.add(new_document)
        await db.commit()
        await db.refresh(new_document)
        
        # Generate diff summary using LLM
        diff_summary = await self._generate_diff_summary(
            old_text=old_document.extracted_text,
            new_text=new_document.extracted_text,
            source_name=source.name,
        )
        
        # Determine severity
        severity = self._determine_severity(diff_summary, source.source_type)
        
        # Create change record
        change = Change(
            source_id=source_id,
            old_hash=old_hash,
            new_hash=new_hash,
            diff_summary=diff_summary,
            severity=severity,
        )
        db.add(change)
        
        # Update source last_scraped_at
        source.last_scraped_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(change)
        
        return change
    
    async def identify_affected_users(
        self,
        change: Change,
        db: AsyncSession,
    ) -> List[int]:
        """
        Identify users affected by a change based on watchlist.
        
        Args:
            change: Change object
            db: Database session
            
        Returns:
            List of affected user IDs
        """
        # Get source details
        result = await db.execute(select(Source).where(Source.id == change.source_id))
        source = result.scalar_one_or_none()
        
        if not source:
            return []
        
        # Find users watching this country or specific source
        affected_users = set()
        
        # Users watching this country
        if source.country:
            result = await db.execute(
                select(Watchlist.user_id)
                .where(Watchlist.watched_type == "country")
                .where(Watchlist.watched_value == source.country)
            )
            country_watchers = result.scalars().all()
            affected_users.update(country_watchers)
        
        # Users watching this specific university/source
        result = await db.execute(
            select(Watchlist.user_id)
            .where(Watchlist.watched_type.in_(["university", "source"]))
            .where(Watchlist.watched_value == source.name)
        )
        specific_watchers = result.scalars().all()
        affected_users.update(specific_watchers)
        
        return list(affected_users)
    
    async def _generate_diff_summary(
        self,
        old_text: str,
        new_text: str,
        source_name: str,
    ) -> str:
        """
        Generate human-readable summary of changes using LLM.
        
        Args:
            old_text: Old content
            new_text: New content
            source_name: Name of source
            
        Returns:
            Summary of changes
        """
        # Simple diff for very short texts
        if len(old_text) < 100 or len(new_text) < 100:
            return f"Content updated on {source_name}"
        
        # Use LLM to summarize changes
        from app.services.llm import llm_service

        prompt = f"""Compare these two versions of content from {source_name} and summarize the key changes in 2-3 sentences:

OLD VERSION (first 1000 chars):
{old_text[:1000]}

NEW VERSION (first 1000 chars):
{new_text[:1000]}

Focus on:
- New requirements or rules
- Changed deadlines or dates
- Modified processes
- Important updates

Summary:"""

        try:
            summary = await llm_service.generate_answer(
                system_prompt="You summarize changes in visa and university policy documents concisely.",
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=200,
            )
            return summary
        
        except Exception as e:
            print(f"Error generating diff summary: {e}")
            return f"Content updated on {source_name}. Please review the changes."
    
    def _determine_severity(self, diff_summary: str, source_type: str) -> str:
        """
        Determine severity of change based on content and source type.
        
        Returns: low, medium, high, or critical
        """
        summary_lower = diff_summary.lower()
        
        # Critical indicators
        if any(word in summary_lower for word in ["deadline", "closed", "no longer", "required", "mandatory"]):
            return "high"
        
        # Embassy/official sources are more important
        if source_type in ["embassy", "official"]:
            if any(word in summary_lower for word in ["new", "updated", "changed"]):
                return "medium"
        
        # Default to low
        return "low"


# Global instance
change_detector = ChangeDetector()
