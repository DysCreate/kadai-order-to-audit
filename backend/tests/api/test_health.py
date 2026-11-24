"""Health endpoint checks used by Render and the deployment workflow."""

from django.urls import reverse


def test_health_reports_ok_and_deployed_commit(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234")

    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "commit": "abc1234"}
