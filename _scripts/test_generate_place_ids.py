from unittest.mock import MagicMock

import pytest

from generate_place_ids import get_place_data_from_api


def test_get_place_data_from_api_ambiguous():
    # Create mock objects that mimic the Google Library's attributes
    place_a = MagicMock()
    place_a.display_name.text = "Brewery A"
    place_a.id = "123"

    place_b = MagicMock()
    place_b.display_name.text = "Brewery B"
    place_b.id = "456"

    # Define the return value of the API call
    mock_response = MagicMock()
    mock_response.places = [place_a, place_b]

    mock_client = MagicMock()
    mock_client.search_text.return_value = mock_response

    # We expect an error because result is ambiguous
    with pytest.raises(RuntimeError, match=r"(?i)ambiguous result"):
        get_place_data_from_api(mock_client, "Brewery")
