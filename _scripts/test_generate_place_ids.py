from unittest.mock import patch

import pytest

from generate_place_ids import get_place_data_from_api


def test_get_place_data_from_api_ambiguous(mocker):
    mock_search = mocker.patch("update_places.client.search_text")

    # Create mock objects that mimic the Google Library's attributes
    place_a = mocker.MagicMock()
    place_a.display_name.text = "Brewery A"
    place_a.id = "123"

    place_b = mocker.MagicMock()
    place_b.display_name.text = "Brewery B"
    place_b.id = "456"

    # Define the return value of the API call
    mock_response = mocker.MagicMock()
    mock_response.places = [place_a, place_b]
    mock_search.return_value = mock_response

    # We expect a ValueError because result is ambiguous
    with pytest.raises(ValueError, match=r"(?i)ambiguous result"):
        get_place_data_from_api("Brewery")
