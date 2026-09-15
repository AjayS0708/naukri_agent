from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.models.ai import AIUsage
from backend.schemas.ai import AIProviderStatus, AIStatusResponse


class AIService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def get_status(self) -> AIStatusResponse:
        # Check configuration
        if not self.settings.gemini_api_key:
            return AIStatusResponse(
                provider="gemini",
                status=AIProviderStatus.NOT_CONFIGURED,
                model=self.settings.gemini_model,
            )

        # Count usage
        total_requests = self.session.scalar(select(AIUsage).count()) or 0
        error_requests = self.session.scalar(
            select(AIUsage).where(AIUsage.status != "SUCCESS").count()
        ) or 0
        
        # Determine status (simplified check for QUOTA exhausted could look up recent errors)
        status = AIProviderStatus.AVAILABLE
        if error_requests > 0:
            recent_quota = self.session.scalar(
                select(AIUsage.id)
                .where(AIUsage.status == "QUOTA_EXHAUSTED")
                .order_by(AIUsage.created_at.desc())
                .limit(1)
            )
            if recent_quota:
                status = AIProviderStatus.QUOTA_EXHAUSTED
        
        return AIStatusResponse(
            provider="gemini",
            status=status,
            model=self.settings.gemini_model,
            requests=total_requests,
            errors=error_requests,
            cached=0,  # Phase 5 cache integration
        )
