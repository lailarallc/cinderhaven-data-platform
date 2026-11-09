"""pytest plugin: a skip anywhere fails the run (U3).

A silently skipped acceptance suite is worse than a failing one. Loaded for
every run by pytest.ini (`-p skip_is_failure`).
"""


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if skipped and session.exitstatus == 0:
        session.exitstatus = 1
        if reporter:
            reporter.write_line(f"skip_is_failure: {len(skipped)} skipped test(s) fail the run", red=True)
