from collections import deque

from prometheus_client import Counter, Gauge, Histogram

runs_total = Counter("runs_total", "Total generation runs", ["status"])
retries_total = Counter("retries_total", "Total debug retries")
run_duration_seconds = Histogram("run_duration_seconds", "Time to complete a run")
active_runs = Gauge("active_runs", "Currently running generations")
deploy_success_rate = Gauge("deploy_success_rate", "Rolling deploy success rate")

_recent_deploy_results: deque[bool] = deque(maxlen=100)


def update_deploy_success_rate(success: bool) -> None:
    _recent_deploy_results.append(success)
    if not _recent_deploy_results:
        deploy_success_rate.set(0.0)
        return
    ratio = sum(1 for item in _recent_deploy_results if item) / len(_recent_deploy_results)
    deploy_success_rate.set(ratio)
