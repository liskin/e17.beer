#!/usr/bin/env python3

import os
import requests
import json
import pprint

from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
if not API_KEY:
    raise ValueError("No API Key found! Check your .env file.")

# gmaps = googlemaps.Client(key = API_KEY)
request = str(input('Enter the address/Place ID:\n'))
# request.split()
# request = '%20'.join(request)
URL = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={request}&key={API_KEY}"


payload={}
headers = {}


response = requests.request("GET", URL, headers=headers, data=payload)
print(response.status_code)
response = response.text
data = json.loads(response)
print(data)


place_id = data['results'][0]['place_id']
# print(place_id)
PLACE_ID_URL = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&key={API_KEY}"

new_response = requests.request("GET", PLACE_ID_URL, headers=headers, data=payload)
new_response = new_response.text
new_data = json.loads(new_response)

# pprint.pprint(new_data)

name = new_data['result']['name']
adddress = new_data['result']['formatted_address']
onMap = new_data['result']['url']
try:
    website = new_data['result']['website']
except:
    pass

print(f'''Place name: \n        {name}\n''')
print(f'''Address: \n       {adddress}\n''')
print(f''''Google maps: \n       {onMap}\n''')
try:
    print(f'''Website: \n       {website}\n''')
except:
    pass

if 'opening_hours' in new_data['result']: 
    if 'weekday_text' in new_data['result']['opening_hours']:
        print('Opening hours:')
        for day in new_data['result']['opening_hours']['weekday_text']:
            print(f'''       {day}''')


