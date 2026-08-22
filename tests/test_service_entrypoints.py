def test_task_worker_compatibility_entrypoint_imports():
    from thinkdome.services.task_worker import run_worker

    assert callable(run_worker)
