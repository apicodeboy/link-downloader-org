import io
import json
import zipfile

from app.models import FileKind
from app.publishing.providers import MetricoolProvider
from tests.conftest import PASSWORD  # noqa: F401


def _video(admin, settings):
    from app.db import session_scope
    from app.models import MediaFile

    d = settings.media_dir / "pj"
    d.mkdir(parents=True)
    (d / "video.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42fakevideo")
    with session_scope() as db:
        mf = MediaFile(user_id=admin, kind=FileKind.PROCESSED, path="pj/video.mp4", filename="clip.mp4",
                       mime_type="video/mp4", size_bytes=10)
        db.add(mf)
        db.flush()
        return mf.id


def test_publishing_flow_never_auto_publishes(client, admin, settings, monkeypatch):
    monkeypatch.setattr(settings, "publishing_accounts", [{"id": "ig-main", "network": "instagram", "label": "@brand"}])
    fid = _video(admin, settings)
    cfg = client.get("/api/publishing/config").json()
    assert cfg["provider"] == "none" and cfg["submit_enabled"] is False
    assert cfg["destinations"] == [{"id": "ig-main", "network": "instagram", "label": "@brand"}]

    r = client.post("/api/publishing/jobs", json={"media_file_id": fid, "caption": "Nouvelle vidéo 🎬\nLigne 2",
                                                  "hashtags": ["reels", "#Café"], "destinations": ["nope"]})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "unknown_destination"

    r = client.post("/api/publishing/jobs", json={"media_file_id": fid, "caption": "Nouvelle vidéo 🎬\nLigne 2",
                                                  "hashtags": ["reels", "#Café", "reels"]})
    pj = r.json()
    assert r.status_code == 201 and pj["status"] == "draft" and pj["hashtags"] == ["#reels", "#Café"]

    assert client.post(f"/api/publishing/jobs/{pj['id']}/approve").json()["detail"]["code"] == "no_destinations"
    client.patch(f"/api/publishing/jobs/{pj['id']}", json={"destinations": ["ig-main"]})
    approved = client.post(f"/api/publishing/jobs/{pj['id']}/approve").json()
    assert approved["status"] == "approved"

    # Editing after approval drops the approval.
    edited = client.patch(f"/api/publishing/jobs/{pj['id']}", json={"caption": "changed"}).json()
    assert edited["status"] == "draft" and edited["approved_at"] is None
    client.patch(f"/api/publishing/jobs/{pj['id']}", json={"caption": "Nouvelle vidéo 🎬\nLigne 2"})
    client.post(f"/api/publishing/jobs/{pj['id']}/approve")

    r = client.post(f"/api/publishing/jobs/{pj['id']}/submit")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "submit_disabled"

    monkeypatch.setattr(settings, "publishing_submit_enabled", True)
    monkeypatch.setattr(settings, "publishing_provider", "metricool")
    r = client.post(f"/api/publishing/jobs/{pj['id']}/submit")
    assert r.status_code == 501 and r.json()["detail"]["code"] == "not_verified"

    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/publishing/jobs/{pj['id']}/package").content))
    assert sorted(z.namelist()) == ["caption.txt", "clip.mp4"]
    assert z.read("caption.txt").decode("utf-8") == "Nouvelle vidéo 🎬\nLigne 2\n\n#reels #Café"


def test_submit_requires_approval(client, admin, settings, monkeypatch):
    monkeypatch.setattr(settings, "publishing_submit_enabled", True)
    fid = _video(admin, settings)
    pj = client.post("/api/publishing/jobs", json={"media_file_id": fid}).json()
    r = client.post(f"/api/publishing/jobs/{pj['id']}/submit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_approved"


def test_metricool_connection_check_uses_documented_endpoint(settings):
    settings.metricool_user_token = "tok"
    settings.metricool_user_id = "42"
    settings.metricool_blog_id = "7"
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("X-mc-auth")
        seen["method"] = req.get_method()
        return Resp(json.dumps([{"id": 7, "label": "My Brand"}]).encode())

    result = MetricoolProvider(settings, opener=opener).check_connection()
    assert result == {"ok": True, "message": "Connected. 1 brand(s) visible.", "brands": ["My Brand"]}
    assert seen == {"url": "https://app.metricool.com/api/admin/simpleProfiles?userId=42", "auth": "tok",
                    "method": "GET"}


def test_metricool_unconfigured(settings):
    assert MetricoolProvider(settings).check_connection()["ok"] is False
