import unittest
from unittest.mock import patch
from update_places import get_week_percentage, fetch_place_data

class TestUpdatePlaces(unittest.TestCase):

    # --- PERCENTAGE CALCULATION TESTS ---
    def test_week_percentage_start(self):
        """Sunday 00:00 should be 0.0"""
        self.assertEqual(get_week_percentage(0, '0000'), 0.0)

    def test_week_percentage_end(self):
        """Saturday 23:59 should be high precision (99.9901)"""
        # ((6*24*60 + 23*60 + 59) / 10080) * 100 = 99.990079... -> 99.9901
        self.assertEqual(get_week_percentage(6, '2359'), 99.9901)

    def test_week_percentage_midweek(self):
        """Wednesday 12:00 should be exactly 50.0"""
        self.assertEqual(get_week_percentage(3, '1200'), 50.0)

    def test_midnight_transition(self):
        """Test Monday midnight vs Sunday midnight"""
        sun_midnight = get_week_percentage(0, '0000') # Start of week
        mon_midnight = get_week_percentage(1, '0000') # 1/7th of the way
        self.assertEqual(sun_midnight, 0.0)
        self.assertEqual(mon_midnight, 14.2857) # (1440/10080)*100 ~ 1/7

    # --- VALIDATION TESTS ---
    def test_invalid_day_index(self):
        """Should raise ValueError for day index 7"""
        with self.assertRaises(ValueError):
            get_week_percentage(7, '1200')

    def test_invalid_time_format(self):
        """Should raise ValueError for any string that isn't exactly HHMM"""
        # Test: Too short
        with self.assertRaises(ValueError):
            get_week_percentage(1, '900')

            # Test: Logic error in input (Hours cannot be 90)
        with self.assertRaises(ValueError):
            get_week_percentage(1, '9000')

        # Test: Not numeric
        with self.assertRaises(ValueError):
            get_week_percentage(1, 'ABCD')

    def test_valid_time_format(self):
        """Should complete without raising an error"""
        # 09:00 AM on Monday
        try:
            get_week_percentage(1, '0900')
        except ValueError:
            self.fail("get_week_percentage() raised ValueError unexpectedly for '0900'!")


    # --- API RETURN TESTS ---
    @patch('update_places.gmaps.place')
    def test_incomplete_data_handling(self, mock_place):
        """Verify 'incomplete' error message is raised when 'close' is missing"""
        mock_place.return_value = {
            'status': 'OK',
            'result': {
                'name': 'Test Place',
                'opening_hours': {'periods': [{'open': {'day': 1, 'time': '0900'}}]}
            }
        }
        with self.assertRaises(KeyError) as cm:
            fetch_place_data('dummy_id')
        self.assertIn("incomplete", str(cm.exception))

    @patch('update_places.gmaps.place')
    def test_fetch_place_api_error_message_passthrough(self, mock_place):
        """Verify the script uses Google's specific error message if provided"""
        google_reason = "Invalid 'place_id' parameter." # A specific error message

        mock_place.return_value = {
            'status': 'REQUEST_DENIED',
            'error_message': google_reason
        }

        with self.assertRaises(ValueError) as cm:
            fetch_place_data('any_id')

        # This confirms your code DID NOT overwrite 'google_reason' with your own fallback text
        self.assertIn(google_reason, str(cm.exception))

if __name__ == '__main__':
    unittest.main()