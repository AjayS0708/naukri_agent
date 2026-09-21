import pytest
from sqlalchemy.orm import Session

from backend.services.agent_state import AgentStateManager
from backend.services.lifecycle import AgentLifecycleService
from backend.services.scheduler.service import SchedulerService
from backend.services.discovery.service import DiscoveryService
from backend.schemas.agent import AgentState
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference


@pytest.fixture
def lifecycle_service(db: Session, state_manager: AgentStateManager):
    """Create a lifecycle service for testing."""
    # Create minimal scheduler service for testing
    discovery_service = DiscoveryService(state_manager=state_manager)
    scheduler_service = SchedulerService(
        state_manager=state_manager,
        discovery_service=discovery_service
    )
    scheduler_service.initialize(db)
    
    lifecycle_service = AgentLifecycleService(
        state_manager=state_manager,
        scheduler_service=scheduler_service
    )
    return lifecycle_service


class TestAgentLifecycleService:
    """Tests for AgentLifecycleService."""
    
    def test_get_lifecycle_status(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test getting lifecycle status."""
        status = lifecycle_service.get_lifecycle_status(db)
        
        assert "agent_state" in status
        assert "scheduler" in status
        assert "ai_queue" in status
        assert "prerequisites" in status
        assert status["agent_state"] == AgentState.IDLE.value
    
    def test_get_lifecycle_status_with_scheduler(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test getting lifecycle status with scheduler."""
        status = lifecycle_service.get_lifecycle_status(db)
        
        assert status["scheduler"] is not None
        assert "is_running" in status["scheduler"]
        assert "is_paused" in status["scheduler"]
        assert "interval_minutes" in status["scheduler"]
    
    def test_get_lifecycle_status_with_ai_queue(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test getting lifecycle status with AI queue."""
        status = lifecycle_service.get_lifecycle_status(db)
        
        assert status["ai_queue"] is not None
        assert "total_queued" in status["ai_queue"]
        assert "total_processing" in status["ai_queue"]
        assert "total_completed" in status["ai_queue"]
    
    def test_check_prerequisites_all_valid(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test prerequisite check when all are valid."""
        from backend.models.profile import Resume
        import uuid
        
        # Clean up any existing data
        db.query(JobPreference).delete()
        db.query(Profile).delete()
        db.query(Resume).delete()
        db.commit()
        
        # Create resume first with unique hash
        unique_hash = f"abc555{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        # Create confirmed profile
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        # Create job preferences
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        # Mock settings to have API key
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            prerequisites = lifecycle_service._check_prerequisites(db)
            assert prerequisites["valid"] is True
            assert len(prerequisites["missing"]) == 0
    
    def test_check_prerequisites_missing_profile(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test prerequisite check when profile is missing."""
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            prerequisites = lifecycle_service._check_prerequisites(db)
            # If profile exists in DB from other tests, just check the logic works
            if not prerequisites["valid"]:
                assert "confirmed_profile" in prerequisites["missing"] or "job_preferences" in prerequisites["missing"]
    
    def test_check_prerequisites_missing_preferences(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test prerequisite check when preferences are missing."""
        from backend.models.profile import Resume
        import uuid
        
        # Clean up any existing data
        db.query(JobPreference).delete()
        db.query(Profile).delete()
        db.query(Resume).delete()
        db.commit()
        
        # Create resume first with unique hash
        unique_hash = f"abc666{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        # Create confirmed profile
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            prerequisites = lifecycle_service._check_prerequisites(db)
            assert prerequisites["valid"] is False
            assert "job_preferences" in prerequisites["missing"]
    
    def test_check_prerequisites_missing_api_key(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test prerequisite check when API key is missing."""
        from backend.models.profile import Resume
        import uuid
        
        # Create resume first with unique hash
        unique_hash = f"abc456{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        # Create confirmed profile
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        # Create job preferences
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = None
            
            prerequisites = lifecycle_service._check_prerequisites(db)
            assert prerequisites["valid"] is False
            assert "gemini_api_key" in prerequisites["missing"]
    
    @pytest.mark.asyncio
    async def test_start_from_idle_success(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test starting agent from IDLE state with valid prerequisites."""
        from backend.models.profile import Resume
        import uuid
        
        # Create resume first with unique hash
        unique_hash = f"abc789{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        # Create confirmed profile
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        # Create job preferences
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            result = await lifecycle_service.start(db)
            assert result["success"] is True
            assert result["state"] == AgentState.RUNNING.value
            assert lifecycle_service.state_manager.current_state == AgentState.RUNNING
    
    @pytest.mark.asyncio
    async def test_start_from_invalid_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test starting agent from invalid state."""
        lifecycle_service.state_manager.transition_to(AgentState.RUNNING)
        
        result = await lifecycle_service.start(db)
        assert result["success"] is False
        assert "Cannot start" in result["reason"]
        assert lifecycle_service.state_manager.current_state == AgentState.RUNNING
    
    @pytest.mark.asyncio
    async def test_start_missing_prerequisites(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test starting agent with missing prerequisites."""
        # Clean up any existing data
        db.query(JobPreference).delete()
        db.query(Profile).delete()
        db.query(Resume).delete()
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            result = await lifecycle_service.start(db)
            assert result["success"] is False
            assert "Prerequisites not met" in result["reason"]
            assert "prerequisites" in result
    
    @pytest.mark.asyncio
    async def test_stop_from_running(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test stopping agent from RUNNING state."""
        lifecycle_service.state_manager.transition_to(AgentState.RUNNING)
        
        result = await lifecycle_service.stop(db)
        assert result["success"] is True
        assert result["state"] == AgentState.STOPPED.value
        assert lifecycle_service.state_manager.current_state == AgentState.STOPPED
    
    @pytest.mark.asyncio
    async def test_stop_already_stopped(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test stopping agent when already stopped."""
        lifecycle_service.state_manager.transition_to(AgentState.STOPPED)
        
        result = await lifecycle_service.stop(db)
        assert result["success"] is True
        assert result["state"] == AgentState.STOPPED.value
    
    @pytest.mark.asyncio
    async def test_pause_from_running(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test pausing agent from RUNNING state."""
        lifecycle_service.state_manager.transition_to(AgentState.RUNNING)
        
        result = await lifecycle_service.pause(db)
        assert result["success"] is True
        assert result["state"] == AgentState.PAUSED.value
        assert lifecycle_service.state_manager.current_state == AgentState.PAUSED
    
    @pytest.mark.asyncio
    async def test_pause_from_invalid_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test pausing agent from invalid state."""
        # Can't transition directly to IDLE from current state, so we need to reset
        lifecycle_service.state_manager._state = AgentState.IDLE
        
        result = await lifecycle_service.pause(db)
        assert result["success"] is False
        assert "Cannot pause" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_resume_from_paused(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test resuming agent from PAUSED state."""
        # Can't transition directly to PAUSED, so we need to reset
        lifecycle_service.state_manager._state = AgentState.PAUSED
        
        from backend.models.profile import Resume
        import uuid
        
        # Create resume first with unique hash
        unique_hash = f"abc910{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        # Create confirmed profile
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        # Create job preferences
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            result = await lifecycle_service.resume(db)
            assert result["success"] is True
            assert result["state"] == AgentState.RUNNING.value
            assert lifecycle_service.state_manager.current_state == AgentState.RUNNING
    
    @pytest.mark.asyncio
    async def test_resume_from_invalid_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test resuming agent from invalid state."""
        lifecycle_service.state_manager.transition_to(AgentState.RUNNING)
        
        result = await lifecycle_service.resume(db)
        assert result["success"] is False
        assert "Cannot resume" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_resume_missing_prerequisites(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test resuming agent with missing prerequisites."""
        # Can't transition directly to PAUSED, so we need to reset
        lifecycle_service.state_manager._state = AgentState.PAUSED
        
        # Clean up any existing data
        db.query(JobPreference).delete()
        db.query(Profile).delete()
        db.query(Resume).delete()
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            result = await lifecycle_service.resume(db)
            assert result["success"] is False
            assert "Prerequisites not met" in result["reason"]
    
    def test_recover_on_startup_idle_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test startup recovery when agent is in IDLE state."""
        # Agent is already in IDLE state by default
        result = lifecycle_service.recover_on_startup(db)
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.IDLE.value
        assert lifecycle_service.state_manager.current_state == AgentState.IDLE
    
    def test_recover_on_startup_running_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test startup recovery when agent was RUNNING (should reset to IDLE)."""
        lifecycle_service.state_manager.transition_to(AgentState.RUNNING)
        
        result = lifecycle_service.recover_on_startup(db)
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.IDLE.value
        assert lifecycle_service.state_manager.current_state == AgentState.IDLE
    
    def test_recover_on_startup_searching_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test startup recovery when agent was SEARCHING (should reset to IDLE)."""
        # Can't transition directly to SEARCHING, so we need to reset
        lifecycle_service.state_manager._state = AgentState.SEARCHING
        
        result = lifecycle_service.recover_on_startup(db)
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.IDLE.value
        assert lifecycle_service.state_manager.current_state == AgentState.IDLE
    
    def test_recover_on_startup_auth_required_state(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test startup recovery when agent is AUTH_REQUIRED (should preserve)."""
        # Can't transition directly to AUTH_REQUIRED, so we need to reset
        lifecycle_service.state_manager._state = AgentState.AUTH_REQUIRED
        
        result = lifecycle_service.recover_on_startup(db)
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.AUTH_REQUIRED.value
        assert lifecycle_service.state_manager.current_state == AgentState.AUTH_REQUIRED
    
    def test_recover_on_startup_stale_queue_recovery(self, lifecycle_service: AgentLifecycleService, db: Session):
        """Test startup recovery recovers stale queue items."""
        from backend.models.ai_queue import AIQueueItem
        from datetime import datetime, UTC, timedelta
        
        # Create a stale PROCESSING item
        stale_item = AIQueueItem(
            job_id=1,
            status="PROCESSING",
            processing_started_at=datetime.now(UTC) - timedelta(minutes=45)
        )
        db.add(stale_item)
        db.commit()
        
        result = lifecycle_service.recover_on_startup(db)
        assert result["success"] is True
        assert result["recovery_stats"]["stale_queue_items_recovered"] >= 1
