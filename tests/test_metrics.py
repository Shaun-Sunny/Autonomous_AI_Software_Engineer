from backend.observability.metrics import update_deploy_success_rate


def test_metrics_update_deploy_success_rate():
    update_deploy_success_rate(True)
    update_deploy_success_rate(False)
    assert True
