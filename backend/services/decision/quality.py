import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.models.feedback import JobFeedback, DecisionQualityRecord
from backend.models.application import Application
from backend.schemas.decision import (
    DecisionQuality, DecisionPriority, DecisionReasonCode, DecisionSignal
)
from backend.schemas.ai import JobQuality
from backend.services.matching.normalizer import (
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed
)
from backend.core.logging import get_logger

logger = get_logger(__name__)


class DecisionQualityService:
    """
    Provides deterministic decision quality assessment and prioritization.
    Hard filters remain authoritative; AI recommendations are advisory only.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def evaluate_job_decision(
        self,
        job: Job,
        profile: Profile,
        preference: JobPreference,
        job_analysis: Optional[JobAnalysisModel] = None
    ) -> DecisionQuality:
        """
        Evaluate a job's decision quality with explainable reasoning.
        Returns a comprehensive DecisionQuality assessment.
        """
        signals = []
        reason_codes = []
        
        # Initialize scores
        role_relevance = 0.0
        skill_relevance = 0.0
        experience_compatibility = 0.0
        location_match = 0.0
        salary_suitability = 0.0
        job_quality = 0.0
        freshness = 0.0
        duplicate_prob = 0.0
        suspicious_prob = 0.0
        feedback_adjustment = 0.0
        
        hard_filter_failed = False
        primary_reason = DecisionReasonCode.UNKNOWN
        
        # 1. Profile confirmation check (hard filter)
        if not profile.confirmed:
            hard_filter_failed = True
            primary_reason = DecisionReasonCode.PROFILE_NOT_CONFIRMED
            reason_codes.append(DecisionReasonCode.PROFILE_NOT_CONFIRMED)
            return DecisionQuality(
                priority=DecisionPriority.HARD_REJECT,
                decision_score=0,
                role_relevance_score=0,
                skill_relevance_score=0,
                experience_compatibility_score=0,
                location_match_score=0,
                salary_suitability_score=0,
                job_quality_score=0,
                freshness_score=0,
                duplicate_probability=0,
                suspicious_probability=0,
                feedback_adjustment=0,
                primary_reason_code=primary_reason,
                reason_codes=reason_codes,
                explanation="Profile is not confirmed by user",
                hard_filter_failed=True,
                signals=signals
            )
        
        # 2. Location hard filter
        if job.location and preference.locations:
            location_ok = has_overlapping_location(job.location, preference.locations)
            location_match = 1.0 if location_ok else 0.0
            signals.append(DecisionSignal(
                signal_type="location_match",
                value=location_match,
                weight=2.0,  # High weight for hard filter
                reason=f"Location match: {location_ok}"
            ))
            
            if not location_ok:
                hard_filter_failed = True
                primary_reason = DecisionReasonCode.LOCATION_MISMATCH
                reason_codes.append(DecisionReasonCode.LOCATION_MISMATCH)
                return DecisionQuality(
                    priority=DecisionPriority.HARD_REJECT,
                    decision_score=0,
                    role_relevance_score=0,
                    skill_relevance_score=0,
                    experience_compatibility_score=0,
                    location_match_score=location_match,
                    salary_suitability_score=0,
                    job_quality_score=0,
                    freshness_score=0,
                    duplicate_probability=0,
                    suspicious_probability=0,
                    feedback_adjustment=0,
                    primary_reason_code=primary_reason,
                    reason_codes=reason_codes,
                    explanation=f"Location mismatch: job location '{job.location}' not in allowed locations",
                    hard_filter_failed=True,
                    signals=signals
                )
        
        # 3. Experience hard filter
        if job.experience:
            exp_min, exp_max = extract_experience_years(job.experience)
            if exp_min is not None:
                user_exp_years = len(profile.data.get("experience", [])) if isinstance(profile.data, dict) else 0
                # Check if required experience exceeds user experience (with 2-year grace)
                if exp_min > user_exp_years + 2:
                    experience_compatibility = 0.0
                    hard_filter_failed = True
                    primary_reason = DecisionReasonCode.EXPERIENCE_TOO_HIGH
                    reason_codes.append(DecisionReasonCode.EXPERIENCE_TOO_HIGH)
                    signals.append(DecisionSignal(
                        signal_type="experience_compatibility",
                        value=0.0,
                        weight=2.0,
                        reason=f"Required experience ({exp_min}y) exceeds user profile ({user_exp_years}y)"
                    ))
                    return DecisionQuality(
                        priority=DecisionPriority.HARD_REJECT,
                        decision_score=0,
                        role_relevance_score=0,
                        skill_relevance_score=0,
                        experience_compatibility_score=0,
                        location_match_score=location_match,
                        salary_suitability_score=0,
                        job_quality_score=0,
                        freshness_score=0,
                        duplicate_probability=0,
                        suspicious_probability=0,
                        feedback_adjustment=0,
                        primary_reason_code=primary_reason,
                        reason_codes=reason_codes,
                        explanation=f"Experience required ({exp_min}y) exceeds user profile ({user_exp_years}y)",
                        hard_filter_failed=True,
                        signals=signals
                    )
                else:
                    # Calculate compatibility score
                    experience_compatibility = min(1.0, user_exp_years / max(exp_min, 1))
                    signals.append(DecisionSignal(
                        signal_type="experience_compatibility",
                        value=experience_compatibility,
                        weight=1.5,
                        reason=f"Experience compatibility: {experience_compatibility:.2f}"
                    ))
        
        # 4. Salary hard filter
        if job.salary and preference.min_salary_lpa is not None:
            salary_lpa = extract_lowest_salary_lpa(job.salary)
            if salary_lpa is not None:
                if salary_lpa < preference.min_salary_lpa:
                    salary_suitability = 0.0
                    hard_filter_failed = True
                    primary_reason = DecisionReasonCode.SALARY_BELOW_MINIMUM
                    reason_codes.append(DecisionReasonCode.SALARY_BELOW_MINIMUM)
                    signals.append(DecisionSignal(
                        signal_type="salary_suitability",
                        value=0.0,
                        weight=2.0,
                        reason=f"Salary ({salary_lpa} LPA) below minimum ({preference.min_salary_lpa} LPA)"
                    ))
                    return DecisionQuality(
                        priority=DecisionPriority.HARD_REJECT,
                        decision_score=0,
                        role_relevance_score=0,
                        skill_relevance_score=0,
                        experience_compatibility_score=experience_compatibility,
                        location_match_score=location_match,
                        salary_suitability_score=0,
                        job_quality_score=0,
                        freshness_score=0,
                        duplicate_probability=0,
                        suspicious_probability=0,
                        feedback_adjustment=0,
                        primary_reason_code=primary_reason,
                        reason_codes=reason_codes,
                        explanation=f"Salary ({salary_lpa} LPA) below minimum ({preference.min_salary_lpa} LPA)",
                        hard_filter_failed=True,
                        signals=signals
                    )
                else:
                    # Calculate suitability score (bonus for higher salaries)
                    salary_suitability = min(1.0, salary_lpa / (preference.min_salary_lpa * 1.5))
                    signals.append(DecisionSignal(
                        signal_type="salary_suitability",
                        value=salary_suitability,
                        weight=1.0,
                        reason=f"Salary suitability: {salary_suitability:.2f}"
                    ))
                    if salary_lpa >= preference.min_salary_lpa * 1.5:
                        reason_codes.append(DecisionReasonCode.HIGH_SALARY)
        
        # 5. Employment type hard filter
        if job.employment_type and preference.employment_types:
            employment_ok = is_employment_type_allowed(job.employment_type, preference.employment_types)
            if not employment_ok:
                hard_filter_failed = True
                primary_reason = DecisionReasonCode.EMPLOYMENT_TYPE_NOT_ALLOWED
                reason_codes.append(DecisionReasonCode.EMPLOYMENT_TYPE_NOT_ALLOWED)
                return DecisionQuality(
                    priority=DecisionPriority.HARD_REJECT,
                    decision_score=0,
                    role_relevance_score=0,
                    skill_relevance_score=0,
                    experience_compatibility_score=experience_compatibility,
                    location_match_score=location_match,
                    salary_suitability_score=salary_suitability,
                    job_quality_score=0,
                    freshness_score=0,
                    duplicate_probability=0,
                    suspicious_probability=0,
                    feedback_adjustment=0,
                    primary_reason_code=primary_reason,
                    reason_codes=reason_codes,
                    explanation=f"Employment type '{job.employment_type}' not allowed",
                    hard_filter_failed=True,
                    signals=signals
                )
        
        # 6. Job title scope check
        if preference.job_titles and job.title:
            title_match = any(
                title.lower() in job.title.lower() 
                for title in preference.job_titles
            )
            if not title_match:
                hard_filter_failed = True
                primary_reason = DecisionReasonCode.OUTSIDE_SEARCH_SCOPE
                reason_codes.append(DecisionReasonCode.OUTSIDE_SEARCH_SCOPE)
                return DecisionQuality(
                    priority=DecisionPriority.HARD_REJECT,
                    decision_score=0,
                    role_relevance_score=0,
                    skill_relevance_score=0,
                    experience_compatibility_score=experience_compatibility,
                    location_match_score=location_match,
                    salary_suitability_score=salary_suitability,
                    job_quality_score=0,
                    freshness_score=0,
                    duplicate_probability=0,
                    suspicious_probability=0,
                    feedback_adjustment=0,
                    primary_reason_code=primary_reason,
                    reason_codes=reason_codes,
                    explanation=f"Job title '{job.title}' not in configured search scope",
                    hard_filter_failed=True,
                    signals=signals
                )
            else:
                role_relevance = 1.0
                signals.append(DecisionSignal(
                    signal_type="role_relevance",
                    value=1.0,
                    weight=2.0,
                    reason=f"Title matches search scope"
                ))
                reason_codes.append(DecisionReasonCode.STRONG_MATCH)
        
        # 7. Duplicate check
        duplicate = self._check_duplicate(job)
        duplicate_prob = 1.0 if duplicate else 0.0
        signals.append(DecisionSignal(
            signal_type="duplicate_probability",
            value=duplicate_prob,
            weight=3.0,  # Very high weight for duplicates
            reason=f"Duplicate check: {duplicate}"
        ))
        
        if duplicate:
            hard_filter_failed = True
            primary_reason = DecisionReasonCode.DUPLICATE_JOB
            reason_codes.append(DecisionReasonCode.DUPLICATE_JOB)
            return DecisionQuality(
                priority=DecisionPriority.HARD_REJECT,
                decision_score=0,
                role_relevance_score=role_relevance,
                skill_relevance_score=0,
                experience_compatibility_score=experience_compatibility,
                location_match_score=location_match,
                salary_suitability_score=salary_suitability,
                job_quality_score=0,
                freshness_score=0,
                duplicate_probability=duplicate_prob,
                suspicious_probability=0,
                feedback_adjustment=0,
                primary_reason_code=primary_reason,
                reason_codes=reason_codes,
                explanation="Job already processed or applied to",
                hard_filter_failed=True,
                signals=signals
            )
        
        # 8. AI Analysis integration (if available)
        if job_analysis:
            role_relevance = job_analysis.role_match * 1.0 if job_analysis.role_match else role_relevance
            skill_relevance = 1.0 if job_analysis.skill_match else 0.5
            job_quality = self._quality_to_score(job_analysis.job_quality)
            duplicate_prob = job_analysis.duplicate_probability
            suspicious_prob = 1.0 if job_analysis.suspicious else 0.0
            
            signals.append(DecisionSignal(
                signal_type="ai_role_match",
                value=1.0 if job_analysis.role_match else 0.0,
                weight=1.5,
                reason=f"AI role match: {job_analysis.role_match}"
            ))
            signals.append(DecisionSignal(
                signal_type="ai_skill_match",
                value=1.0 if job_analysis.skill_match else 0.0,
                weight=1.0,
                reason=f"AI skill match: {job_analysis.skill_match}"
            ))
            signals.append(DecisionSignal(
                signal_type="ai_job_quality",
                value=job_quality,
                weight=1.0,
                reason=f"AI job quality: {job_analysis.job_quality}"
            ))
            
            if job_analysis.suspicious:
                hard_filter_failed = True
                primary_reason = DecisionReasonCode.SUSPICIOUS_JOB
                reason_codes.append(DecisionReasonCode.SUSPICIOUS_JOB)
                return DecisionQuality(
                    priority=DecisionPriority.HARD_REJECT,
                    decision_score=0,
                    role_relevance_score=role_relevance,
                    skill_relevance_score=skill_relevance,
                    experience_compatibility_score=experience_compatibility,
                    location_match_score=location_match,
                    salary_suitability_score=salary_suitability,
                    job_quality_score=job_quality,
                    freshness_score=0,
                    duplicate_probability=duplicate_prob,
                    suspicious_probability=suspicious_prob,
                    feedback_adjustment=0,
                    primary_reason_code=primary_reason,
                    reason_codes=reason_codes,
                    explanation="Job flagged as suspicious by AI analysis",
                    hard_filter_failed=True,
                    signals=signals
                )
        else:
            # No AI analysis - use heuristics
            skill_relevance = 0.7  # Default moderate score
            job_quality = 0.7  # Default moderate score
        
        # 9. Freshness calculation
        if job.posted_at:
            # Ensure both datetimes are timezone-aware
            now = datetime.now(UTC)
            posted_at = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=UTC)
            days_old = (now - posted_at).days
            freshness = max(0.0, 1.0 - (days_old / 30.0))  # Decay over 30 days
            signals.append(DecisionSignal(
                signal_type="freshness",
                value=freshness,
                weight=0.5,
                reason=f"Job is {days_old} days old"
            ))
            if days_old <= 3:
                reason_codes.append(DecisionReasonCode.FRESH_JOB)
        
        # 10. Historical feedback integration
        feedback_adjustment = self._get_feedback_adjustment(job.id)
        if feedback_adjustment != 0:
            signals.append(DecisionSignal(
                signal_type="feedback_adjustment",
                value=feedback_adjustment,
                weight=1.0,
                reason=f"Feedback adjustment: {feedback_adjustment:.2f}"
            ))
            if feedback_adjustment > 0:
                reason_codes.append(DecisionReasonCode.PREVIOUS_POSITIVE_FEEDBACK)
        
        # 11. Calculate final decision score
        decision_score = self._calculate_decision_score(
            role_relevance=role_relevance,
            skill_relevance=skill_relevance,
            experience_compatibility=experience_compatibility,
            location_match=location_match,
            salary_suitability=salary_suitability,
            job_quality=job_quality,
            freshness=freshness,
            duplicate_prob=duplicate_prob,
            suspicious_prob=suspicious_prob,
            feedback_adjustment=feedback_adjustment
        )
        
        # 12. Determine priority
        priority = self._determine_priority(decision_score, reason_codes, suspicious_prob)
        
        # 13. Generate explanation
        explanation = self._generate_explanation(
            priority, reason_codes, job, decision_score
        )
        
        # 14. Set primary reason
        if not primary_reason or primary_reason == DecisionReasonCode.UNKNOWN:
            primary_reason = reason_codes[0] if reason_codes else DecisionReasonCode.STRONG_MATCH
        
        return DecisionQuality(
            priority=priority,
            decision_score=decision_score,
            role_relevance_score=role_relevance,
            skill_relevance_score=skill_relevance,
            experience_compatibility_score=experience_compatibility,
            location_match_score=location_match,
            salary_suitability_score=salary_suitability,
            job_quality_score=job_quality,
            freshness_score=freshness,
            duplicate_probability=duplicate_prob,
            suspicious_probability=suspicious_prob,
            feedback_adjustment=feedback_adjustment,
            primary_reason_code=primary_reason,
            reason_codes=reason_codes,
            explanation=explanation,
            hard_filter_failed=hard_filter_failed,
            requires_ai_analysis=job_analysis is None,
            ai_available=job_analysis is not None,
            signals=signals
        )
    
    def _check_duplicate(self, job: Job) -> bool:
        """Check if job is a duplicate."""
        if not job.url:
            return False
        
        # Check for existing applications
        stmt = select(Application).where(
            Application.job_id == job.id,
            Application.status.in_(["APPLIED", "SUBMITTED"])
        )
        existing_app = self.session.execute(stmt).first()
        if existing_app:
            return True
        
        # Check for duplicate URLs
        stmt = select(Job).where(Job.url == job.url)
        if job.id is not None:
            stmt = stmt.where(Job.id != job.id)
        duplicate = self.session.execute(stmt).first()
        return duplicate is not None
    
    def _quality_to_score(self, quality: str) -> float:
        """Convert job quality enum to score."""
        quality_map = {
            "GOOD": 1.0,
            "AVERAGE": 0.7,
            "LOW": 0.4,
            "SUSPICIOUS": 0.0
        }
        return quality_map.get(quality, 0.5)
    
    def _get_feedback_adjustment(self, job_id: int) -> float:
        """Get feedback adjustment score for a job."""
        stmt = select(JobFeedback).where(JobFeedback.job_id == job_id)
        feedbacks = self.session.execute(stmt).scalars().all()
        
        if not feedbacks:
            return 0.0
        
        adjustment = 0.0
        for feedback in feedbacks:
            if feedback.feedback_type in ["RELEVANT", "GOOD_MATCH", "APPLIED"]:
                adjustment += 0.2
            elif feedback.feedback_type in ["NOT_RELEVANT", "INCORRECT_MATCH", "SKIPPED"]:
                adjustment -= 0.3
        
        # Clamp adjustment to [-1, 1]
        return max(-1.0, min(1.0, adjustment))
    
    def _calculate_decision_score(
        self,
        role_relevance: float,
        skill_relevance: float,
        experience_compatibility: float,
        location_match: float,
        salary_suitability: float,
        job_quality: float,
        freshness: float,
        duplicate_prob: float,
        suspicious_prob: float,
        feedback_adjustment: float
    ) -> float:
        """
        Calculate final decision score (0-100).
        Uses weighted combination of signals.
        """
        # Weighted sum
        weighted_sum = (
            role_relevance * 25.0 +      # High weight for role match
            skill_relevance * 20.0 +     # High weight for skill match
            experience_compatibility * 15.0 +
            location_match * 15.0 +
            salary_suitability * 10.0 +
            job_quality * 10.0 +
            freshness * 5.0
        )
        
        # Apply penalties
        if duplicate_prob > 0.5:
            weighted_sum *= (1.0 - duplicate_prob)
        
        if suspicious_prob > 0.5:
            weighted_sum *= (1.0 - suspicious_prob)
        
        # Apply feedback adjustment
        weighted_sum += feedback_adjustment * 20.0
        
        # Clamp to 0-100
        return max(0.0, min(100.0, weighted_sum))
    
    def _determine_priority(
        self,
        decision_score: float,
        reason_codes: list[DecisionReasonCode],
        suspicious_prob: float
    ) -> DecisionPriority:
        """Determine priority level based on score and factors."""
        # Check for needs attention cases
        if DecisionReasonCode.REQUIRES_MANUAL_REVIEW in reason_codes:
            return DecisionPriority.NEEDS_ATTENTION
        
        if suspicious_prob > 0.7:
            return DecisionPriority.NEEDS_ATTENTION
        
        # Determine priority based on score
        if decision_score >= 80:
            return DecisionPriority.HIGH_PRIORITY
        elif decision_score >= 60:
            return DecisionPriority.NORMAL_PRIORITY
        elif decision_score >= 40:
            return DecisionPriority.LOW_PRIORITY
        elif decision_score >= 20:
            return DecisionPriority.SKIP
        else:
            return DecisionPriority.SKIP
    
    def _generate_explanation(
        self,
        priority: DecisionPriority,
        reason_codes: list[DecisionReasonCode],
        job: Job,
        decision_score: float
    ) -> str:
        """Generate concise human-readable explanation."""
        if priority == DecisionPriority.HARD_REJECT:
            if DecisionReasonCode.LOCATION_MISMATCH in reason_codes:
                return f"Location mismatch: job is in {job.location or 'unknown location'}"
            elif DecisionReasonCode.EXPERIENCE_TOO_HIGH in reason_codes:
                return f"Experience requirement exceeds profile"
            elif DecisionReasonCode.SALARY_BELOW_MINIMUM in reason_codes:
                return f"Salary below minimum requirement"
            elif DecisionReasonCode.DUPLICATE_JOB in reason_codes:
                return f"Duplicate job - already processed"
            elif DecisionReasonCode.SUSPICIOUS_JOB in reason_codes:
                return f"Job flagged as suspicious"
            else:
                return f"Hard filter failed: {reason_codes[0].value if reason_codes else 'unknown'}"
        
        elif priority == DecisionPriority.HIGH_PRIORITY:
            parts = []
            if DecisionReasonCode.STRONG_MATCH in reason_codes:
                parts.append("Strong title and skill match")
            if DecisionReasonCode.FRESH_JOB in reason_codes:
                parts.append("Freshly posted")
            if DecisionReasonCode.HIGH_SALARY in reason_codes:
                parts.append("Competitive salary")
            if job.location:
                parts.append(f"Location: {job.location}")
            return "; ".join(parts) if parts else "High priority match"
        
        elif priority == DecisionPriority.NORMAL_PRIORITY:
            return f"Good match (score: {decision_score:.0f}/100)"
        
        elif priority == DecisionPriority.LOW_PRIORITY:
            if DecisionReasonCode.WEAK_ROLE_MATCH in reason_codes:
                return "Lower priority due to weak role match"
            elif DecisionReasonCode.WEAK_SKILL_MATCH in reason_codes:
                return "Lower priority due to weak skill match"
            else:
                return f"Lower priority (score: {decision_score:.0f}/100)"
        
        elif priority == DecisionPriority.SKIP:
            return f"Skipped due to low relevance (score: {decision_score:.0f}/100)"
        
        elif priority == DecisionPriority.NEEDS_ATTENTION:
            if DecisionReasonCode.COMPANY_UNIDENTIFIED in reason_codes:
                return "Needs attention: employer could not be confidently identified"
            elif DecisionReasonCode.REQUIRES_MANUAL_REVIEW in reason_codes:
                return "Requires manual review"
            else:
                return "Needs attention before application"
        
        return f"Priority: {priority.value} (score: {decision_score:.0f}/100)"
    
    def save_decision_record(self, decision: DecisionQuality, job_id: int) -> None:
        """Save decision quality record to database for analytics."""
        record = DecisionQualityRecord(
            job_id=job_id,
            priority=decision.priority.value,
            decision_score=int(decision.decision_score),
            role_relevance_score=int(decision.role_relevance_score * 100),
            skill_relevance_score=int(decision.skill_relevance_score * 100),
            experience_compatibility_score=int(decision.experience_compatibility_score * 100),
            location_match_score=int(decision.location_match_score * 100),
            salary_suitability_score=int(decision.salary_suitability_score * 100),
            job_quality_score=int(decision.job_quality_score * 100),
            freshness_score=int(decision.freshness_score * 100),
            duplicate_probability=int(decision.duplicate_probability * 100),
            suspicious_probability=int(decision.suspicious_probability * 100),
            feedback_adjustment=int(decision.feedback_adjustment * 100),
            primary_reason_code=decision.primary_reason_code.value,
            reason_codes=json.dumps([rc.value for rc in decision.reason_codes]),
            explanation=decision.explanation,
            hard_filter_failed=1 if decision.hard_filter_failed else 0,
            requires_ai_analysis=1 if decision.requires_ai_analysis else 0,
            ai_available=1 if decision.ai_available else 0
        )
        self.session.add(record)
        self.session.commit()
