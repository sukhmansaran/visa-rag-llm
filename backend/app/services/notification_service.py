"""
Notification service for creating and sending notifications.
"""

from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.user import User
from app.models.profile import Profile
from sqlalchemy import select


class NotificationService:
    """Create and send notifications to users."""
    
    async def create_notification(
        self,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        related_url: Optional[str] = None,
        db: AsyncSession = None,
    ) -> Notification:
        """
        Create a notification for a user.
        
        Args:
            user_id: User ID
            title: Notification title
            message: Notification message
            notification_type: Type (change_alert, reminder, system, review_complete)
            related_url: Optional related URL
            db: Database session
            
        Returns:
            Created notification
        """
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            related_url=related_url,
        )
        
        if db:
            db.add(notification)
            await db.commit()
            await db.refresh(notification)
        
        return notification
    
    async def send_push_notification(
        self,
        user_id: int,
        notification: Notification,
        db: AsyncSession,
    ):
        """
        Send push notification via FCM.
        
        Args:
            user_id: User ID
            notification: Notification object
            db: Database session
        """
        from app.services.push_notification_service import push_notification_service
        
        # Get user and check push preferences
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            return
        
        # Get profile for preferences
        result = await db.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        
        if profile and not profile.notification_preferences.get('push', True):
            return  # User has disabled push notifications
        
        # Get FCM tokens (stored in user metadata for now)
        fcm_tokens = getattr(user, 'fcm_tokens', None)
        if not fcm_tokens:
            return  # No FCM tokens registered
        
        # Prepare notification data
        data = {
            'notification_id': str(notification.id),
            'type': notification.notification_type,
        }
        if notification.related_url:
            data['url'] = notification.related_url
        
        # Send to all user's devices
        for token in fcm_tokens:
            await push_notification_service.send_notification(
                device_token=token,
                title=notification.title,
                body=notification.message,
                data=data
            )
    
    async def notify_users_of_change(
        self,
        user_ids: List[int],
        source_name: str,
        diff_summary: str,
        source_url: str,
        severity: str,
        db: AsyncSession,
    ):
        """
        Notify multiple users of a source change.
        
        Args:
            user_ids: List of user IDs to notify
            source_name: Name of changed source
            diff_summary: Summary of changes
            source_url: URL of source
            severity: Change severity
            db: Database session
        """
        # Create title based on severity
        severity_emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "📢",
            "low": "ℹ️",
        }
        emoji = severity_emoji.get(severity, "📢")
        
        title = f"{emoji} Update: {source_name}"
        message = f"{diff_summary}\n\nCheck the latest information to stay informed."
        
        for user_id in user_ids:
            # Create notification
            notification = await self.create_notification(
                user_id=user_id,
                title=title,
                message=message,
                notification_type="change_alert",
                related_url=source_url,
                db=db,
            )
            
            # Send push notification
            await self.send_push_notification(user_id, notification, db)


# Global instance
notification_service = NotificationService()
