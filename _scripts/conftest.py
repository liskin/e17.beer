import gc
import os


def pytest_configure(config):
    os.environ["GOOGLE_MAPS_API_KEY"] = "__invalid_api_key_for_tests__"


def pytest_unconfigure(config):
    import generate_place_ids
    import update_places

    # destroy grpc clients to avoid waiting a few seconds for the grpc timer thread to shut down
    generate_place_ids.client = None
    update_places.client = None
    gc.collect()
