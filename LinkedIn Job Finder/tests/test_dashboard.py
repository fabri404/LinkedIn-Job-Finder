import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import dashboard
import dashboard_data as data
import loop_control

LOG = """\
2026-10-20 10:00:00,001 INFO Job Finder v3 | dry-run=False | cupo diario 100 | 45 canales | 0 en cola
2026-10-20 10:01:00,001 ERROR Chrome dejó de responder (ReadTimeoutError) en la fuente 0
2026-10-20 11:00:00,001 INFO Job Finder v3 | dry-run=False | cupo diario 100 | 45 canales | 2 en cola
2026-10-20 11:05:00,001 INFO https://www.linkedin.com/groups/13927947/: 90 posts leídos.
2026-10-20 11:06:00,001 INFO BORRADOR → rrhh@acme.com | Postulación: QA | CV.pdf
2026-10-20 11:07:00,001 ERROR LinkedIn pidió verificación de seguridad (checkpoint); freno el loop.
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "job_finder.log").write_text(LOG, encoding="utf-8")
    (data_dir / "state.json").write_text(json.dumps({"pending": [{}, {}]}), encoding="utf-8")
    (data_dir / "enviados.csv").write_text("fecha,email,puesto,asunto,cv,post_url\n", encoding="utf-8")
    channels = tmp_path / "channels.txt"
    channels.write_text("https://www.linkedin.com/groups/1/\n" + data.CONTENT_SEARCH_URL.format("%22enviar%20cv%22")
                        + "\n", encoding="utf-8")
    monkeypatch.setattr(data, "DATA_DIR", data_dir)
    monkeypatch.setattr(data, "LOG_FILE", data_dir / "job_finder.log")
    monkeypatch.setattr(data, "CHANNELS_FILE", channels)
    return tmp_path


def test_status_snapshot_only_reports_events_since_last_start(workspace):
    status = data.status_snapshot()

    assert status.started_at == "2026-10-20 11:00:00"
    assert status.current_source == "grupo 13927947"
    assert status.last_error.endswith("freno el loop.")
    assert "checkpoint" in status.alert
    assert status.pending == 2


def test_add_search_writes_past_week_url_and_rejects_duplicates(workspace):
    assert data.add_search("  qa   tester  ") is True
    assert data.add_search("qa tester") is False
    assert data.list_searches() == ['"enviar cv"', "qa tester"]
    assert "datePosted=%22past-week%22" in data.CHANNELS_FILE.read_text().splitlines()[-1]


def test_remove_search_keeps_other_sources(workspace):
    assert data.remove_search('"enviar cv"') is True
    assert data.list_searches() == []
    assert data.other_sources_count() == 1


@pytest.mark.parametrize("query", ["", "   ", "x" * (data.MAX_QUERY_CHARS + 1)])
def test_clean_query_with_invalid_text_raises_value_error(query):
    with pytest.raises(ValueError):
        data.clean_query(query)


@pytest.mark.parametrize(("url", "label"), [
    ("https://www.linkedin.com/feed/", "feed"),
    ("https://www.linkedin.com/company/revistaempleo/posts/?feedView=all", "página revistaempleo"),
    (data.CONTENT_SEARCH_URL.format("%22enviar%20cv%22%20qa"), 'búsqueda: "enviar cv" qa'),
])
def test_source_label_describes_each_source(url, label):
    assert data.source_label(url) == label


@pytest.mark.parametrize(("args", "expected"), [
    (["python3", "main.py"], True),
    (["/usr/bin/python3.12", "main.py", "--once"], True),
    (["python3", "dashboard.py"], False),
    (["systemd-inhibit", "--what=idle:sleep", "python3", "main.py"], False),
])
def test_is_loop_cmdline_matches_only_the_python_process(args, expected):
    assert loop_control.is_loop_cmdline(args) is expected


def test_find_loop_pid_requires_project_cwd(tmp_path, monkeypatch):
    project = tmp_path / "proyecto"
    project.mkdir()
    for pid, cwd in (("100", tmp_path), ("200", project)):
        (tmp_path / "proc" / pid).mkdir(parents=True)
        (tmp_path / "proc" / pid / "cmdline").write_bytes(b"python3\0main.py\0")
        (tmp_path / "proc" / pid / "cwd").symlink_to(cwd)
    monkeypatch.setattr(loop_control, "BASE_DIR", project)

    assert loop_control.find_loop_pid(tmp_path / "proc") == 200


def test_loop_command_once_adds_flag():
    assert loop_control.loop_command(loop_control.LoopMode.ONCE)[-2:] == ["main.py", "--once"]


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def _request(port, method, path, headers):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(method, path, body=b"{}", headers=headers | {"Content-Length": "2"})
    response = conn.getresponse()
    return response.status, json.loads(response.read())


def test_api_with_foreign_host_header_returns_403(server):
    status, _ = _request(server, "GET", "/api/searches", {"Host": "evil.example:8765"})

    assert status == 403


def test_api_post_without_dashboard_header_returns_403(server):
    status, body = _request(server, "POST", "/api/loop/stop", {"Host": f"localhost:{dashboard.PORT}"})

    assert status == 403
    assert "header" in body["error"]


def test_api_unknown_route_returns_404(server):
    status, _ = _request(server, "GET", "/api/nada", {"Host": f"localhost:{dashboard.PORT}"})

    assert status == 404
