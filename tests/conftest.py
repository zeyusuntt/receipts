def pytest_configure(config):
    config.addinivalue_line("markers", "docker: requires a reachable local Docker daemon")
    config.addinivalue_line("markers", "live: calls an explicitly enabled external service")

