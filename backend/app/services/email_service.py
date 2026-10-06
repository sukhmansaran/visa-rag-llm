"""
Email notification service using SendGrid or SMTP.
"""

from typing import List, Dict, Any, Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jinja2 import Template

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger(__name__)


class EmailService:
    """Service for sending email notifications."""
    
    def __init__(self):
        self.smtp_host = getattr(settings, 'SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = getattr(settings, 'SMTP_PORT', 587)
        self.smtp_user = getattr(settings, 'SMTP_USER', '')
        self.smtp_password = getattr(settings, 'SMTP_PASSWORD', '')
        self.from_email = getattr(settings, 'FROM_EMAIL', 'noreply@pendu.app')
        self.from_name = getattr(settings, 'FROM_NAME', 'Pendu Visa Assistant')
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """
        Send email to a single recipient.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text fallback
            
        Returns:
            True if successful, False otherwise
        """
        
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email")
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{self.from_name} <{self.from_email}>"
            msg['To'] = to_email
            
            # Add text and HTML parts
            if text_content:
                part1 = MIMEText(text_content, 'plain')
                msg.attach(part1)
            
            part2 = MIMEText(html_content, 'html')
            msg.attach(part2)
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    async def send_change_alert_email(
        self,
        to_email: str,
        user_name: str,
        source_name: str,
        changes: str,
        source_url: str,
    ) -> bool:
        """
        Send change alert email.
        
        Args:
            to_email: Recipient email
            user_name: User's name
            source_name: Name of changed source
            changes: Description of changes
            source_url: URL to source
            
        Returns:
            True if successful
        """
        
        subject = f"🚨 Update Alert: {source_name}"
        
        html_content = self._render_change_alert_template(
            user_name=user_name,
            source_name=source_name,
            changes=changes,
            source_url=source_url,
        )
        
        text_content = f"""
Hi {user_name},

There's an important update to {source_name}:

{changes}

View the latest information: {source_url}

Stay informed with Pendu Visa Assistant.

---
To manage your notification preferences, visit your settings.
        """.strip()
        
        return await self.send_email(to_email, subject, html_content, text_content)
    
    async def send_document_ready_email(
        self,
        to_email: str,
        user_name: str,
        document_type: str,
        document_url: str,
    ) -> bool:
        """
        Send document ready notification email.
        
        Args:
            to_email: Recipient email
            user_name: User's name
            document_type: Type of document (SOP, etc.)
            document_url: URL to document
            
        Returns:
            True if successful
        """
        
        subject = f"✅ Your {document_type} is Ready!"
        
        html_content = self._render_document_ready_template(
            user_name=user_name,
            document_type=document_type,
            document_url=document_url,
        )
        
        text_content = f"""
Hi {user_name},

Great news! Your {document_type} has been generated and is ready for review.

View your document: {document_url}

Best regards,
Pendu Visa Assistant Team
        """.strip()
        
        return await self.send_email(to_email, subject, html_content, text_content)
    
    async def send_weekly_digest_email(
        self,
        to_email: str,
        user_name: str,
        notifications: List[Dict[str, Any]],
    ) -> bool:
        """
        Send weekly digest email.
        
        Args:
            to_email: Recipient email
            user_name: User's name
            notifications: List of notifications
            
        Returns:
            True if successful
        """
        
        subject = f"📊 Your Weekly Digest - {len(notifications)} Updates"
        
        html_content = self._render_weekly_digest_template(
            user_name=user_name,
            notifications=notifications,
        )
        
        return await self.send_email(to_email, subject, html_content)
    
    def _render_change_alert_template(
        self,
        user_name: str,
        source_name: str,
        changes: str,
        source_url: str,
    ) -> str:
        """Render change alert email template."""
        
        template = Template("""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #6750A4; color: white; padding: 20px; text-align: center; }
        .content { background: #f9f9f9; padding: 20px; margin: 20px 0; }
        .button { background: #6750A4; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; }
        .footer { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚨 Important Update</h1>
        </div>
        <div class="content">
            <p>Hi {{ user_name }},</p>
            <p>There's an important update to <strong>{{ source_name }}</strong>:</p>
            <p>{{ changes }}</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{{ source_url }}" class="button">View Latest Information</a>
            </p>
            <p>Stay informed and up-to-date with Pendu Visa Assistant.</p>
        </div>
        <div class="footer">
            <p>You're receiving this because you're watching {{ source_name }}.</p>
            <p>Manage your notification preferences in your account settings.</p>
        </div>
    </div>
</body>
</html>
        """)
        
        return template.render(
            user_name=user_name,
            source_name=source_name,
            changes=changes,
            source_url=source_url,
        )
    
    def _render_document_ready_template(
        self,
        user_name: str,
        document_type: str,
        document_url: str,
    ) -> str:
        """Render document ready email template."""
        
        template = Template("""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #4CAF50; color: white; padding: 20px; text-align: center; }
        .content { background: #f9f9f9; padding: 20px; margin: 20px 0; }
        .button { background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block; }
        .footer { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>✅ Document Ready!</h1>
        </div>
        <div class="content">
            <p>Hi {{ user_name }},</p>
            <p>Great news! Your <strong>{{ document_type }}</strong> has been generated and is ready for review.</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{{ document_url }}" class="button">View Your Document</a>
            </p>
            <p>You can now review, edit, and download your document.</p>
        </div>
        <div class="footer">
            <p>Pendu Visa Assistant - Your AI-powered study abroad companion</p>
        </div>
    </div>
</body>
</html>
        """)
        
        return template.render(
            user_name=user_name,
            document_type=document_type,
            document_url=document_url,
        )
    
    def _render_weekly_digest_template(
        self,
        user_name: str,
        notifications: List[Dict[str, Any]],
    ) -> str:
        """Render weekly digest email template."""
        
        template = Template("""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #2196F3; color: white; padding: 20px; text-align: center; }
        .content { background: #f9f9f9; padding: 20px; margin: 20px 0; }
        .notification { background: white; padding: 15px; margin: 10px 0; border-left: 4px solid #2196F3; }
        .footer { text-align: center; color: #666; font-size: 12px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Your Weekly Digest</h1>
        </div>
        <div class="content">
            <p>Hi {{ user_name }},</p>
            <p>Here's your weekly summary of {{ notifications|length }} updates:</p>
            {% for notif in notifications %}
            <div class="notification">
                <strong>{{ notif.title }}</strong>
                <p>{{ notif.message }}</p>
                <small>{{ notif.created_at }}</small>
            </div>
            {% endfor %}
        </div>
        <div class="footer">
            <p>Pendu Visa Assistant - Stay informed, stay ahead</p>
        </div>
    </div>
</body>
</html>
        """)
        
        return template.render(
            user_name=user_name,
            notifications=notifications,
        )


# Global instance
email_service = EmailService()
