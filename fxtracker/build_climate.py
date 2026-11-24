#!/usr/bin/env python3
"""Precompute monthly climate-comfort scores per country -> public/climate.json.

"Best time to travel" has no API, so we derive a weather-comfort proxy: for one
point per country (see sample_point) we pull five years of daily temperature +
rainfall from Open-Meteo (free, no key), aggregate to months, and score each
month 0-100. Top destinations get curated best-month overrides on top (the
"hybrid" approach).

Run once (re-run to refresh): python3 -m fxtracker.build_climate
Only some countries:          python3 -m fxtracker.build_climate FR NO CL
Rain only (the guide's month table; nothing else in a row changes):
                              python3 -m fxtracker.build_climate --rain [FR NO CL]
Elevation only (the HIGH_M check; nothing else in a row changes):
                              python3 -m fxtracker.build_climate --elev [FR NO CL]
It writes a static file the website reads, so there are no live weather calls.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import defaultdict

from . import geo
from . import rates  # reuse the verifying SSL context + fetch_json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOJSON = os.path.join(ROOT, "public", "world.geojson")
OUT = os.path.join(ROOT, "public", "climate.json")
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
# A five-year window over the last COMPLETE calendar years, derived from the
# clock. Was hardcoded to 2024 alone, which had two problems: it could never
# refresh, and one year is a thin basis for "typical" weather — a single wet or
# freak-hot year permanently skewed a country's best months. Five years averages
# anomalies out while staying recent enough to reflect current climate. The end
# year is the last complete one, since a partial year would bias whichever
# months have already happened.
_LAST_COMPLETE = time.gmtime().tm_year - 1
WINDOW_YEARS = 5
YEAR = ("%d-01-01" % (_LAST_COMPLETE - WINDOW_YEARS + 1), "%d-12-31" % _LAST_COMPLETE)
# The same window as the guide's month table words it ("2021–2025"), stored on
# each row a run writes, since a merge can leave rows from different runs.
WINDOW = "%s–%s" % (YEAR[0][:4], YEAR[1][:4])
# A rainy day: more than this much rain (mm) in the day.
RAIN_DAY_MM = 1.0

# Curated best-months for major destinations (1=Jan). Overlaid on weather scores
# so the "best months" reflect travel knowledge (shoulder seasons, dry seasons,
# festivals) for the places people most often ask about.
CURATED = {
    "JP": [3, 4, 10, 11], "FR": [5, 6, 9, 10], "IT": [4, 5, 9, 10],
    "ES": [4, 5, 9, 10], "GB": [5, 6, 7, 9], "GR": [5, 6, 9, 10],
    "PT": [5, 6, 9, 10], "HR": [5, 6, 9], "DE": [5, 6, 9],
    "TH": [11, 12, 1, 2], "VN": [2, 3, 4, 11], "ID": [5, 6, 7, 8, 9],
    "IN": [10, 11, 2, 3], "MY": [1, 2, 6, 7], "PH": [12, 1, 2, 3],
    "KR": [4, 5, 10, 11], "TR": [4, 5, 9, 10], "AE": [11, 12, 1, 2, 3],
    "MX": [11, 12, 3, 4], "BR": [4, 5, 9, 10], "AR": [3, 4, 10, 11],
    "PE": [5, 6, 7, 8], "CL": [3, 4, 11, 12], "CO": [12, 1, 2, 7],
    "CR": [12, 1, 2, 3, 4], "US": [5, 6, 9, 10], "CA": [6, 7, 8, 9],
    "ZA": [9, 10, 4, 5], "EG": [10, 11, 3, 4], "MA": [3, 4, 5, 10],
    "KE": [1, 2, 6, 7, 8, 9, 10], "TZ": [6, 7, 8, 9], "AU": [3, 4, 9, 10, 11],
    "NZ": [11, 12, 1, 2, 3], "FJ": [5, 6, 7, 8, 9, 10],
}


# Where to sample, as (lat, lon, place, reason): every country with a month
# table names its place (review 2026-11-23 item 1; the tables reach every
# guide with MONTH_TABLE_ALL). The first 41 (2026-07) replaced geometric
# points that were nowhere anyone goes: a vertex average over every part put France's
# sample in the Atlantic west of Morocco (dragged by French Guiana) and Fiji's
# in the Indian Ocean; the big ones' interior points were the US at Mt Hood,
# Canada in Nunavut, Chile in the high Andes, China on the Gansu plateau, Peru
# in the Ucayali Amazon (25°C every month while Cusco's dry season is
# 10-13°C), Iceland's central highlands, Kenya's Samburu lowlands. Tel Aviv,
# not Jerusalem, for Israel: the simplified map puts East Jerusalem in the
# Palestine polygon. The rest (2026-11) fixed the same fault at smaller
# scale: the Dominican Republic read 18°C in January from its central
# mountains (the coast is ~25°C), Switzerland 13°C in July from the Alps,
# Timor-Leste 18-21°C (Dili ~27°C). Rule for every point: the place most
# visitors actually spend time — usually the main tourist city or the capital
# at normal altitude, a beach hub where the beaches are the draw. Re-judged by
# it (2026-11-24), six of the 2026-07 points moved: Jakarta to Bali, Suva (the
# wet side) to Nadi, Zagreb to Split, Mexico City (2,230 m) to Cancún, Bogotá
# (2,550 m) to Cartagena, Praia to Sal; the rest stand. Coordinates
# cross-checked against GeoNames (Open-Meteo's geocoder): each within 10 km
# of the town's own GeoNames point (the big cities' centres, Dubai's or
# Dhaka's, sit a few km from it).
# The place name ships in climate.json ("at") so the guide can say WHERE its
# temperatures are measured; a country on the geometric fallback (LEFT_ALONE)
# carries none, and the guide says "one representative point" rather than
# inventing a name. Points above HIGH_M or with a best score under LOW_BEST
# are listed in REVIEWED with why they stand.
SAMPLE_POINTS = {
    "AE": (25.204, 55.270, "Dubai", "where most visitors stay"),
    "AF": (34.555, 69.207, "Kabul", "capital; nearly every visit starts there"),
    "AL": (41.328, 19.819, "Tirana", "capital, 30 km from the coast at 110 m"),
    "AM": (40.179, 44.499, "Yerevan", "capital, where visitors base; the old point read the cold uplands"),
    "AO": (-8.837, 13.234, "Luanda", "capital and arrival city"),
    "AR": (-34.604, -58.382, "Buenos Aires", "capital of a multi-part country"),
    "AT": (48.208, 16.373, "Vienna", "most-visited city; the old point was in the Alps"),
    "AU": (-33.869, 151.209, "Sydney", "main city visitors go to (Canberra is atypical)"),
    "AW": (12.524, -70.027, "Oranjestad", "capital, beside the resort beaches"),
    "AZ": (40.409, 49.867, "Baku", "capital, where most visitors stay"),
    "BA": (43.856, 18.413, "Sarajevo", "capital and most-visited city"),
    "BB": (13.097, -59.613, "Bridgetown", "capital, on the west-coast beaches"),
    "BD": (23.764, 90.389, "Dhaka", "capital and arrival city"),
    "BE": (50.847, 4.357, "Brussels", "capital and most-visited city"),
    "BF": (12.371, -1.520, "Ouagadougou", "capital and arrival city"),
    "BG": (42.698, 23.322, "Sofia", "capital and main arrival city"),
    "BH": (26.228, 50.586, "Manama", "capital, where visitors stay"),
    "BI": (-3.383, 29.361, "Bujumbura", "largest city and airport, on Lake Tanganyika"),
    "BJ": (6.366, 2.433, "Cotonou", "main city and airport, on the coast"),
    "BN": (4.903, 114.940, "Bandar Seri Begawan", "capital, where visitors stay"),
    "BO": (-16.495, -68.133, "La Paz", "seat of government, the big-country rule"),
    "BR": (-22.907, -43.173, "Rio de Janeiro", "main city visitors go to"),
    "BS": (25.048, -77.355, "Nassau", "capital; most visitors stay on New Providence"),
    "BT": (27.430, 89.410, "Paro", "where visitors fly in and start their tours"),
    "BW": (-19.983, 23.417, "Maun", "gateway to the Okavango Delta, the main draw"),
    "BY": (53.904, 27.562, "Minsk", "capital and main destination"),
    "BZ": (17.916, -87.966, "San Pedro, Ambergris Caye", "the cayes and the reef are the main draw"),
    "CA": (45.421, -75.697, "Ottawa", "capital; the interior point was in Nunavut"),
    "CD": (-4.322, 15.312, "Kinshasa", "capital and arrival city"),
    "CF": (4.394, 18.558, "Bangui", "capital and arrival city"),
    "CG": (-4.263, 15.242, "Brazzaville", "capital and arrival city"),
    "CH": (47.377, 8.540, "Zürich", "largest city and main airport; the old point was in the Alps"),
    "CI": (5.360, -4.008, "Abidjan", "main city and airport, on the coast"),
    "CL": (-33.449, -70.669, "Santiago", "capital; the interior point was in the high Andes"),
    "CM": (4.048, 9.704, "Douala", "largest city and main airport"),
    "CN": (39.904, 116.407, "Beijing", "capital; the interior point was on the Gansu plateau"),
    "CO": (10.391, -75.479, "Cartagena", "the main leisure destination, at sea level; Bogotá is at 2,550 m"),
    "CU": (23.113, -82.366, "Havana", "capital and most-visited city"),
    "CV": (16.598, -22.905, "Santa Maria, Sal", "Sal's beach resorts, where most visitors stay (Praia, the capital, is on Santiago)"),
    "CW": (12.109, -68.932, "Willemstad", "capital, beside the main beaches"),
    "CY": (34.707, 33.022, "Limassol", "the south-coast resorts are the draw; Limassol sits between Paphos and Larnaca"),
    "CZ": (50.076, 14.438, "Prague", "capital and most-visited city"),
    "DE": (52.520, 13.405, "Berlin", "capital and most-visited city"),
    "DJ": (11.589, 43.145, "Djibouti City", "capital, where nearly all visitors stay"),
    "DK": (55.676, 12.568, "Copenhagen", "capital and most-visited city"),
    "DO": (18.582, -68.405, "Punta Cana", "Punta Cana–Bávaro is where most visitors stay; the old point was in the mountains"),
    "DZ": (36.754, 3.059, "Algiers", "capital and arrival city"),
    "EC": (-0.220, -78.510, "Quito", "capital, where nearly every trip starts"),
    "EE": (59.437, 24.754, "Tallinn", "capital and most-visited city"),
    "EG": (30.044, 31.236, "Cairo", "Cairo and the pyramids are on nearly every itinerary"),
    "EH": (23.684, -15.958, "Dakhla", "the lagoon town is the main draw; the old point was in the inland desert"),
    "ER": (15.322, 38.925, "Asmara", "capital, where visitors stay"),
    "ES": (41.385, 2.173, "Barcelona", "most-visited city, with the Mediterranean climate of the coasts"),
    "ET": (9.030, 38.740, "Addis Ababa", "capital and arrival city"),
    "FI": (60.170, 24.938, "Helsinki", "capital and most-visited city"),
    "FJ": (-17.803, 177.416, "Nadi", "the airport and the Denarau resorts, on the dry side (Suva, the capital, is on the wet side)"),
    "FK": (-51.697, -57.852, "Stanley", "capital, where nearly all visitors arrive"),
    "FO": (62.011, -6.776, "Tórshavn", "capital of a multi-part country"),
    "FR": (48.857, 2.352, "Paris", "capital; the vertex average fell in the Atlantic"),
    "GA": (0.416, 9.467, "Libreville", "capital and arrival city"),
    "GB": (51.507, -0.128, "London", "capital of a multi-part country"),
    "GE": (41.716, 44.783, "Tbilisi", "capital, where visitors base"),
    "GG": (49.456, -2.537, "St Peter Port", "capital and harbour"),
    "GH": (5.604, -0.187, "Accra", "capital and arrival city"),
    # Greenland's geometric point is on the ice sheet (-38 °C in January, every
    # month scoring 0, so "best months" fell back to January-March on the live
    # guide). Nuuk is where visitors arrive and the only town with a climate
    # anyone plans around.
    "GL": (64.175, -51.738, "Nuuk", "where visitors arrive; the geometric point was on the ice sheet"),
    "GM": (13.454, -16.579, "Banjul", "capital, beside the resort strip"),
    "GN": (9.538, -13.677, "Conakry", "capital and arrival city"),
    "GQ": (3.751, 8.774, "Malabo", "capital, on Bioko"),
    "GR": (37.984, 23.728, "Athens", "capital of a multi-part country"),
    "GT": (14.557, -90.733, "Antigua Guatemala", "where most visitors stay"),
    "GU": (13.476, 144.749, "Hagåtña", "capital, beside the Tumon hotel strip"),
    "GW": (11.864, -15.598, "Bissau", "capital and arrival city"),
    "GY": (6.801, -58.155, "Georgetown", "capital and arrival city"),
    "HK": (22.298, 114.172, "Kowloon", "Victoria Harbour, where visitors stay; the old point was in the hills"),
    "HN": (16.316, -86.540, "Roatán", "the Bay Islands are the main draw"),
    "HR": (43.508, 16.440, "Split", "the Dalmatian coast is the draw; Split sits between Zadar and Dubrovnik"),
    "HT": (18.594, -72.307, "Port-au-Prince", "capital of a multi-part country"),
    "HU": (47.498, 19.040, "Budapest", "capital and most-visited city"),
    "ID": (-8.650, 115.216, "Denpasar, Bali", "Bali is where most visitors go; Denpasar sits between Kuta, Sanur and Ubud"),
    "IE": (53.350, -6.260, "Dublin", "capital and most-visited city"),
    "IL": (32.085, 34.782, "Tel Aviv", "main city (the map puts East Jerusalem in Palestine)"),
    "IM": (54.150, -4.482, "Douglas", "capital, where most visitors stay"),
    "IN": (28.614, 77.209, "New Delhi", "capital, the big-country rule"),
    "IQ": (33.315, 44.366, "Baghdad", "capital, with the climate of Karbala and Najaf"),
    "IR": (35.689, 51.389, "Tehran", "capital and arrival city"),
    "IS": (64.146, -21.942, "Reykjavík", "capital; the interior point was in the central highlands"),
    "IT": (41.903, 12.496, "Rome", "capital of a multi-part country"),
    "JM": (18.476, -77.893, "Montego Bay", "main resort area and airport"),
    "JO": (31.954, 35.911, "Amman", "capital, where visitors base"),
    "JP": (35.676, 139.650, "Tokyo", "capital of a multi-part country"),
    "KE": (-1.286, 36.817, "Nairobi", "capital; the interior point was in the Samburu lowlands"),
    "KG": (42.875, 74.570, "Bishkek", "capital and arrival city"),
    "KH": (13.362, 103.860, "Siem Reap", "Angkor is the main draw"),
    "KP": (39.039, 125.763, "Pyongyang", "capital, where tours are based"),
    "KR": (37.567, 126.978, "Seoul", "capital and most-visited city"),
    "KW": (29.376, 47.977, "Kuwait City", "capital, where visitors stay"),
    "KZ": (43.238, 76.946, "Almaty", "largest city and main airport"),
    "LA": (19.886, 102.135, "Luang Prabang", "the most-visited town"),
    "LB": (33.894, 35.502, "Beirut", "capital and arrival city"),
    "LK": (6.927, 79.861, "Colombo", "arrival city, with the west and south coasts' monsoon"),
    "LR": (6.301, -10.797, "Monrovia", "capital and arrival city"),
    "LS": (-29.316, 27.486, "Maseru", "capital and arrival point"),
    "LT": (54.687, 25.280, "Vilnius", "capital and most-visited city"),
    "LU": (49.612, 6.130, "Luxembourg City", "capital and most-visited city"),
    "LV": (56.950, 24.105, "Riga", "capital and most-visited city"),
    "LY": (32.887, 13.191, "Tripoli", "capital and arrival city"),
    "MA": (31.629, -7.981, "Marrakech", "main city visitors go to"),
    "MD": (47.011, 28.863, "Chișinău", "capital and arrival city"),
    "ME": (42.288, 18.840, "Budva", "the coast is the main draw; Budva is its biggest resort"),
    "MG": (-18.879, 47.508, "Antananarivo", "capital, where every trip starts"),
    "MK": (41.117, 20.802, "Ohrid", "Lake Ohrid is the main draw"),
    "ML": (12.639, -8.003, "Bamako", "capital and arrival city"),
    "MM": (16.840, 96.173, "Yangon", "main arrival city"),
    "MN": (47.886, 106.906, "Ulaanbaatar", "capital, where nearly every trip starts"),
    "MR": (18.079, -15.965, "Nouakchott", "capital and arrival city"),
    "MU": (-20.013, 57.580, "Grand Baie", "biggest resort area; the old point was on the cooler central plateau"),
    "MW": (-14.020, 34.840, "Cape Maclear", "Lake Malawi is the main draw"),
    "MX": (21.161, -86.851, "Cancún", "Cancún and the Riviera Maya draw the most visitors; Mexico City is at 2,230 m"),
    "MY": (3.139, 101.687, "Kuala Lumpur", "capital of a multi-part country"),
    "MZ": (-25.969, 32.573, "Maputo", "capital, on the southern beach coast"),
    "NA": (-22.560, 17.083, "Windhoek", "capital, where road trips start"),
    "NC": (-22.276, 166.458, "Nouméa", "capital, where most visitors stay"),
    "NE": (13.512, 2.112, "Niamey", "capital and arrival city"),
    "NG": (6.455, 3.394, "Lagos", "largest city and main airport"),
    "NI": (11.930, -85.956, "Granada", "the most-visited town"),
    "NL": (52.370, 4.895, "Amsterdam", "capital and most-visited city"),
    "NO": (59.913, 10.752, "Oslo", "capital of a multi-part country"),
    "NP": (27.717, 85.324, "Kathmandu", "capital, where nearly every trip starts"),
    "NZ": (-41.286, 174.776, "Wellington", "capital of a multi-part country"),
    "OM": (23.588, 58.383, "Muscat", "capital of a multi-part country"),
    "PA": (8.983, -79.517, "Panama City", "capital and arrival city"),
    "PE": (-13.532, -71.967, "Cusco", "main city visitors go to; the interior point was in the Amazon"),
    "PG": (-9.443, 147.180, "Port Moresby", "capital of a multi-part country"),
    "PH": (14.600, 120.984, "Manila", "capital of a multi-part country"),
    "PK": (31.549, 74.344, "Lahore", "most-visited city"),
    "PL": (50.065, 19.945, "Kraków", "most-visited city"),
    "PR": (18.466, -66.106, "San Juan", "capital, where most visitors stay; the old point was in the mountains"),
    "PS": (31.705, 35.200, "Bethlehem", "the most-visited town"),
    "PT": (38.722, -9.139, "Lisbon", "capital and most-visited city"),
    "PY": (-25.286, -57.647, "Asunción", "capital and arrival city"),
    "QA": (25.286, 51.531, "Doha", "capital, where nearly all visitors stay"),
    "RO": (44.426, 26.103, "Bucharest", "capital and arrival city"),
    "RS": (44.787, 20.457, "Belgrade", "capital and most-visited city"),
    "RU": (55.756, 37.617, "Moscow", "capital of a multi-part country"),
    "RW": (-1.950, 30.059, "Kigali", "capital, where every trip starts"),
    "SA": (21.542, 39.198, "Jeddah", "gateway for most visitors (Mecca pilgrims and the Red Sea)"),
    "SB": (-9.433, 159.950, "Honiara", "capital of a multi-part country"),
    "SD": (15.552, 32.532, "Khartoum", "capital and arrival city"),
    "SE": (59.329, 18.069, "Stockholm", "capital and most-visited city; the old point was far north"),
    "SG": (1.290, 103.852, "central Singapore", "the city centre"),
    "SI": (46.056, 14.506, "Ljubljana", "capital and most-visited city"),
    "SK": (48.149, 17.107, "Bratislava", "capital and most-visited city"),
    "SL": (8.484, -13.234, "Freetown", "capital, beside the beaches"),
    "SN": (14.716, -17.467, "Dakar", "capital and arrival city"),
    "SO": (2.047, 45.318, "Mogadishu", "capital and arrival city"),
    "SR": (5.852, -55.204, "Paramaribo", "capital, where visitors base"),
    "SS": (4.859, 31.571, "Juba", "capital and arrival city"),
    "SV": (13.692, -89.218, "San Salvador", "capital, where most visitors stay"),
    "SY": (33.513, 36.292, "Damascus", "capital and arrival city"),
    "SZ": (-26.495, 31.388, "Manzini", "largest town, central to the main sights"),
    "TD": (12.134, 15.056, "N'Djamena", "capital and arrival city"),
    "TF": (-49.350, 70.220, "Port-aux-Français", "the only base visitors reach"),
    "TG": (6.131, 1.223, "Lomé", "capital and arrival city, on the coast"),
    "TH": (13.756, 100.502, "Bangkok", "capital and arrival city"),
    "TJ": (38.560, 68.787, "Dushanbe", "capital and arrival city"),
    "TL": (-8.556, 125.578, "Dili", "capital, where most visitors stay; the old point was in the mountains"),
    "TM": (37.950, 58.383, "Ashgabat", "capital and arrival city"),
    "TN": (35.826, 10.637, "Sousse", "the resort coast, where most visitors stay"),
    "TR": (41.008, 28.978, "Istanbul", "main city visitors go to (Ankara is atypical)"),
    "TT": (10.660, -61.508, "Port of Spain", "capital and Carnival city"),
    "TW": (25.033, 121.565, "Taipei", "capital and most-visited city; the old point was in the mountains"),
    "TZ": (-3.387, 36.683, "Arusha", "safari gateway (Dodoma is atypical)"),
    "UA": (50.450, 30.523, "Kyiv", "capital"),
    "UG": (0.348, 32.582, "Kampala", "capital, near Entebbe's airport"),
    "US": (38.907, -77.037, "Washington, D.C.", "capital; the interior point was on Mt Hood"),
    "UY": (-34.901, -56.164, "Montevideo", "capital, on the beach coast"),
    "UZ": (39.654, 66.976, "Samarkand", "centre of the Silk Road circuit"),
    "VE": (10.481, -66.904, "Caracas", "capital and arrival city"),
    "VN": (21.028, 105.854, "Hanoi", "capital"),
    "VU": (-17.734, 168.322, "Port Vila", "capital, where most visitors stay"),
    "XK": (42.663, 21.166, "Pristina", "capital and arrival city"),
    "YE": (15.369, 44.191, "Sanaa", "capital"),
    "ZA": (-33.925, 18.423, "Cape Town", "main city visitors go to"),
    "ZM": (-17.842, 25.854, "Livingstone", "Victoria Falls is the main draw"),
    "ZW": (-17.932, 25.831, "Victoria Falls", "the falls are the main draw"),
}
# Left on the geometric fallback on purpose, with why: the guide says "one
# representative point" for these.
LEFT_ALONE = {
    "CR": "review 2026-11-23: its geometric point already sits in the Central Valley near San José",
}
# An override must sit on (or just off the simplified coastline of) its own
# country — a typo'd coordinate should fail the build, not sample the sea.
MAX_OFFSHORE_KM = 40
# Except where the simplified map leaves the place out: these may sit up to
# OFF_MAP_KM from their country's outline, still enough to catch a typo that
# lands on another continent.
OFF_MAP = {
    "BS": "New Providence (Nassau) isn't on the simplified map",
    "CV": "Sal (Santa Maria) isn't on the simplified map",
    "EH": "the simplified map draws the coast about 200 km inland of Dakhla",
    "GQ": "Bioko (Malabo) isn't on the simplified map",
    "HN": "the Bay Islands (Roatán) aren't on the simplified map",
    "ID": "Bali isn't on the simplified map",
    "VU": "Efate (Port Vila) isn't on the simplified map",
    "ZM": "the simplified map draws the Zambezi south of Livingstone, inside Zimbabwe's outline",
}
OFF_MAP_KM = 250
# The build warns for a point above HIGH_M (Open-Meteo's elevation for it) or
# a year whose best month scores under LOW_BEST: either can mean a point
# visitors don't experience. Every one is checked by hand; REVIEWED says why
# it stands (scripts/test_climate_points.py holds the list complete).
HIGH_M = 800
LOW_BEST = 60
REVIEWED = {
    # High: the place visitors go is high (most of these countries are
    # plateau or highland throughout). Checked by hand 2026-11-24.
    "AF": "Kabul, where nearly every visit starts, is at 1,800 m",
    "AM": "Yerevan itself is at about 1,000 m; most of Armenia is higher",
    "BI": "Bujumbura is on Lake Tanganyika, Burundi's lowest ground (about 780 m)",
    "BO": "La Paz is at 3,650 m, and Uyuni, Titicaca and Sucre are high too (2026-07 point)",
    "BT": ("every visitor flies into Paro, and western Bhutan's sights are all at 2,000-2,500 m. The "
           "reanalysis reads Paro's spring far wetter than the valley's own records, which holds the "
           "scores near 60; its best months (Sep-Nov) are the main season"),
    "BW": "Maun is at 945 m; Botswana is Kalahari plateau throughout",
    "CR": "left alone (review 2026-11-23): the geometric point is in the Central Valley, where trips start",
    "EC": "Quito, where nearly every trip starts, is at 2,800 m",
    "ER": "Asmara, where visitors stay, is at 2,300 m",
    "ET": "Addis Ababa, where every trip starts, is at 2,400 m; the historic north is highland too",
    "GT": "Antigua is at 1,500 m, as are Lake Atitlán and the capital",
    "IR": "Tehran is at about 1,200 m; Isfahan and Shiraz are higher",
    "JO": "Amman is at 800-1,000 m, as is Petra",
    "KE": "Nairobi, where every trip starts, is at 1,670 m; the Masai Mara and the other safari parks are high too",
    "KZ": "Almaty, the main arrival city, is at the foot of the Tian Shan, about 850 m",
    "LS": "Maseru is Lesotho's lowest city; the whole country is above 1,400 m",
    "MG": "Antananarivo, where every trip starts, is on the central plateau at 1,250 m",
    "MN": "Ulaanbaatar, where nearly every trip starts, is at 1,300 m, as the steppe is",
    "NA": "Windhoek, where road trips start, is at 1,650 m on the central plateau",
    "NP": "Kathmandu, where nearly every trip starts, is at 1,300 m",
    "PE": ("Cusco, the base for Machu Picchu and the Sacred Valley, where most visitors spend their time, is "
           "at 3,340 m; Lima's coast is grey and cool most of the year"),
    "RW": "Kigali is at 1,550 m; Rwanda is highland throughout",
    "TJ": "Dushanbe, the arrival city, is at about 800 m",
    "TZ": "Arusha, the safari gateway, is at 1,360 m, on the plateau the northern parks share (Serengeti, Ngorongoro)",
    "UG": "Kampala is at 1,200 m beside Lake Victoria; most of Uganda is plateau",
    "VE": "Caracas, the arrival city, is in a valley at about 900 m",
    "YE": "Sanaa is at 2,250 m",
    "ZM": "Livingstone, by Victoria Falls, is at 965 m; Zambia is plateau throughout",
    "ZW": "Victoria Falls town is at 955 m; Zimbabwe is plateau throughout",
    # Low best month: the whole country's climate, not a bad point.
    "BN": "equatorial: hot and wet all year, Brunei alike everywhere",
    "FO": "cool North Atlantic summers: July about 11°C anywhere on the islands",
    "GL": "Arctic: Nuuk's warmest month is about 8°C, and it is the mild coast",
    "IS": "subarctic: Reykjavík's July is about 11°C, the island's mildest corner",
    "TF": "Kerguelen is cold and wet all year; Port-aux-Français is the only base",
}
ELEVATION = "https://api.open-meteo.com/v1/elevation"


def point_warnings(row):
    """Why a climate.json row needs a look by hand: its point sits above
    HIGH_M, or its best month scores under LOW_BEST. [] when neither."""
    out = []
    if (row.get("elev") or 0) > HIGH_M:
        out.append("point at %d m (over %d m)" % (row["elev"], HIGH_M))
    scores = [x for x in row.get("scores") or [] if x is not None]
    if scores and max(scores) < LOW_BEST:
        out.append("best month scores %d (under %d)" % (max(scores), LOW_BEST))
    return out


def elevations(points):
    """Open-Meteo's elevation (m, the same 90 m terrain model the archive
    answers with) for each (lat, lon), 100 per request."""
    out = []
    for i in range(0, len(points), 100):
        chunk = points[i:i + 100]
        url = "{0}?latitude={1}&longitude={2}".format(
            ELEVATION, ",".join("%.3f" % p[0] for p in chunk), ",".join("%.3f" % p[1] for p in chunk))
        got = rates.fetch_json(url, retries=4).get("elevation") or []
        if len(got) != len(chunk):
            raise ValueError("elevation API returned %d values for %d points" % (len(got), len(chunk)))
        out += [round(e) if isinstance(e, (int, float)) else None for e in got]
        time.sleep(0.9)
    return out


def centroid(geometry):
    """The old sample point: mean of every vertex of every part. Kept only so
    the rebuild can tell which countries' points moved."""
    polys = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polys = [polys]
    sx = sy = n = 0
    for poly in polys:
        for ring in poly:
            for lon, lat in ring:
                sx += lon
                sy += lat
                n += 1
    return (sx / n, sy / n) if n else (None, None)


