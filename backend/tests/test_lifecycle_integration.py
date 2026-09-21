import pytest
from sqlalchemy.orm import Session

from backend.services.agent_state import AgentStateManager
from backend.services.lifecycle import AgentLifecycleService
from backend.services.scheduler.service import SchedulerService
from backend.services.discovery.service import DiscoveryService
from backend.schemas.agent import AgentState
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference
from backend.models.ai_queue import AIQueueItem
from datetime import datetime, UTC, timedelta


@pytest.fixture
def lifecycle_integration_setup(db: Session):
    """Set up complete lifecycle integration test environment."""
    # Create state manager
    state_manager = AgentStateManager(initial_state=AgentState.IDLE)
    
    # Create discovery service
    discovery_service = DiscoveryService(state_manager=state_manager)
    
    # Create scheduler service
    scheduler_service = SchedulerService(
        state_manager=state_manager,
        discovery_service=discovery_service
    )
    scheduler_service.initialize(db)
    
    # Create lifecycle service
    lifecycle_service = AgentLifecycleService(
        state_manager=state_manager,
        scheduler_service=scheduler_service
    )
    
    return {
        "state_manager": state_manager,
        "discovery_service": discovery_service,
        "scheduler_service": scheduler_service,
        "lifecycle_service": lifecycle_service
    }


