"""
Regression tests for JobAnalysis prompt_version persistence (Issue 1 fix).

Verifies:
1. A successful job analysis persists prompt_version.
2. The persisted value is non-null.
3. The value corresponds to the prompt version actually used (JOB_ANALYSIS_PROMPT_V1).
4. Existing analysis behavior is unchanged.
"""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.ai import JobAnalysisModel
from backend.services.gemini.queue import AIQueueService
from backend.services.gemini.prompts import JOB_ANALYSIS_PROMPT_V1
from backend.schemas.ai import JobAnalysis, AIRecommendation, JobQuality
from backend.schemas.ai_queue import AIQueueStatus

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_job(db_session: Session):
    job = Job(
        platform="naukri",
        external_job_id="test_job_001",
        url="https://www.naukri.com/test_job_001",
        title="Data Analyst",
        company="Test Corp",
        description="Looking for a data analyst with Python and SQL skills. 0-1 years experience.",
        location="Bengaluru",
        experience="0-1 years",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def queued_item(db_session: Session, sample_job: Job):
    service = AIQueueService(db_session)
    item = service.enqueue_job(job_id=sample_job.id, queue_source="TEST")
    return item


def _make_mock_analysis() -> JobAnalysis:
    return JobAnalysis(
        match_score=75,
        role_match=True,
        skill_match=True,
        experience_match=True,
        location_match=True,
        salary_match=True,
        job_quality=JobQuality.GOOD,
        duplicate_probability=0.05,
        suspicious=False,
        recommendation=AIRecommendation.APPLY,
        short_reason="Good match for data analyst role.",
    )


class TestJobAnalysisPersistence:
    """Regression tests for prompt_version persistence in JobAnalysisModel."""

    def test_prompt_version_is_persisted_on_successful_analysis(
        self, db_session: Session, queued_item, sample_job: Job
    ):
        """Successful analysis must persist a non-null prompt_version."""
        service = AIQueueService(db_session)

        with patch.object(service, "gemini_provider") as mock_gemini:
            service.gemini_provider = mock_gemini
            mock_gemini.analyze_job.return_value = _make_mock_analysis()

            result = service.process_item(queued_item.id, profile_context="{}")

        assert result.success is True
        assert result.status == AIQueueStatus.COMPLETED
        assert result.analysis_id is not None

        saved = db_session.get(JobAnalysisModel, result.analysis_id)
        assert saved is not None
        assert saved.prompt_version is not None

    def test_prompt_version_is_non_null(
        self, db_session: Session, queued_item, sample_job: Job
    ):
        """The persisted prompt_version must not be an empty string or None."""
        service = AIQueueService(db_session)

        with patch.object(service, "gemini_provider") as mock_gemini:
            service.gemini_provider = mock_gemini
            mock_gemini.analyze_job.return_value = _make_mock_analysis()

            result = service.process_item(queued_item.id, profile_context="{}")

        saved = db_session.get(JobAnalysisModel, result.analysis_id)
        assert saved.prompt_version is not None
        assert len(saved.prompt_version) > 0

    def test_prompt_version_matches_actual_prompt_constant(
        self, db_session: Session, queued_item, sample_job: Job
    ):
        """The persisted prompt_version must equal JOB_ANALYSIS_PROMPT_V1."""
        service = AIQueueService(db_session)

        with patch.object(service, "gemini_provider") as mock_gemini:
            service.gemini_provider = mock_gemini
            mock_gemini.analyze_job.return_value = _make_mock_analysis()

            result = service.process_item(queued_item.id, profile_context="{}")

        saved = db_session.get(JobAnalysisModel, result.analysis_id)
        assert saved.prompt_version == JOB_ANALYSIS_PROMPT_V1

    def test_prompt_version_constant_is_defined_and_non_empty(self):
        """JOB_ANALYSIS_PROMPT_V1 constant must be defined and non-empty."""
        assert JOB_ANALYSIS_PROMPT_V1 is not None
        assert isinstance(JOB_ANALYSIS_PROMPT_V1, str)
        assert len(JOB_ANALYSIS_PROMPT_V1) > 0

    def test_existing_analysis_behavior_unchanged_on_gemini_failure(
        self, db_session: Session, queued_item, sample_job: Job
    ):
        """When Gemini returns None, item goes to RETRY_PENDING (existing behavior)."""
        service = AIQueueService(db_session)

        with patch.object(service, "gemini_provider") as mock_gemini:
            service.gemini_provider = mock_gemini
            mock_gemini.analyze_job.return_value = None

            result = service.process_item(queued_item.id, profile_context="{}")

        assert result.success is False
        assert result.status == AIQueueStatus.RETRY_PENDING

        # No JobAnalysisModel should be created on failure
        analyses = db_session.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == sample_job.id)
        ).scalars().all()
        assert len(analyses) == 0

    def test_analysis_model_fields_complete(
        self, db_session: Session, queued_item, sample_job: Job
    ):
        """All required JobAnalysisModel fields are populated after successful analysis."""
        service = AIQueueService(db_session)

        with patch.object(service, "gemini_provider") as mock_gemini:
            service.gemini_provider = mock_gemini
            mock_gemini.analyze_job.return_value = _make_mock_analysis()

            result = service.process_item(queued_item.id, profile_context="{}")

        saved = db_session.get(JobAnalysisModel, result.analysis_id)
        assert saved.job_id == sample_job.id
        assert saved.match_score == 75
        assert saved.recommendation == AIRecommendation.APPLY.value
        assert saved.model is not None
        assert saved.prompt_version == JOB_ANALYSIS_PROMPT_V1
        assert saved.created_at is not None
