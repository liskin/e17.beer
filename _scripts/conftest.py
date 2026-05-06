import os


def pytest_configure(config):
    os.environ["GOOGLE_MAPS_API_KEY"] = "__invalid_api_key_for_tests__"