class TestLifecycleIntegration:
    """Integration tests for complete lifecycle."""
    
    @pytest.mark.asyncio
    async def test_complete_lifecycle_flow(self, lifecycle_integration_setup, db: Session):
        """Test complete lifecycle: start -> pause -> resume -> stop."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        from backend.models.profile import Resume
        import uuid
        
        # Create prerequisites with unique hash
        unique_hash = f"abc111{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            # Start
            start_result = await lifecycle_service.start(db)
            assert start_result["success"] is True
            assert setup["state_manager"].current_state == AgentState.RUNNING
            
            # Pause
            pause_result = await lifecycle_service.pause(db)
            assert pause_result["success"] is True
            assert setup["state_manager"].current_state == AgentState.PAUSED
            
            # Resume
            resume_result = await lifecycle_service.resume(db)
            assert resume_result["success"] is True
            assert setup["state_manager"].current_state == AgentState.RUNNING
            
            # Stop
            stop_result = await lifecycle_service.stop(db)
            assert stop_result["success"] is True
            assert setup["state_manager"].current_state == AgentState.STOPPED
    
    @pytest.mark.asyncio
    async def test_lifecycle_with_scheduler_integration(self, lifecycle_integration_setup, db: Session):
        """Test lifecycle operations integrate with scheduler."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        scheduler_service = setup["scheduler_service"]
        
        from backend.models.profile import Resume
        import uuid
        
        # Create prerequisites with unique hash
        unique_hash = f"abc222{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            # Start agent (should start scheduler)
            await lifecycle_service.start(db)
            scheduler_status = scheduler_service.get_status()
            assert scheduler_status["is_running"] is True
            
            # Pause agent (should pause scheduler)
            await lifecycle_service.pause(db)
            scheduler_status = scheduler_service.get_status()
            assert scheduler_status["is_paused"] is True
            
            # Stop agent (should stop scheduler)
            setup["state_manager"]._state = AgentState.RUNNING
            await lifecycle_service.stop(db)
            scheduler_status = scheduler_service.get_status()
            assert scheduler_status["is_running"] is False
    
    def test_startup_recovery_with_stale_queue(self, lifecycle_integration_setup, db: Session):
        """Test startup recovery handles stale queue items correctly."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Create stale queue items
        stale_item = AIQueueItem(
            job_id=1,
            status="PROCESSING",
            processing_started_at=datetime.now(UTC) - timedelta(minutes=45)
        )
        db.add(stale_item)
        
        stale_item_2 = AIQueueItem(
            job_id=2,
            status="PROCESSING",
            processing_started_at=datetime.now(UTC) - timedelta(minutes=35)
        )
        db.add(stale_item_2)
        db.commit()
        
        # Run recovery
        result = lifecycle_service.recover_on_startup(db)
        
        assert result["success"] is True
        assert result["recovery_stats"]["stale_queue_items_recovered"] >= 2
        
        # Verify items were recovered
        from backend.services.gemini.queue import AIQueueService
        queue_service = AIQueueService(db)
        queue_status = queue_service.get_queue_status()
        assert queue_status.total_processing == 0
    
    def test_startup_recovery_preserves_auth_required_state(self, lifecycle_integration_setup, db: Session):
        """Test startup recovery preserves AUTH_REQUIRED state."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Set agent to AUTH_REQUIRED (can't transition directly, so reset)
        setup["state_manager"]._state = AgentState.AUTH_REQUIRED
        
        # Run recovery
        result = lifecycle_service.recover_on_startup(db)
        
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.AUTH_REQUIRED.value
        assert setup["state_manager"].current_state == AgentState.AUTH_REQUIRED
    
    def test_startup_recovery_preserves_security_required_state(self, lifecycle_integration_setup, db: Session):
        """Test startup recovery preserves SECURITY_REQUIRED state."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Set agent to SECURITY_REQUIRED (can't transition directly, so reset)
        setup["state_manager"]._state = AgentState.SECURITY_REQUIRED
        
        # Run recovery
        result = lifecycle_service.recover_on_startup(db)
        
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.SECURITY_REQUIRED.value
        assert setup["state_manager"].current_state == AgentState.SECURITY_REQUIRED
    
    def test_startup_recovery_resets_running_states(self, lifecycle_integration_setup, db: Session):
        """Test startup recovery resets active states to IDLE."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        active_states = [
            AgentState.RUNNING,
            AgentState.SEARCHING,
            AgentState.FILTERING,
            AgentState.APPLYING
        ]
        
        for state in active_states:
            # Can't transition directly, so reset
            setup["state_manager"]._state = state
            
            result = lifecycle_service.recover_on_startup(db)
            
            assert result["success"] is True
            assert result["recovery_stats"]["agent_state_restored"] == AgentState.IDLE.value
            assert setup["state_manager"].current_state == AgentState.IDLE
    
    @pytest.mark.asyncio
    async def test_no_automatic_application_after_restart(self, lifecycle_integration_setup, db: Session):
        """Test that agent does NOT automatically start applications after restart."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        from backend.models.profile import Resume
        import uuid
        
        # Create prerequisites with unique hash
        unique_hash = f"abc333{uuid.uuid4().hex[:8]}"
        resume = Resume(
            stored_filename=f"test_hash_{unique_hash}.pdf",
            original_filename="test.pdf",
            sha256=unique_hash,
            file_size=1024,
            text_length=500
        )
        db.add(resume)
        db.flush()
        
        profile = Profile(
            resume_id=resume.id,
            data={"name": "Test User"},
            confirmed=True
        )
        db.add(profile)
        
        preferences = JobPreference()
        db.add(preferences)
        db.commit()
        
        # Simulate agent was RUNNING before restart (can't transition directly, so reset)
        setup["state_manager"]._state = AgentState.RUNNING
        
        # Run startup recovery
        result = lifecycle_service.recover_on_startup(db)
        
        # Agent should be reset to IDLE, not RUNNING
        assert result["success"] is True
        assert result["recovery_stats"]["agent_state_restored"] == AgentState.IDLE.value
        assert setup["state_manager"].current_state == AgentState.IDLE
        
        # Scheduler should NOT be auto-started
        scheduler_status = setup["scheduler_service"].get_status()
        assert scheduler_status["is_running"] is False
    
    @pytest.mark.asyncio
    async def test_lifecycle_status_comprehensive(self, lifecycle_integration_setup, db: Session):
        """Test that lifecycle status includes all components."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        status = lifecycle_service.get_lifecycle_status(db)
        
        assert "agent_state" in status
        assert "scheduler" in status
        assert "ai_queue" in status
        assert "prerequisites" in status
        
        # Verify scheduler status structure
        assert status["scheduler"] is not None
        assert "is_running" in status["scheduler"]
        assert "is_paused" in status["scheduler"]
        assert "interval_minutes" in status["scheduler"]
        
        # Verify AI queue status structure
        assert status["ai_queue"] is not None
        assert "total_queued" in status["ai_queue"]
        assert "total_processing" in status["ai_queue"]
        assert "total_completed" in status["ai_queue"]
        
        # Verify prerequisites structure
        assert "valid" in status["prerequisites"]
        assert "missing" in status["prerequisites"]
    
    @pytest.mark.asyncio
    async def test_invalid_state_transitions_prevented(self, lifecycle_integration_setup, db: Session):
        """Test that invalid state transitions are prevented."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Try to start from RUNNING (invalid) - reset state
        setup["state_manager"]._state = AgentState.RUNNING
        result = await lifecycle_service.start(db)
        assert result["success"] is False
        
        # Try to pause from IDLE (invalid) - reset state
        setup["state_manager"]._state = AgentState.IDLE
        result = await lifecycle_service.pause(db)
        assert result["success"] is False
        
        # Try to resume from RUNNING (invalid) - reset state
        setup["state_manager"]._state = AgentState.RUNNING
        result = await lifecycle_service.resume(db)
        assert result["success"] is False
    
    def test_recovery_failure_safety(self, lifecycle_integration_setup, db: Session):
        """Test that recovery failure leaves agent in safe state."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Set agent to a dangerous state (can't transition directly, so reset)
        setup["state_manager"]._state = AgentState.RUNNING
        
        # The recovery method is designed to handle failures gracefully
        # Even if something fails, it should reset to IDLE
        result = lifecycle_service.recover_on_startup(db)
        
        # Agent should be in safe IDLE state regardless
        assert setup["state_manager"].current_state == AgentState.IDLE
    
    @pytest.mark.asyncio
    async def test_lifecycle_with_missing_prerequisites(self, lifecycle_integration_setup, db: Session):
        """Test lifecycle operations with missing prerequisites."""
        setup = lifecycle_integration_setup
        lifecycle_service = setup["lifecycle_service"]
        
        # Clean up any existing data
        db.query(JobPreference).delete()
        db.query(Profile).delete()
        db.query(Resume).delete()
        db.commit()
        
        from unittest.mock import patch
        with patch('backend.core.config.get_settings') as mock_settings:
            mock_settings.return_value.gemini_api_key = "test_key"
            
            # Try to start without profile
            result = await lifecycle_service.start(db)
            assert result["success"] is False
            assert "Prerequisites not met" in result["reason"]
            assert "confirmed_profile" in result["prerequisites"]["missing"]
