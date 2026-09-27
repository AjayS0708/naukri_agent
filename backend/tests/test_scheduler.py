import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session

from backend.core.scheduler import JobScheduler
from backend.services.scheduler.service import SchedulerService
from backend.models.scheduler import SchedulerConfig
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.schemas.agent import AgentState


class TestJobScheduler:
    """Tests for the core JobScheduler class."""
    
    @pytest.fixture
    def scheduler(self):
        """Create a JobScheduler instance for testing."""
        return JobScheduler(interval_minutes=60, max_instances=1)
    
    @pytest.fixture
    def mock_callback(self):
        """Create a mock callback for the scheduler."""
        return AsyncMock()
    
    def test_scheduler_initialization(self, scheduler):
        """Test that scheduler initializes with correct defaults."""
        assert scheduler.interval_minutes == 60
        assert scheduler.max_instances == 1
        assert scheduler._is_running is False
        assert scheduler._is_paused is False
        assert scheduler._last_run_at is None
        assert scheduler._next_run_at is None
    
    def test_set_task_callback(self, scheduler, mock_callback):
        """Test setting the task callback."""
        scheduler.set_task_callback(mock_callback)
        assert scheduler._task_callback == mock_callback
    
    @pytest.mark.asyncio
    async def test_scheduler_start(self, scheduler, mock_callback):
        """Test starting the scheduler."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        
        assert scheduler._is_running is True
        assert scheduler._is_paused is False
        assert scheduler._next_run_at is not None
    
    @pytest.mark.asyncio
    async def test_scheduler_start_already_running(self, scheduler, mock_callback):
        """Test that starting an already running scheduler is idempotent."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        
        scheduler._is_running = True
        await scheduler.start()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_scheduler_start_no_callback(self, scheduler):
        """Test that starting without callback logs warning."""
        with patch('backend.core.scheduler.logger'):
            await scheduler.start()
            assert scheduler._is_running is False
    
    @pytest.mark.asyncio
    async def test_scheduler_stop(self, scheduler, mock_callback):
        """Test stopping the scheduler."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        await scheduler.stop()
        
        assert scheduler._is_running is False
        assert scheduler._is_paused is False
        assert scheduler._next_run_at is None
    
    @pytest.mark.asyncio
    async def test_scheduler_stop_not_running(self, scheduler):
        """Test stopping a scheduler that's not running."""
        with patch('backend.core.scheduler.logger'):
            await scheduler.stop()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_scheduler_pause(self, scheduler, mock_callback):
        """Test pausing the scheduler."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        await scheduler.pause()
        
        assert scheduler._is_running is True
        assert scheduler._is_paused is True
        assert scheduler._next_run_at is None
    
    @pytest.mark.asyncio
    async def test_scheduler_pause_not_running(self, scheduler):
        """Test pausing a scheduler that's not running."""
        with patch('backend.core.scheduler.logger'):
            await scheduler.pause()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_scheduler_pause_already_paused(self, scheduler, mock_callback):
        """Test pausing an already paused scheduler."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        await scheduler.pause()
        
        with patch('backend.core.scheduler.logger'):
            await scheduler.pause()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_scheduler_resume(self, scheduler, mock_callback):
        """Test resuming the scheduler."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        await scheduler.pause()
        await scheduler.resume()
        
        assert scheduler._is_running is True
        assert scheduler._is_paused is False
        assert scheduler._next_run_at is not None
    
    @pytest.mark.asyncio
    async def test_scheduler_resume_not_running(self, scheduler):
        """Test resuming a scheduler that's not running."""
        with patch('backend.core.scheduler.logger'):
            await scheduler.resume()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_scheduler_resume_not_paused(self, scheduler, mock_callback):
        """Test resuming a scheduler that's not paused."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        
        with patch('backend.core.scheduler.logger'):
            await scheduler.resume()  # Should not raise error
    
    @pytest.mark.asyncio
    async def test_update_interval(self, scheduler, mock_callback):
        """Test updating the scheduler interval."""
        scheduler.set_task_callback(mock_callback)
        await scheduler.start()
        await scheduler.update_interval(30)
        
        assert scheduler.interval_minutes == 30
    
    @pytest.mark.asyncio
    async def test_update_interval_invalid(self, scheduler):
        """Test that invalid interval raises error."""
        with pytest.raises(ValueError, match="Interval must be at least 1 minute"):
            await scheduler.update_interval(0)
    
    def test_get_status(self, scheduler):
        """Test getting scheduler status."""
        status = scheduler.get_status()
        
        assert status["is_running"] is False
        assert status["is_paused"] is False
        assert status["interval_minutes"] == 60
        assert status["max_instances"] == 1
        assert status["last_run_at"] is None
        assert status["next_run_at"] is None
    
    @pytest.mark.asyncio
    async def test_execute_task_success(self, scheduler, mock_callback):
        """Test successful task execution."""
        scheduler.set_task_callback(mock_callback)
        await scheduler._execute_task()
        
        assert scheduler._last_run_at is not None
        mock_callback.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_task_no_callback(self, scheduler):
        """Test task execution without callback."""
        with patch('backend.core.scheduler.logger'):
            await scheduler._execute_task()
            assert scheduler._last_run_at is None
    
    @pytest.mark.asyncio
    async def test_execute_task_failure(self, scheduler, mock_callback):
        """Test task execution when callback fails."""
        mock_callback.side_effect = Exception("Task failed")
        scheduler.set_task_callback(mock_callback)
        
        with patch('backend.core.scheduler.logger'):
            await scheduler._execute_task()
            assert scheduler._last_run_at is not None


class TestSchedulerService:
    """Tests for the SchedulerService class."""
    
    @pytest.fixture
    def state_manager(self):
        """Create an AgentStateManager for testing."""
        manager = AgentStateManager(initial_state=AgentState.IDLE)
        return manager
    
    @pytest.fixture
    def mock_discovery_service(self):
        """Create a mock DiscoveryService for testing."""
        service = MagicMock(spec=DiscoveryService)
        service.run_discovery = AsyncMock()
        return service
    
    @pytest.fixture
    def scheduler_service(self, state_manager, mock_discovery_service):
        """Create a SchedulerService instance for testing."""
        return SchedulerService(
            state_manager=state_manager,
            discovery_service=mock_discovery_service
        )
    
    @pytest.fixture
    def db_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=Session)
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()
        return session
    
    def test_service_initialization(self, scheduler_service, state_manager, mock_discovery_service):
        """Test that service initializes with correct dependencies."""
        assert scheduler_service.state_manager == state_manager
        assert scheduler_service.discovery_service == mock_discovery_service
        assert scheduler_service._scheduler is None
        assert scheduler_service._config is None
    
    def test_initialize_creates_config(self, scheduler_service, db_session):
        """Test that initialize creates config if none exists."""
        db_session.execute.return_value.scalars.return_value.first.return_value = None
        
        scheduler_service.initialize(db_session)
        
        assert scheduler_service._config is not None
        assert scheduler_service._scheduler is not None
        db_session.add.assert_called_once()
        db_session.commit.assert_called()
    
    def test_initialize_loads_existing_config(self, scheduler_service, db_session):
        """Test that initialize loads existing config."""
        existing_config = SchedulerConfig(
            enabled=True,
            interval_minutes=30,
            max_instances=1
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = existing_config
        
        scheduler_service.initialize(db_session)
        
        assert scheduler_service._config == existing_config
        assert scheduler_service._scheduler is not None
        db_session.add.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_start_scheduler(self, scheduler_service, db_session):
        """Test starting the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.start = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=False
        )
        
        await scheduler_service.start(db_session)
        
        scheduler_service._scheduler.start.assert_called_once()
        assert scheduler_service._config.is_running is True
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_start_scheduler_disabled(self, scheduler_service, db_session):
        """Test that start does nothing when config is disabled."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._config = SchedulerConfig(
            enabled=False,
            interval_minutes=60,
            max_instances=1
        )
        
        with patch('backend.services.scheduler.service.logger'):
            await scheduler_service.start(db_session)
            scheduler_service._scheduler.start.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_start_scheduler_already_running(self, scheduler_service, db_session):
        """Test that start is idempotent when already running."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=True
        )
        
        with patch('backend.services.scheduler.service.logger'):
            await scheduler_service.start(db_session)
            scheduler_service._scheduler.start.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_stop_scheduler(self, scheduler_service, db_session):
        """Test stopping the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.stop = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=True
        )
        
        await scheduler_service.stop(db_session)
        
        scheduler_service._scheduler.stop.assert_called_once()
        assert scheduler_service._config.is_running is False
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_pause_scheduler(self, scheduler_service, db_session):
        """Test pausing the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.pause = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=True,
            is_paused=False
        )
        
        await scheduler_service.pause(db_session)
        
        scheduler_service._scheduler.pause.assert_called_once()
        assert scheduler_service._config.is_paused is True
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_resume_scheduler(self, scheduler_service, db_session):
        """Test resuming the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.resume = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=True,
            is_paused=True
        )
        
        await scheduler_service.resume(db_session)
        
        scheduler_service._scheduler.resume.assert_called_once()
        assert scheduler_service._config.is_paused is False
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_update_interval(self, scheduler_service, db_session):
        """Test updating the scheduler interval."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.update_interval = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1
        )
        
        await scheduler_service.update_interval(db_session, 30)
        
        scheduler_service._scheduler.update_interval.assert_called_once_with(30)
        assert scheduler_service._config.interval_minutes == 30
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_update_interval_invalid(self, scheduler_service, db_session):
        """Test that invalid interval raises error."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1
        )
        
        with pytest.raises(ValueError, match="Interval must be at least 1 minute"):
            await scheduler_service.update_interval(db_session, 0)
    
    @pytest.mark.asyncio
    async def test_update_enabled_true(self, scheduler_service, db_session):
        """Test enabling the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.start = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=False,
            interval_minutes=60,
            max_instances=1,
            is_running=False
        )
        
        await scheduler_service.update_enabled(db_session, True)
        
        assert scheduler_service._config.enabled is True
        scheduler_service._scheduler.start.assert_called_once()
        db_session.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_update_enabled_false(self, scheduler_service, db_session):
        """Test disabling the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.stop = AsyncMock()
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=60,
            max_instances=1,
            is_running=True
        )
        
        await scheduler_service.update_enabled(db_session, False)
        
        assert scheduler_service._config.enabled is False
        scheduler_service._scheduler.stop.assert_called_once()
        db_session.commit.assert_called()
    
    def test_get_status_no_scheduler(self, scheduler_service):
        """Test getting status when scheduler not initialized."""
        status = scheduler_service.get_status()
        
        assert status["is_running"] is False
        assert status["is_paused"] is False
        assert status["enabled"] is True
        assert status["interval_minutes"] == 60
    
    def test_get_status_with_scheduler(self, scheduler_service):
        """Test getting status when scheduler is initialized."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler.get_status.return_value = {
            "is_running": True,
            "is_paused": False,
            "interval_minutes": 30,
            "max_instances": 1,
            "last_run_at": datetime.now(UTC),
            "next_run_at": datetime.now(UTC)
        }
        scheduler_service._config = SchedulerConfig(
            enabled=True,
            interval_minutes=30,
            max_instances=1,
            last_run_at=datetime.now(UTC),
            next_run_at=datetime.now(UTC)
        )
        
        status = scheduler_service.get_status()
        
        assert status["is_running"] is True
        assert status["enabled"] is True
        assert status["interval_minutes"] == 30
    
    @pytest.mark.asyncio
    async def test_shutdown(self, scheduler_service):
        """Test shutting down the scheduler."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler._is_running = True
        scheduler_service._scheduler.stop = AsyncMock()
        
        await scheduler_service.shutdown()
        
        scheduler_service._scheduler.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_not_running(self, scheduler_service):
        """Test shutdown when scheduler not running."""
        scheduler_service._scheduler = MagicMock(spec=JobScheduler)
        scheduler_service._scheduler._is_running = False
        
        await scheduler_service.shutdown()
        
        scheduler_service._scheduler.stop.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_run_discovery_task_success(self, scheduler_service, state_manager):
        """Test successful discovery task execution."""
        scheduler_service._config = MagicMock()
        # State manager is already IDLE from fixture

        with patch('backend.services.scheduler.service.SessionLocal') as mock_session_local:
            mock_session = MagicMock()
            mock_session.close = MagicMock()
            mock_session_local.return_value = mock_session

            with patch('backend.services.scheduler.service.ApplicationLimitService') as mock_limit_class:
                mock_limit_service = MagicMock()
                mock_limit_service.check_limits.return_value = MagicMock(allowed=True)
                mock_limit_class.return_value = mock_limit_service

                await scheduler_service._run_discovery_task()

                scheduler_service.discovery_service.run_discovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_discovery_task_skip_when_busy(self, scheduler_service, state_manager):
        """Test that discovery is skipped when agent is busy."""
        # Transition from IDLE to RUNNING
        state_manager.transition_to(AgentState.RUNNING)

        with patch('backend.services.scheduler.service.logger'):
            await scheduler_service._run_discovery_task()
            scheduler_service.discovery_service.run_discovery.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_discovery_task_failure(self, scheduler_service, state_manager):
        """Test discovery task failure handling."""
        # State manager is already IDLE from fixture
        scheduler_service.discovery_service.run_discovery.side_effect = Exception("Discovery failed")

        with patch('backend.services.scheduler.service.SessionLocal') as mock_session_local:
            mock_session = MagicMock()
            mock_session.close = MagicMock()
            mock_session_local.return_value = mock_session

            with patch('backend.services.scheduler.service.ApplicationLimitService') as mock_limit_class:
                mock_limit_service = MagicMock()
                mock_limit_service.check_limits.return_value = MagicMock(allowed=True)
                mock_limit_class.return_value = mock_limit_service

                with patch('backend.services.scheduler.service.logger'):
                    await scheduler_service._run_discovery_task()


class TestPhase9ASchedulerIntegration:
    """Integration tests for Phase 9A scheduler automation loop."""

    @pytest.fixture
    def state_manager(self):
        """Create an AgentStateManager for testing."""
        return AgentStateManager(initial_state=AgentState.IDLE)

    @pytest.fixture
    def mock_discovery_service(self):
        """Create a mock DiscoveryService."""
        service = MagicMock(spec=DiscoveryService)
        service.run_discovery = AsyncMock()
        return service

    @pytest.fixture
    def scheduler_service(self, state_manager, mock_discovery_service):
        """Create a SchedulerService."""
        return SchedulerService(
            state_manager=state_manager,
            discovery_service=mock_discovery_service
        )

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock(spec=Session)
        db.execute = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.close = MagicMock()
        db.get = MagicMock(return_value=None)
        return db

    @pytest.mark.asyncio
    async def test_phase_9a_cycle_runs_without_error(self, scheduler_service, state_manager, mock_db):
        """
        Test that Phase 9A cycle executes without error and calls discovery.
        """
        scheduler_service._config = MagicMock()

        with patch('backend.services.scheduler.service.SessionLocal') as mock_session_local:
            mock_session_local.return_value = mock_db

            with patch('backend.services.scheduler.service.ApplicationLimitService') as mock_limit_class:
                mock_limit_service = MagicMock()
                mock_limit_service.check_limits.return_value = MagicMock(allowed=True)
                mock_limit_class.return_value = mock_limit_service

                # Run the full cycle
                await scheduler_service._run_discovery_task()

                # Verify discovery was called (first step of Phase 9A)
                scheduler_service.discovery_service.run_discovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_phase_9a_hard_filter_method_exists(self, scheduler_service, mock_db):
        """
        Test that hard filter integration method (GAP-C3) exists and can be called.
        """
        # Mock database to return empty results
        def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute

        # Should not raise error
        stats = await scheduler_service._apply_hard_filters_and_enqueue(mock_db)

        # Should return valid stats dict
        assert isinstance(stats, dict)
        assert "discovered" in stats
        assert "hard_filtered" in stats
        assert "queued" in stats

    @pytest.mark.asyncio
    async def test_phase_9a_ai_queue_processing_method_exists(self, scheduler_service, mock_db):
        """
        Test that AI queue processing method (GAP-C1) exists and can be called.
        """
        from backend.models.profile import Profile

        profile = Profile(id=1, confirmed=True, data={})

        def mock_execute(stmt):
            result = MagicMock()
            if "Profile" in str(stmt):
                result.scalars.return_value.first.return_value = profile
            else:
                result.scalars.return_value.first.return_value = None
            return result

        mock_db.execute = mock_execute

        with patch('backend.services.scheduler.service.AIQueueService'):
            # Should not raise error
            stats = await scheduler_service._process_ai_queue_items(mock_db)

            # Should return valid stats dict
            assert isinstance(stats, dict)
            assert "processed" in stats
            assert "quota_blocked" in stats

    @pytest.mark.asyncio
    async def test_phase_9a_application_runner_method_exists(self, scheduler_service, mock_db):
        """
        Test that ApplicationRunner invocation method (GAP-C2) exists and can be called.
        """
        def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalars.return_value.first.return_value = None
            return result

        mock_db.execute = mock_execute

        with patch('backend.services.scheduler.service.ApplicationRunner'):
            # Should not raise error
            stats = await scheduler_service._invoke_application_runner(mock_db)

            # Should return valid stats dict
            assert isinstance(stats, dict)
            assert "candidates" in stats
            assert "applied" in stats

    @pytest.mark.asyncio
    async def test_phase_9a_full_cycle_orchestrates_all_steps(self, scheduler_service, state_manager, mock_db):
        """
        Test that Phase 9A cycle orchestrates discovery → filtering → AI → application.
        Verifies the integration of all components.
        """
        scheduler_service._config = MagicMock()

        def mock_execute(stmt):
            result = MagicMock()
            result.scalars.return_value.first.return_value = None
            result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute

        with patch('backend.services.scheduler.service.SessionLocal') as mock_session_local:
            mock_session_local.return_value = mock_db

            with patch('backend.services.scheduler.service.ApplicationLimitService') as mock_limit_class:
                mock_limit_service = MagicMock()
                mock_limit_service.check_limits.return_value = MagicMock(allowed=True)
                mock_limit_class.return_value = mock_limit_service

                # Patch internal methods to verify they're called
                with patch.object(scheduler_service, '_apply_hard_filters_and_enqueue', new_callable=AsyncMock) as mock_filter:
                    mock_filter.return_value = {
                        "discovered": 0,
                        "hard_filtered": 0,
                        "queued": 0,
                        "errors": []
                    }

                    with patch.object(scheduler_service, '_process_ai_queue_items', new_callable=AsyncMock) as mock_ai:
                        mock_ai.return_value = {
                            "processed": 0,
                            "quota_blocked": 0,
                            "errors": []
                        }

                        with patch.object(scheduler_service, '_invoke_application_runner', new_callable=AsyncMock) as mock_app:
                            mock_app.return_value = {
                                "candidates": 0,
                                "applied": 0,
                                "errors": []
                            }

                            await scheduler_service._run_discovery_task()

                            # Verify all phases were called in order
                            scheduler_service.discovery_service.run_discovery.assert_called_once()
                            mock_filter.assert_called_once()
                            mock_ai.assert_called_once()
                            mock_app.assert_called_once()
