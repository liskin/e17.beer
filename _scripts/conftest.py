import gc
import os


def pytest_configure(config):
    os.environ["GOOGLE_MAPS_API_KEY"] = "__invalid_api_key_for_tests__"


def pytest_unconfigure(config):
    import update_places

    # destroy grpc clients to avoid waiting a few seconds for the grpc timer thread to shut down
    update_places.client = None
    gc.collect()
