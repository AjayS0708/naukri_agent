import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.services.applications import ApplicationService
from backend.schemas.application import ApplicationStatus, ApplicationCreate, ApplicationUpdate


# Test database setup
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    """Create a test database session."""
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
    """Create a sample job."""
    job = Job(
        platform="naukri",
        external_job_id="job123",
        url="https://www.naukri.com/job123",
        title="Software Engineer",
        company="Tech Company",
        description="Python developer role",
        location="Bengaluru",
        salary="5-7 LPA",
        experience="2-4 years",
        employment_type="Full-time"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def application_service(db_session: Session):
    """Create application service."""
    return ApplicationService(db_session)


class TestDuplicateProtection:
    """Test duplicate application protection."""
    
    def test_check_duplicate_no_existing_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that a job with no existing application is not considered duplicate."""
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is False
    
    def test_check_duplicate_with_applied_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that an already applied job is considered duplicate."""
        # Create an applied application
        app = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        application_service.update_application(
            app.id,
            ApplicationUpdate(status=ApplicationStatus.APPLIED, applied_at=datetime.now(UTC))
        )
        
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is True
    
    def test_check_duplicate_with_submitted_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that a submitted job is considered duplicate."""
        # Create and submit an application
        app = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        application_service.update_application(
            app.id,
            ApplicationUpdate(status=ApplicationStatus.SUBMITTED, applied_at=datetime.now(UTC))
        )
        
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is True
    
    def test_check_duplicate_with_skipped_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that a skipped job is NOT considered duplicate (can be reconsidered)."""
        # Create a skipped application
        app = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        application_service.update_application(
            app.id,
            ApplicationUpdate(status=ApplicationStatus.SKIPPED, skip_reason="Location mismatch")
        )
        
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is False
    
    def test_check_duplicate_with_needs_attention_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that a needs-attention job is NOT considered duplicate (can be reconsidered)."""
        # Create a needs-attention application
        app = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        application_service.update_application(
            app.id,
            ApplicationUpdate(
                status=ApplicationStatus.NEEDS_ATTENTION,
                failure_reason="Security verification required"
            )
        )
        
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is False
    
    def test_check_duplicate_with_external_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test that an external application is NOT considered duplicate (can be reconsidered)."""
        # Create an external application
        application_service.record_external_application(
            sample_job,
            "https://company.com/apply",
            "External redirect"
        )
        
        is_duplicate = application_service.check_duplicate_application(sample_job)
        assert is_duplicate is False
