import pytest
from unittest.mock import patch
from generate_place_ids import get_place_name_and_id

@patch('requests.request')
def test_get_place_name_and_id_ambiguous(mock_get):
    # Mocking a response with 2 results
    mock_get.return_value.json.return_value = {
        'results': [
            {'name': 'Brewery A', 'place_id': '123'},
            {'name': 'Brewery B', 'place_id': '456'}
        ]
    }

    # We expect a ValueError because it's ambiguous
    with pytest.raises(ValueError, match=r"(?i)ambiguous result"):
        get_place_name_and_id("Signature")