def _km_to_geometry(pt, geometry):
    """Rough distance (km) from pt to the nearest vertex of the geometry."""
    return min(geo.dist_km(pt, v) for poly in geo.polygons(geometry)
               for ring in poly for v in ring)


def sample_point(iso, geometry):
    """(lon, lat) guaranteed on the country's own land, or None.

    1. SAMPLE_POINTS override.
    2. The vertex average of the main territory (largest ring), when that lands
       on it. Single-part countries keep exactly the point their data was built
       on, and it leans toward the (usually more visited) coast.
    3. Otherwise the largest ring's area centroid, nudged inside when a concave
       shape puts it outside (geo.ring_centroid, as app.js does for map pins).
    """
    if iso in SAMPLE_POINTS:
        lat, lon = SAMPLE_POINTS[iso][:2]
        pt = (lon, lat)
        if geo.in_geometry(pt, geometry) or _km_to_geometry(pt, geometry) <= (
                OFF_MAP_KM if iso in OFF_MAP else MAX_OFFSHORE_KM):
            return pt
        print("  {0}: override {1} is not on its own land — ignored".format(iso, pt))
    ring = geo.largest_ring(geometry)
    if not ring:
        return None
    mean = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    if geo.in_ring(mean, ring):
        return mean
    c = geo.ring_centroid(ring)
    if c and geo.in_ring(c, ring):
        return (c[0], c[1])
    return None


