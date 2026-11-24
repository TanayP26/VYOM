from app import service

def test_single_run_reservation_is_owner_safe():
    service.release_run(1001)
    service.release_run(1002)
    assert service.reserve_run(1001) is True
    assert service.active_run_id() == 1001
    assert service.reserve_run(1002) is False
    service.release_run(1002)
    assert service.active_run_id() == 1001
    service.release_run(1001)
    assert service.active_run_id() is None
