import pytest

from thinkdome.control_plane.contracts import SandboxPlacementRequest
from thinkdome.control_plane.quota import ProjectQuota, ProjectUsage, QuotaExceededError


def test_project_quota_rejects_cpu_overcommit():
    request = SandboxPlacementRequest(organization_id="org", project_id="project", sandbox_id="sb", cpu_millis=1000)
    with pytest.raises(QuotaExceededError, match="CPU"):
        ProjectQuota(max_cpu_millis=1000).check(request, ProjectUsage(cpu_millis=500))