def sample_place(iso, pt):
    """The named place `pt` stands for, or None when it is a geometric point
    (an override that was rejected as off-land falls back to geometry too, so
    the name is only claimed when the point really is the override's)."""
    o = SAMPLE_POINTS.get(iso)
    return o[2] if o and pt == (o[1], o[0]) else None


# comfort()'s numbers, named so /how-grades-work (fxtracker/render_methodology.py)
# prints the ones in use: full marks for a month averaging COMFORT_LO-COMFORT_HI
# °C; HOT_PTS_PER_C off per degree above, COLD_PTS_PER_C per degree below;
# RAIN_PTS_PER_MM off per mm of the month's rain, at most RAIN_PTS_MAX.
COMFORT_LO, COMFORT_HI = 18, 26
HOT_PTS_PER_C, COLD_PTS_PER_C = 6, 4
RAIN_PTS_PER_MM, RAIN_PTS_MAX = 0.18, 60


def comfort(temp, rain):
    """0-100 monthly comfort from avg temp (C) and total rain (mm). Sweet spot
    ~18-26C; hot months penalized harder (humidity); rain reduces the score."""
    if temp is None:
        return None
    if temp > COMFORT_HI:
        t_pen = (temp - COMFORT_HI) * HOT_PTS_PER_C
    elif temp < COMFORT_LO:
        t_pen = (COMFORT_LO - temp) * COLD_PTS_PER_C
    else:
        t_pen = 0
    r_pen = min(RAIN_PTS_MAX, (rain or 0) * RAIN_PTS_PER_MM)
    return max(0, min(100, round(100 - t_pen - r_pen)))


