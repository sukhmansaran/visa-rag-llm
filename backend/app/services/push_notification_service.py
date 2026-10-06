"""
Push notification service using Firebase Cloud Messaging (FCM).
"""

from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class PushNotificationService:
    """Service for sending push notifications via FCM."""
    
    def __init__(self):
        self.fcm_server_key = getattr(settings, 'FCM_SERVER_KEY', '')
        self.fcm_url = "https://fcm.googleapis.com/fcm/send"
    
    async def send_notification(
        self,
        device_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send push notification to a single device.
        
        Args:
            device_token: FCM device token
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            True if successful, False otherwise
        """
        
        if not self.fcm_server_key:
            logger.warning("FCM_SERVER_KEY not configured, skipping push notification")
            return False
        
        payload = {
            "to": device_token,
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "badge": "1"
            },
            "priority": "high"
        }
        
        if data:
            payload["data"] = data
        
        headers = {
            "Authorization": f"key={self.fcm_server_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.fcm_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success") == 1:
                        logger.info(f"Push notification sent successfully to {device_token[:20]}...")
                        return True
                    else:
                        logger.error(f"FCM error: {result.get('results')}")
                        return False
                else:
                    logger.error(f"FCM request failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")
            return False
    
    async def send_notification_to_multiple(
        self,
        device_tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, int]:
        """
        Send push notification to multiple devices.
        
        Args:
            device_tokens: List of FCM device tokens
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            Dict with success and failure counts
        """
        
        if not self.fcm_server_key:
            logger.warning("FCM_SERVER_KEY not configured, skipping push notifications")
            return {"success": 0, "failure": len(device_tokens)}
        
        payload = {
            "registration_ids": device_tokens,
            "notification": {
                "title": title,
                "body": body,
                "sound": "default",
                "badge": "1"
            },
            "priority": "high"
        }
        
        if data:
            payload["data"] = data
        
        headers = {
            "Authorization": f"key={self.fcm_server_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.fcm_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    success_count = result.get("success", 0)
                    failure_count = result.get("failure", 0)
                    
                    logger.info(f"Push notifications sent: {success_count} success, {failure_count} failure")
                    
                    return {
                        "success": success_count,
                        "failure": failure_count
                    }
                else:
                    logger.error(f"FCM batch request failed: {response.status_code}")
                    return {"success": 0, "failure": len(device_tokens)}
                    
        except Exception as e:
            logger.error(f"Failed to send batch push notifications: {e}")
            return {"success": 0, "failure": len(device_tokens)}
    
    async def send_notification_to_topic(
        self,
        topic: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Send push notification to a topic.
        
        Args:
            topic: FCM topic name
            title: Notification title
            body: Notification body
            data: Optional data payload
            
        Returns:
            True if successful, False otherwise
        """
        
        if not self.fcm_server_key:
            logger.warning("FCM_SERVER_KEY not configured, skipping push notification")
            return False
        
        payload = {
            "to": f"/topics/{topic}",
            "notification": {
                "title": title,
                "body": body,
                "sound": "default"
            },
            "priority": "high"
        }
        
        if data:
            payload["data"] = data
        
        headers = {
            "Authorization": f"key={self.fcm_server_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.fcm_url,
                    json=payload,
                    headers=headers
                )
                
                if response.status_code == 200:
                    logger.info(f"Push notification sent to topic: {topic}")
                    return True
                else:
                    logger.error(f"FCM topic request failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Failed to send topic push notification: {e}")
            return False


# Global instance
push_notification_service = PushNotificationService()
