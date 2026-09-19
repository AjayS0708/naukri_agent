import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference
from backend.services.applications import ApplicationService
from backend.schemas.application import (
    ApplicationStatus, ApplicationMethod, ApplicationCreate, ApplicationUpdate
)


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


class TestApplicationFlow:
    """Test the application flow."""
    
    def test_create_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test creating an application."""
        application = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        assert application.id is not None
        assert application.job_id == sample_job.id
        assert application.status == ApplicationStatus.APPLICATION_STARTED
    
    def test_get_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test getting an application by ID."""
        created = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        retrieved = application_service.get_application(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.job_id == sample_job.id
    
    def test_update_application_status(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test updating application status."""
        created = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        
        updated = application_service.update_application(
            created.id,
            ApplicationUpdate(status=ApplicationStatus.APPLIED, applied_at=datetime.now(UTC))
        )
        
        assert updated is not None
        assert updated.status == ApplicationStatus.APPLIED
        assert updated.applied_at is not None
    
    def test_update_application_failure_reason(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test updating application with failure reason."""
        created = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        
        updated = application_service.update_application(
            created.id,
            ApplicationUpdate(
                status=ApplicationStatus.NEEDS_ATTENTION,
                failure_reason="Security verification required",
                needs_attention=True
            )
        )
        
        assert updated is not None
        assert updated.status == ApplicationStatus.NEEDS_ATTENTION
        assert updated.failure_reason == "Security verification required"
        assert updated.needs_attention is True
    
    def test_record_external_application(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test recording an external application."""
        application = application_service.record_external_application(
            sample_job,
            "https://company.com/apply",
            "External application redirect"
        )
        
        assert application.status == ApplicationStatus.EXTERNAL_APPLICATION
        assert application.application_method == ApplicationMethod.EXTERNAL
        assert application.external_url == "https://company.com/apply"
        assert application.needs_attention is True
    
    def test_record_application_failure(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test recording an application failure."""
        application = application_service.record_application_failure(
            sample_job,
            "Failed to start application"
        )
        
        assert application.status == ApplicationStatus.NEEDS_ATTENTION
        assert application.failure_reason == "Failed to start application"
        assert application.needs_attention is True
    
    def test_record_application_skip(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test recording a skipped application."""
        application = application_service.record_application_skip(
            sample_job,
            "Location mismatch"
        )
        
        assert application.status == ApplicationStatus.SKIPPED
        assert application.skip_reason == "Location mismatch"
    
    def test_get_application_by_job(
        self,
        application_service: ApplicationService,
        sample_job: Job
    ):
        """Test getting application by job ID."""
        created = application_service.create_application(
            ApplicationCreate(job_id=sample_job.id)
        )
        
        retrieved = application_service.get_application_by_job(sample_job.id)
        assert retrieved is not None
        assert retrieved.id == created.id
    
    def test_get_application_history(
        self,
        application_service: ApplicationService,
        sample_job: Job,
        db_session: Session
    ):
        """Test getting application history."""
        # Create multiple applications
        for i in range(3):
            job = Job(
                platform="naukri",
                external_job_id=f"job{i}",
                url=f"https://www.naukri.com/job{i}",
                title=f"Job {i}",
                company="Tech Company",
                description="Test job"
            )
            db_session.add(job)
            db_session.commit()
            application_service.create_application(ApplicationCreate(job_id=job.id))
        
        history = application_service.get_application_history(limit=10)
        assert len(history) == 3
    
    def test_update_nonexistent_application(
        self,
        application_service: ApplicationService
    ):
        """Test updating a non-existent application."""
        updated = application_service.update_application(
            99999,
            ApplicationUpdate(status=ApplicationStatus.APPLIED)
        )
        assert updated is None
    
    def test_get_nonexistent_application(
        self,
        application_service: ApplicationService
    ):
        """Test getting a non-existent application."""
        retrieved = application_service.get_application(99999)
        assert retrieved is None