def monthly_climate(lat, lon):
    """(scores, temps, rain_mm, rain_days, elev): twelve of each of the first
    four — comfort 0-100, mean °C, the month's rain total in mm and its days
    with more than RAIN_DAY_MM, both averaged over the window's years — and
    the point's elevation in metres as Open-Meteo resolves it (None if the
    answer carries none)."""
    url = ("{0}?latitude={1:.3f}&longitude={2:.3f}&start_date={3}&end_date={4}"
           "&daily=temperature_2m_mean,precipitation_sum&timezone=auto").format(
        ARCHIVE, lat, lon, YEAR[0], YEAR[1])
    data = rates.fetch_json(url, retries=4)
    daily = data.get("daily", {})
    times = daily.get("time", [])
    temps = daily.get("temperature_2m_mean", [])
    rains = daily.get("precipitation_sum", [])
    # Temperature averages over every matching day, but rain must be totalled
    # PER (year, month) and then averaged across years — comfort() expects one
    # month's rainfall in mm. Summing every matching day across a 5-year window
    # would report five Januaries of rain as one, quintupling the penalty and
    # driving nearly every score to the floor.
    mt = defaultdict(list)                          # month -> daily temps
    mr = defaultdict(lambda: defaultdict(float))    # month -> year -> total mm
    md = defaultdict(lambda: defaultdict(int))      # month -> year -> rainy days
    for t, tp, rn in zip(times, temps, rains):
        y, m = int(t[0:4]), int(t[5:7])
        if tp is not None:
            mt[m].append(tp)
        if rn is not None:
            mr[m][y] += rn
            md[m][y] += rn > RAIN_DAY_MM
    scores, temps, rain_mm, rain_days = [], [], [], []
    for m in range(1, 13):
        at = sum(mt[m]) / len(mt[m]) if mt[m] else None
        tr = (sum(mr[m].values()) / len(mr[m])) if mr[m] else 0
        scores.append(comfort(at, tr))
        temps.append(round(at) if at is not None else None)  # avg °C, shown in the guide
        rain_mm.append(round(tr) if mr[m] else None)
        rain_days.append(round(sum(md[m].values()) / len(md[m])) if md[m] else None)
    elev = data.get("elevation")
    return scores, temps, rain_mm, rain_days, (round(elev) if isinstance(elev, (int, float)) else None)


def monthly_scores(lat, lon):
    return monthly_climate(lat, lon)[:2]


def season_order(months):
    """Months in the order a season reads. A season that runs across New Year
    starts after its largest gap: [1, 2, 12] -> [12, 1, 2], so it reads
    "December, January and February", not "January, February and December".
    Anything else stays in calendar order ([3, 4, 10] -> "March, April and
    October")."""
    b = sorted(set(months))
    n = len(b)
    if n < 2 or b[0] + 12 - b[-1] > 2:
        return b
    _gap, i = max(((b[(i + 1) % n] - b[i]) % 12, i) for i in range(n))
    start = (i + 1) % n
    return b[start:] + b[:start]


def best_months(scores, iso):
    if iso in CURATED:
        return CURATED[iso]
    ranked = sorted(range(12), key=lambda i: (scores[i] if scores[i] is not None else -1),
                    reverse=True)
    return season_order(m + 1 for m in ranked[:3])


# Rain-only mode measures rain where the committed row's numbers were measured:
# the point that reproduces its temps and scores, give or take Open-Meteo's
# revisions of the same point between runs (a degree, a few points). Four
# committed rows (AZ HK KP MA, 2026-10) still come from the old vertex average
# (centroid()), from before the points moved; a row neither point reproduces
# (Singapore) gets no rain, rather than rain from somewhere else.
REVISION_TEMP = 1
REVISION_SCORE = 3


def _reproduces(scores, temps, row):
    """Whether freshly fetched scores/temps are the committed row's, up to
    Open-Meteo's revisions."""
    def close(a, b, tol):
        return (len(a or []) == len(b or []) == 12
                and all((x is None) == (y is None) and (x is None or abs(x - y) <= tol) for x, y in zip(a, b)))
    return close(temps, row.get("temps"), REVISION_TEMP) and close(scores, row.get("scores"), REVISION_SCORE)


def main(only=None, rain_only=False, elev_only=False):
    """Rebuild every country, or only the ISO codes in `only`. rain_only writes
    rain_mm, rain_days and window onto the rows already committed and nothing
    else: a full run rewrites scores, temps and best, and best feeds every
    guide's description, its best-time sentence and guide-facts.json. It
    reports any country whose scores or temps would have come out different.
    elev_only writes only "elev" (the point's elevation) onto committed rows.
    Every run ends with the point warnings (point_warnings) for the rows it
    touched, marking those REVIEWED has already looked at."""
    if elev_only:
        return main_elev(only)
    with open(GEOJSON, encoding="utf-8") as f:
        geo_data = json.load(f)

    out = {}
    moved = []      # rain_only: countries a full run would have re-scored
    at_old = []     # rain_only: rows measured at the old vertex average
    unmatched = []  # rain_only: rows no point reproduces (no rain written)
    previous = {}
    try:
        with open(OUT, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        pass
    feats = [f for f in geo_data["features"]
             if f["properties"].get("iso") and f["properties"]["iso"] != "-99"
             # Northern Ireland carries iso "GB"; the UK is its own feature.
             and not (f["properties"].get("sub") and f["properties"]["sub"] == f["properties"]["iso"])
             and (not only or f["properties"]["iso"] in only)]
    print("computing climate for {0} countries...".format(len(feats)))
    for i, f in enumerate(feats):
        iso = f["properties"]["iso"]
        name = f["properties"].get("name", iso)
        if iso in out or (rain_only and iso not in previous):
            continue
        pt = sample_point(iso, f["geometry"])
        if pt is None:
            print("  [{0}/{1}] {2} {3} SKIPPED: no sample point on land".format(i + 1, len(feats), iso, name))
            continue
        lon, lat = pt
        try:
            scores, temps, rain_mm, rain_days, elev = monthly_climate(lat, lon)
            rain = {"rain_mm": rain_mm, "rain_days": rain_days, "window": WINDOW}
            at = sample_place(iso, pt)
            if rain_only:
                p = previous[iso]
                if (scores, temps, best_months(scores, iso), at) != (p.get("scores"), p.get("temps"),
                                                                      p.get("best"), p.get("at")):
                    moved.append(iso)
                if not _reproduces(scores, temps, p):
                    old = centroid(f["geometry"])
                    s2, t2, rain_mm, rain_days, _e = (monthly_climate(old[1], old[0]) if old[0] is not None
                                                      else (None, None, None, None, None))
                    if not _reproduces(s2, t2, p):
                        unmatched.append(iso)
                        print("  [{0}/{1}] {2} {3} no rain: neither point reproduces its committed "
                              "numbers".format(i + 1, len(feats), iso, name))
                        continue
                    at_old.append(iso)
                    rain = {"rain_mm": rain_mm, "rain_days": rain_days, "window": WINDOW}
                out[iso] = rain
            else:
                out[iso] = dict({
                    "name": name,
                    "scores": scores,
                    "temps": temps,
                    "best": best_months(scores, iso),
                    "curated": iso in CURATED,
                }, **rain)
                if elev is not None:
                    out[iso]["elev"] = elev
                # Where the temperatures are measured, for the guide's ⓘ. Unset
                # (not null) on the geometric path, so a country whose point
                # moved from a city back to geometry loses the stale name.
                if at:
                    out[iso]["at"] = at
            print("  [{0}/{1}] {2} {3} ok".format(i + 1, len(feats), iso, name))
        except (urllib.error.HTTPError, urllib.error.URLError, Exception) as e:
            print("  [{0}/{1}] {2} {3} FAILED: {4}".format(i + 1, len(feats), iso, name, e))
        # 0.4s was fine for one-year requests; five-year ones are ~5x the payload
        # and Open-Meteo started returning 429 about 190 countries in. It weighs
        # a five-year, two-variable request as ~26 calls against 600 a minute:
        # at 0.9s a refetch of 24 countries was refused on the 25th (2026-11-24),
        # so 3s keeps a run under the minute's budget (an hour's is 5,000).
        time.sleep(3.0)

    # MERGE onto whatever is already committed rather than replacing it. A run
    # that gets rate-limited half way through used to write only the countries
    # it managed to fetch, silently deleting the rest — the 2026-07 rebuild lost
    # 39 (Singapore, the Maldives, most of the Caribbean) before this existed.
    # Stale data for a country beats no data for it. A refreshed country keeps
    # any fields this script doesn't produce.
    kept = [k for k in previous if k not in out]
    merged = dict(previous)
    for iso, row in out.items():
        prev = dict(previous.get(iso) or {})
        # "at" is this script's own field: a country whose override was
        # removed (or rejected as off-land) must not keep naming a city its
        # numbers no longer come from.
        if not rain_only:
            prev.pop("at", None)
            prev.pop("elev", None)
        merged[iso] = dict(prev, **row)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(merged, f, separators=(",", ":"), sort_keys=True)
    print("wrote {0} countries -> {1} ({2} fresh, {3} kept from the previous file)"
          .format(len(merged), OUT, len(out), len(kept)))
    if kept and not only:
        print("  kept: {0}".format(", ".join(sorted(kept)[:20])))
    if rain_only:
        print("rain only: {0} rows gained rain_mm, rain_days, window {1}; scores/temps/best/at left as "
              "committed. A full run would have changed {2}: {3}".format(
                  len(out), WINDOW, len(moved), " ".join(sorted(moved)) or "none"))
        print("  rain measured at the old vertex average, where the committed numbers are from: {0}".format(
            " ".join(sorted(at_old)) or "none"))
        print("  no rain (no point reproduces the committed numbers): {0}".format(
            " ".join(sorted(unmatched)) or "none"))
    else:
        report_warnings(merged, out)


def report_warnings(table, isos):
    """Print every point warning among `isos`, each marked with REVIEWED's
    verdict or as needing one."""
    new = 0
    for iso in sorted(isos):
        w = point_warnings(table.get(iso) or {})
        if not w:
            continue
        seen = REVIEWED.get(iso)
        new += not seen
        print("  WARNING {0} ({1}): {2} — {3}".format(
            iso, (table[iso].get("at") or "geometric point"), "; ".join(w),
            "reviewed: " + seen if seen else "NOT REVIEWED: check the point by hand, then add it to REVIEWED"))
    print("point warnings: {0} not reviewed".format(new))


def main_elev(only=None):
    """Write "elev" onto committed rows from Open-Meteo's elevation API at
    each row's sample point (the rows a full run would write it on, without
    re-fetching their weather). Then the point warnings."""
    with open(GEOJSON, encoding="utf-8") as f:
        geo_data = json.load(f)
    with open(OUT, encoding="utf-8") as f:
        table = json.load(f)
    todo = []
    for f in geo_data["features"]:
        iso = f["properties"].get("iso")
        if (not iso or iso not in table or (only and iso not in only)
                or (f["properties"].get("sub") and f["properties"]["sub"] == iso)):
            continue
        pt = sample_point(iso, f["geometry"])
        if pt is not None and iso not in [t[0] for t in todo]:
            todo.append((iso, pt))
    got = elevations([(pt[1], pt[0]) for _iso, pt in todo])
    for (iso, _pt), e in zip(todo, got):
        if e is not None:
            table[iso]["elev"] = e
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(table, f, separators=(",", ":"), sort_keys=True)
    print("wrote elev for {0} countries -> {1}".format(sum(e is not None for e in got), OUT))
    report_warnings(table, [iso for iso, _pt in todo])


if __name__ == "__main__":
    args = sys.argv[1:]
    main(set(a.upper() for a in args if a not in ("--rain", "--elev")) or None,
         rain_only="--rain" in args, elev_only="--elev" in args)
