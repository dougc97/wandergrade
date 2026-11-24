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
Station rain only (STATION_RAIN onto the committed rows, rescored; offline):
                              python3 -m fxtracker.build_climate --station [BT EC]
It writes a static file the website reads, so there are no live weather calls.
"""

import json
import math
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
ELEVATION = "https://api.open-meteo.com/v1/elevation"   # elevations() (--elev); d566c89 dropped it by mistake
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
    # Bhutan (2026-11-24): spring and autumn, the seasons every guide gives.
    # On Paro's station rain the three best-scoring months are May, June and
    # September, and June sat beside the guide's own "Jun–Aug: Monsoon"
    # warning, starred and warned in the same month table.
    "BT": [3, 4, 5, 9, 10, 11],
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
# it stands (scripts/test_climate_points.py holds the list complete). Rain far
# from the place's own records warns too (RAIN_RATIO, below), and is fixed in
# STATION_RAIN, not excused here.
HIGH_M = 800
LOW_BEST = 60
REVIEWED = {
    # High: the place visitors go is high (most of these countries are
    # plateau or highland throughout). Checked by hand 2026-11-24.
    "AF": "Kabul, where nearly every visit starts, is at 1,800 m",
    "AM": "Yerevan itself is at about 1,000 m; most of Armenia is higher",
    "BI": "Bujumbura is on Lake Tanganyika, Burundi's lowest ground (about 780 m)",
    "BO": "La Paz is at 3,650 m, and Uyuni, Titicaca and Sucre are high too (2026-07 point)",
    "BT": "every visitor flies into Paro, and western Bhutan's sights are all at 2,000-2,500 m",
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
    "TF": "Kerguelen is cold and wet all year; Port-aux-Français is the only base",
}
# Rain against each place's own long-run records (2026-11-24). The reanalysis
# drifts wet in some mountain valleys and dry on some coasts: it read Paro
# (Bhutan) at 2,897 mm a year on 270 rain days, where the station records
# 631 mm on 89, and Port-au-Prince at 413 mm against about 1,300. Every row was
# checked against a cited station normal for the same place or the nearest
# representative station (Wikipedia climate boxes, which cite the WMO, NOAA or
# the national met service; the source of each is named below):
#   RAIN_REF      the rows whose Open-Meteo rain is within RAIN_RATIO of the
#                 station's yearly total either way, which keep it: (station
#                 mm a year, "station, normal period, cited source");
#   STATION_RAIN  the rows that were outside it, which use the station's
#                 monthly rain instead (temperatures stay Open-Meteo's). Their
#                 scores and best months are recomputed from it with comfort()
#                 (main, or offline: --station), climate.json names the source
#                 ("rain_src", which the guide's month table quotes), and
#                 rain_days are the station's only where it counts them at
#                 RAIN_DAY_MM (WMO's standard 1 mm, the build's own "more than
#                 1.0 mm" to within the 0.1 mm a gauge reads): a count at 0.1 mm
#                 can't be turned into one at 1 mm without the daily record
#                 (the share of light-rain days varies by climate), so those
#                 rows have no days (None) and the table shows millimetres only.
# A row over RAIN_RATIO from its RAIN_REF warns (point_warnings), as does a
# STATION_RAIN row whose rain isn't the station's; full list and the check
# behind it: scripts/test_station_rain.py.
RAIN_RATIO = 1.5
RAIN_REF = {
    "AE": (79, "Dubai International Airport, 1991–2020, NOAA"),
    "AF": (346, "Kabul, 1991–2020, NOAA"),
    "AL": (1152, "Tirana Airport, 1991–2020, DWD"),
    "AM": (363, "Yerevan, 1991–2020, Pogoda.ru.net"),
    "AR": (1258, "Buenos Aires Central Observatory, 1991–2020, Servicio Meteorológico Nacional"),
    "AT": (669, "Vienna Innere Stadt, 1991–2020, GeoSphere Austria"),
    "AU": (1147, "Sydney Observatory Hill, 1991–2020, Bureau of Meteorology"),
    "AW": (451, "Oranjestad, 1991–2020, Departamento Meteorologico Aruba"),
    "AZ": (274, "Baku (Maştağa), 1991–2020, NOAA"),
    "BA": (949, "Sarajevo, 1991–2020, WMO"),
    "BD": (1990, "Dhaka, 1991–2020, NOAA"),
    "BE": (837, "Uccle, 1991–2020, Royal Meteorological Institute"),
    "BF": (818, "Ouagadougou, 1991–2020, WMO"),
    "BG": (626, "Sofia, 1991–2020, NOAA/WMO"),
    "BH": (94, "Bahrain International Airport, 1991–2020, NOAA"),
    "BI": (922, "Bujumbura, 1991–2020, WMO"),
    "BJ": (1341, "Cotonou, 1991–2020, NOAA"),
    "BN": (3070, "Brunei Airport, 1991–2020, WMO"),
    "BO": (524, "La Paz (Laikakota Park), 1981–2010, SENAMHI Bolivia"),
    "BR": (1069, "Rio de Janeiro (Saúde), 1981–2010, INMET"),
    "BW": (453, "Maun, period not stated, wetterkontor.de (de.wikipedia)"),
    "BY": (686, "Minsk, 1991–2020, Pogoda.ru.net"),
    "BZ": (1970, "Belize City airport, 1991–2020, National Meteorological Service (nearest to the cayes)"),
    "CA": (930, "Ottawa International Airport, 1991–2020, Environment Canada"),
    "CD": (1482, "Kinshasa N'djili Airport, 1991–2020, Starlings Roost Weather"),
    "CF": (1458, "Bangui M'poko Airport, 1991–2020, NOAA"),
    "CG": (1495, "Brazzaville, 1991–2020, NOAA"),
    "CH": (1108, "Zürich Fluntern, 1991–2020, NOAA/MeteoSwiss"),
    "CI": (1691, "Abidjan, 1991–2020, DWD"),
    "CL": (286, "Santiago Quinta Normal, 1991–2020, Dirección Meteorológica de Chile"),
    "CN": (586, "Beijing (Haidian), 1991–2020, China Meteorological Administration"),
    "CO": (1074, "Cartagena Rafael Núñez Airport, 1991–2020, IDEAM"),
    "CU": (1242, "Havana Casa Blanca, 1991–2020, WMO"),
    "CW": (570, "Curaçao Hato Airport, 1991–2020, Meteorological Department Curaçao"),
    "CY": (408, "Limassol, 1991–2020, Meteorological Service (Cyprus)"),
    "CZ": (454, "Prague Clementinum, 1991–2020, Czech Hydrometeorological Institute"),
    "DE": (532, "Berlin-Brandenburg, 1991–2020, DWD"),
    "DK": (523, "Copenhagen Airport, 1991–2020, Danish Meteorological Institute"),
    "DO": (1158, "Punta Cana International Airport, 1991–2020, NOAA"),
    "DZ": (601, "Algiers Houari Boumediene Airport, 1991–2020, NOAA"),
    "EE": (701, "Tallinn, 1991–2020, Estonian Weather Service"),
    "EG": (25, "Cairo International Airport, 1991–2020, NOAA"),
    "ER": (519, "Asmara, 1961–1990, NOAA"),
    "ES": (558, "Barcelona Airport, 1991–2020, AEMET"),
    "ET": (1056, "Addis Ababa, 1991–2020, Ethiopian Meteorological Institute"),
    "FI": (651, "Helsinki Kaisaniemi, 1991–2020, Finnish Meteorological Institute"),
    "FJ": (1999, "Nadi International Airport, 1991–2020, WMO"),
    "FK": (543, "Stanley, 1961–1990, Climatic Research Unit"),
    "FO": (1399, "Tórshavn, 1991–2020, Danish Meteorological Institute"),
    "FR": (634, "Paris Montsouris, 1991–2020, Météo-France"),
    "GA": (2740, "Libreville, 1991–2020, NOAA"),
    "GB": (615, "London Heathrow, 1991–2020, Met Office"),
    "GE": (512, "Tbilisi, 1991–2020, Pogoda.ru.net/NOAA"),
    "GG": (861, "Guernsey Airport, 1991–2020, Guernsey Met Office"),
    "GH": (799, "Accra International Airport, 1991–2020, NOAA"),
    "GL": (848, "Nuuk, 1991–2020, Danish Meteorological Institute"),
    "GM": (909, "Banjul, 1991–2020, WMO"),
    "GN": (3730, "Conakry, 1991–2020, NOAA"),
    "GQ": (1869, "Malabo, period not stated, DWD"),
    "GR": (433, "downtown Athens, 1991–2020, National Observatory of Athens"),
    "GT": (1354, "Guatemala City La Aurora Airport, 1991–2020, NOAA (Antigua's own box cites Climate-Data.org)"),
    "GU": (2492, "Guam International Airport, 1991–2020, NOAA"),
    "GW": (1532, "Bissau Osvaldo Vieira Airport, 1991–2020, NOAA"),
    "GY": (2281, "Georgetown Botanical Gardens, 1991–2020, NOAA"),
    "HK": (2431, "Hong Kong Observatory (Tsim Sha Tsui), 1991–2020, Hong Kong Observatory"),
    "HN": (1672, "La Ceiba Golosón Airport, 1970–1990, NOAA (nearest station to Roatán)"),
    "HU": (572, "Budapest Pestszentlőrinc, 1991–2020, NOAA"),
    "ID": (1742, "Denpasar Ngurah Rai Airport, 1991–2020, Starlings Roost Weather"),
    "IE": (726, "Dublin Merrion Square, 1991–2020, Met Éireann"),
    "IL": (583, "Tel Aviv, 1980–2010, Israel Meteorological Service"),
    "IN": (774, "New Delhi Safdarjung, 1991–2020, India Meteorological Department"),
    "IQ": (125, "Baghdad, 1991–2020, WMO"),
    "IR": (239, "Tehran Mehrabad, 1991–2020, NOAA"),
    "IT": (752, "Rome Urbe Airport, 1991–2020, NOAA"),
    "JM": (1120, "Montego Bay, 1991–2020, NOAA"),
    "JO": (233, "Amman Civil Airport, 1989–2018, Jordan Meteorological Department"),
    "JP": (1598, "Tokyo Kitanomaru Park, 1991–2020, Japan Meteorological Agency"),
    "KE": (749, "Nairobi Jomo Kenyatta Airport, 1991–2020, DWD/Starlings Roost Weather"),
    "KH": (1406, "Siem Reap, 1997–2010, DWD"),
    "KP": (936, "Pyongyang, 1991–2020, Korea Meteorological Administration"),
    "KR": (1418, "Seoul, 1991–2020, Korea Meteorological Administration"),
    "KW": (116, "Kuwait City, 1991–2020, Météo Climat"),
    "KZ": (673, "Almaty, 1991–2020, Pogoda.ru.net"),
    "LA": (1472, "Luang Prabang, 1991–2020, WMO"),
    "LB": (729, "Beirut International Airport, period not stated, Danish Meteorological Institute"),
    "LK": (2397, "Colombo, 1991–2020, NOAA"),
    "LR": (4561, "Roberts International Airport, 1991–2020, DWD/Danish Meteorological Institute"),
    "LS": (786, "Maseru Mejametala Airport, 1991–2020, WMO"),
    "LT": (678, "Vilnius, 1991–2020, Lithuanian Hydrometeorological Service"),
    "LU": (832, "Luxembourg Airport, 1991–2020, Meteolux"),
    "LV": (675, "Riga, 1991–2020, Latvian Environment, Geology and Meteorology Agency"),
    "LY": (318, "Tripoli, 1991–2020, WMO"),
    "MA": (221, "Marrakesh Menara Airport, 1991–2020, NOAA"),
    "MD": (555, "Chișinău, 1991–2020, Pogoda.ru.net"),
    "ME": (1993, "Budva, period not stated, Weather.Directory"),
    "MG": (1171, "Antananarivo, 1991–2020, NOAA"),
    "MK": (662, "Ohrid, period not stated, WMO"),
    "ML": (947, "Bamako, 1991–2020, NOAA/WMO"),
    "MM": (2841, "Yangon Kaba-Aye, 1991–2020, WMO"),
    "MN": (273, "Ulaanbaatar, 1991–2020, Pogoda.ru.net/NOAA"),
    "MR": (113, "Nouakchott Oumtounsy Airport, 1991–2020, DWD"),
    "MU": (711, "Port Louis, period not stated, WMO (nearest station to Grand Baie)"),
    "MW": (846, "Mangochi, period not stated, NOAA (nearest station to Cape Maclear)"),
    "MX": (1295, "Cancún, 1991–2020, Servicio Meteorológico Nacional"),
    "MY": (2847, "Kuala Lumpur Subang Airport, 1991–2020, WMO"),
    "MZ": (842, "Maputo International Airport, 1991–2020, DWD/Starlings Roost Weather"),
    "NA": (378, "Windhoek Eros Airport, 1991–2020, DWD"),
    "NE": (554, "Niamey Airport, 1991–2020, NOAA"),
    "NG": (1703, "Lagos Island, 1991–2020, NOAA"),
    "NL": (850, "Amsterdam Schiphol, 1991–2020, KNMI"),
    "NO": (835, "Oslo Blindern, 1991–2020, Seklima (Norwegian Meteorological Institute)"),
    "NZ": (1319, "Wellington Kelburn, 1991–2020, NIWA"),
    "OM": (73, "Muscat International Airport, 1991–2020, NOAA"),
    "PA": (1959, "Panama City, 1991–2020, WMO"),
    "PH": (2243, "Manila Port Area, 1991–2020, PAGASA"),
    "PK": (674, "Lahore, 1991–2020, NOAA"),
    "PL": (693, "Kraków Observatory, 1991–2020, meteomodel.pl"),
    "PR": (1521, "San Juan Luis Muñoz Marín Airport, 1991–2020, NOAA"),
    "PT": (794, "Lisbon Instituto Geofísico, 1991–2020, IPMA"),
    "PY": (1462, "Asunción, 1991–2020, WMO"),
    "QA": (77, "Doha, 1992–2021, Qatar Meteorological Department"),
    "RO": (648, "Bucharest Băneasa, 1991–2020, NOAA"),
    "RS": (699, "Belgrade, 1991–2020, Republic Hydrometeorological Service of Serbia"),
    "RU": (713, "Moscow VDNKh, 1991–2020, Pogoda.ru.net"),
    "RW": (953, "Kigali Airport, 1991–2020, NOAA"),
    "SB": (1961, "Honiara International Airport, 1991–2020, NOAA"),
    "SE": (546, "Stockholm Observatorielunden, 1991–2020, SMHI"),
    "SG": (2113, "Singapore, 1991–2020, National Environment Agency"),
    "SI": (1368, "Ljubljana Bežigrad, 1991–2020, Slovenian Environment Agency"),
    "SK": (574, "Bratislava Airport, 1991–2020, WMO"),
    "SL": (4433, "Freetown, 1961–1990, NOAA"),
    "SN": (392, "Dakar, 1991–2020, NOAA"),
    "SO": (429, "Mogadishu, period not stated, DWD"),
    "SR": (2136, "Paramaribo Zorg en Hoop Airport, 1991–2020, NOAA"),
    "SV": (1782, "San Salvador Ilopango Airport, 1991–2020, MARN/NOAA"),
    "SY": (125, "Damascus International Airport, 1991–2020, NOAA"),
    "SZ": (923, "Manzini, period not stated, WMO"),
    "TD": (510, "N'Djamena, 1991–2020, WMO/Météo Climat"),
    "TG": (830, "Lomé Airport, 1991–2020, NOAA"),
    "TH": (1702, "Bangkok, 1991–2020, NOAA/Thai Meteorological Department"),
    "TJ": (618, "Dushanbe, 1991–2020, Pogoda.ru.net"),
    "TM": (208, "Ashgabat, 1991–2020, Pogoda.ru.net"),
    "TN": (354, "Sousse, period not stated, Climate-Data.org"),
    "TR": (865, "Istanbul Kireçburnu, 1991–2020, source not named on Wikipedia"),
    "TW": (1901, "Taipei, 1991–2020, Central Weather Bureau"),
    "TZ": (1180, "Arusha, period not stated, Weatherbase"),
    "UA": (618, "Kyiv, 1991–2020, Pogoda.ru.net"),
    "UG": (1204, "Kampala Makerere University, 1991–2020, WMO"),
    "US": (1062, "Washington Reagan National Airport, 1991–2020, NOAA"),
    "UY": (1143, "Montevideo Prado, 1991–2020, Instituto Uruguayo de Meteorología"),
    "UZ": (378, "Samarkand, 1991–2020, Pogoda.ru.net"),
    "VE": (1104, "Caracas La Carlota, 1991–2020, NOAA"),
    "VN": (1600, "Hanoi Láng, 1991–2020, Vietnam Institute for Building Science and Technology"),
    "VU": (2339, "Port Vila Bauerfield Airport, period not stated, DWD"),
    "XK": (635, "Pristina, 1991–2020, Republic Hydrometeorological Service of Serbia"),
    "YE": (265, "Sanaa, period not stated, Climate-Data.org"),
    "ZA": (493, "Cape Town International Airport, 1991–2020, NOAA/South African Weather Service"),
    "ZM": (646, "Livingstone, 1991–2020, NOAA"),
    "ZW": (657, "Victoria Falls, 1961–1990, WMO"),
}
STATION_RAIN = {
    "AO": dict(
        station="Luanda", period="1961–1990",
        where="Quatro de Fevereiro Airport",
        agency="Deutscher Wetterdienst",
        page="en.wikipedia.org/wiki/Luanda",
        mm=[30, 36, 114, 136, 16, 0, 0, 1, 2, 7, 32, 31],
        days=None,
        days_rule="counted at ≥0.1 mm",
        why="Open-Meteo 775 mm a year on 90 rain days; the station 405 mm (1.91x)"),
    "BB": dict(
        station="Bridgetown", period="1991–2020",
        where="Grantley Adams International Airport",
        agency="Barbados Meteorological Services",
        page="en.wikipedia.org/wiki/Bridgetown",
        mm=[68.1, 41.7, 38.9, 58.1, 74.1, 101.2, 121.5, 150.6, 162.6, 179.6, 172.6, 91],
        days=None,
        days_rule="threshold not stated",
        why="Open-Meteo 825 mm a year on 180 rain days; the station 1,260 mm (0.65x)"),
    "BS": dict(
        station="Nassau", period="1991–2020",
        where="Lynden Pindling International Airport",
        agency="Bahamas Department of Meteorology",
        page="en.wikipedia.org/wiki/Nassau,_Bahamas",
        mm=[44.7, 48.26, 54.1, 73.91, 139.19, 219.96, 158.24, 211.07, 195.58, 150.62, 86.61, 43.18],
        days=[7, 5, 6, 7, 10, 15, 16, 18, 17, 13, 9, 7],
        days_rule="≥1.0 mm",
        why="Open-Meteo 817 mm a year on 158 rain days; the station 1,425 mm on 130 (0.57x)"),
    "BT": dict(
        station="Paro", period="1996–2017",
        where="Paro",
        agency="National Center for Hydrology and Meteorology (Bhutan)",
        page="en.wikipedia.org/wiki/Paro,_Bhutan",
        mm=[7.1, 13, 22.2, 33.8, 58.7, 80.9, 161.2, 112.7, 87.9, 48.8, 1.5, 2.9],
        days=[0.7, 2.1, 3.7, 6.4, 9.7, 12.5, 18.5, 17.4, 13.3, 4.3, 0.2, 0.5],
        days_rule="WMO rainy days 1996–2018, threshold not stated (WMO's standard is ≥1 mm)",
        why="Open-Meteo 2,897 mm a year on 270 rain days; the station 631 mm on 89 (4.59x)"),
    "CM": dict(
        station="Douala", period="1991–2020",
        where="Douala",
        agency="World Meteorological Organization / Direction de la Météorologie Nationale du Cameroun",
        page="en.wikipedia.org/wiki/Douala",
        mm=[35.6, 55.9, 154.9, 238.8, 274.3, 355.6, 680.7, 690.9, 558.8, 403.9, 124.5, 30.5],
        days=None,
        days_rule="counted at ≥0.1 mm",
        why="Open-Meteo 1,873 mm a year on 240 rain days; the station 3,604 mm (0.52x)"),
    "CR": dict(
        station="Alajuela", period="1956–2003",
        where="Alajuela, beside Juan Santamaría airport, Central Valley",
        agency="World Meteorological Organization (World Weather Information Service)",
        page="en.wikipedia.org/wiki/Alajuela",
        mm=[7.6, 12.6, 17.4, 79.6, 271.2, 265.6, 177.5, 253.8, 340.6, 338.5, 148.5, 32.8],
        days=[2, 1.9, 3, 8.2, 21.6, 23.3, 20.1, 21.8, 25.2, 25.5, 16, 5.9],
        days_rule="threshold not stated (WMO's standard is ≥1 mm)",
        why="Open-Meteo 3,963 mm a year on 282 rain days; the station 1,946 mm on 174 (2.04x)"),
    "CV": dict(
        station="Sal", period="1991–2020",
        where="Amílcar Cabral International Airport, Sal",
        agency="NOAA",
        page="en.wikipedia.org/wiki/Sal,_Cape_Verde",
        mm=[2.8, 0.5, 0.5, 1, 0.5, 0, 2.4, 12.8, 34.5, 15.6, 1.3, 3.4],
        days=None,
        days_rule="counted at ≥0.1 mm",
        why="Open-Meteo 129 mm a year on 25 rain days; the station 75 mm (1.71x)"),
    "DJ": dict(
        station="Djibouti", period="1991–2020",
        where="Djibouti",
        agency="Hong Kong Observatory (rain), Deutscher Wetterdienst (rain days 1968–1986)",
        page="en.wikipedia.org/wiki/Djibouti_(city)",
        mm=[14.1, 12.2, 13.7, 28.5, 16.1, 1.5, 6.3, 5.7, 10.2, 11.4, 22.4, 15.2],
        days=[1.3, 1.1, 1, 1.6, 0.5, 0, 0, 0.4, 0.8, 0.9, 1.8, 1],
        days_rule="≥1.0 mm, 1968–1986",
        why="Open-Meteo 241 mm a year on 49 rain days; the station 157 mm on 10 (1.53x)"),
    "EC": dict(
        station="Quito", period="1991–2020",
        where="Mariscal Sucre airport",
        agency="World Meteorological Organization",
        page="en.wikipedia.org/wiki/Quito",
        mm=[81.3, 109.1, 142.4, 168.2, 120.5, 41.3, 22, 31.5, 69.4, 112.1, 108.5, 93.6],
        days=[14.2, 15.6, 18.4, 20.3, 17.5, 8.2, 5.4, 5.9, 11.2, 16.8, 16.1, 15.2],
        days_rule="≥1.0 mm",
        why="Open-Meteo 2,483 mm a year on 189 rain days; the station 1,100 mm on 165 (2.26x)"),
    # Western Sahara sits on the line: the 1.5x test used the climate box's
    # yearly total, 30.8 mm (1.53x); its rounded months add up to 32 mm,
    # 1.47x, which is what rain_reference() checks against now. Isle of Man
    # (1.51x) is close too, and its station (Ronaldsway) is likely a little
    # drier than Douglas. Both kept on station rain, which moves little:
    # Western Sahara's best score stays 100 (best months Jan-Mar -> Feb-Apr),
    # the Isle of Man's best goes 71 -> 77.
    "EH": dict(
        station="Dakhla", period="1991–2020",
        where="Dakhla",
        agency="NOAA",
        page="en.wikipedia.org/wiki/Dakhla,_Western_Sahara",
        mm=[2.6, 1.5, 2.4, 1.2, 0.9, 0.6, 0, 1.9, 7.6, 5, 1, 6.1],
        days=[0.7, 0.5, 0.4, 0.2, 0.2, 0.2, 0, 0.5, 1, 0.6, 0.2, 0.8],
        days_rule="≥1.0 mm",
        why="Open-Meteo 47 mm a year on 5 rain days; the station 31 mm on 5 (1.53x)"),
    "HR": dict(
        station="Split", period="1991–2020",
        where="Split-Marjan",
        agency="NOAA NCEI",
        page="en.wikipedia.org/wiki/Split,_Croatia",
        mm=[72.7, 63.8, 58.4, 62, 57.8, 49.2, 24.6, 31.7, 82.3, 79.6, 119.8, 98.7],
        days=None,
        days_rule="counted at ≥0.1 mm",
        why="Open-Meteo 1,382 mm a year on 103 rain days; the station 801 mm (1.73x)"),
    "HT": dict(
        station="Port-au-Prince", period="1991–2020",
        where="Port-au-Prince",
        agency="climatemps.com and climate-data.org, as Wikipedia cites them (no met-service normals found)",
        page="en.wikipedia.org/wiki/Port-au-Prince",
        label="Port-au-Prince averages 1991–2020",
        mm=[25, 33, 58, 121, 214, 111, 122, 155, 188, 165, 71, 32],
        days=[3.1, 3.5, 4.8, 8.2, 13.4, 9.1, 9.5, 12.1, 14.2, 13.1, 7.6, 4.4],
        days_rule="≥1 mm",
        why="Open-Meteo 413 mm a year on 72 rain days; the station 1,295 mm on 103 (0.32x)"),
    "IM": dict(
        station="Ronaldsway", period="1991–2020",
        where="Ronaldsway, the island's Met Office station, 13 km from Douglas",
        agency="Met Office",
        page="en.wikipedia.org/wiki/Isle_of_Man",
        mm=[82.5, 65.5, 62.5, 55.1, 54.6, 62.4, 59.1, 67.4, 70.6, 103.3, 105.2, 95],
        days=[14.2, 11.4, 10.9, 10, 9.8, 9.3, 10.2, 10.8, 11.2, 13.4, 15.8, 14.7],
        days_rule="≥1.0 mm",
        why="Open-Meteo 1,338 mm a year on 181 rain days; the station 883 mm on 142 (1.51x)"),
    "IS": dict(
        station="Reykjavík", period="1991–2020",
        where="Reykjavík",
        agency="Icelandic Met Office",
        page="en.wikipedia.org/wiki/Reykjavík",
        mm=[87.1, 90.6, 80.7, 59, 52.6, 43.3, 49.9, 64.5, 87, 79.8, 86.5, 94.9],
        days=[15.3, 15, 14.2, 12, 10.8, 9.3, 10.3, 11.6, 15, 13.1, 13.7, 14.6],
        days_rule="≥1.0 mm",
        why="Open-Meteo 1,586 mm a year on 198 rain days; the station 876 mm on 155 (1.81x)"),
    "KG": dict(
        station="Bishkek", period="1991–2020",
        where="Bishkek",
        agency="Pogoda i klimat (pogodaiklimat.ru), from the station's records",
        page="en.wikipedia.org/wiki/Bishkek",
        mm=[28, 36, 48, 71, 59, 34, 19, 15, 18, 37, 45, 37],
        days=None,
        days_rule="rain days only, snow days apart",
        why="Open-Meteo 763 mm a year on 99 rain days; the station 447 mm (1.71x)"),
    "NC": dict(
        station="Nouméa", period="1991–2020",
        where="Nouméa",
        agency="Météo-France",
        page="en.wikipedia.org/wiki/Nouméa",
        mm=[107.2, 128.3, 161.9, 118.3, 89.9, 77.5, 69.8, 67.5, 39.3, 36.3, 44.2, 64],
        days=[10.1, 10.8, 11.9, 11.7, 11.3, 9.3, 9.4, 8.4, 5.8, 4.8, 6, 6.7],
        days_rule="≥1.0 mm",
        why="Open-Meteo 2,567 mm a year on 193 rain days; the station 1,004 mm on 106 (2.56x)"),
    "NI": dict(
        station="Managua", period="1991–2020",
        where="Augusto C. Sandino airport, Managua, 45 km from Granada",
        agency="Deutscher Wetterdienst",
        page="en.wikipedia.org/wiki/Managua",
        mm=[1, 2, 4, 5, 85, 208, 126, 135, 245, 282, 48, 8],
        days=[0.6, 0.4, 0.4, 0.6, 6.2, 14.8, 12.1, 12.8, 17.3, 18.5, 4.4, 1.2],
        days_rule="≥1 mm",
        why="Open-Meteo 2,386 mm a year on 227 rain days; the station 1,149 mm on 89 (2.08x)"),
    "NP": dict(
        station="Kathmandu", period="1991–2020",
        where="Tribhuvan International Airport",
        agency="World Meteorological Organization",
        page="en.wikipedia.org/wiki/Kathmandu",
        mm=[15.2, 23.6, 38, 62.9, 128.8, 241.4, 384.1, 342.7, 207.8, 43.3, 6.4, 7.8],
        days=[1.9, 2.6, 3.9, 6.6, 11.9, 16.9, 23.1, 22.7, 14.6, 3.8, 0.5, 0.7],
        days_rule="≥1.0 mm",
        why="Open-Meteo 2,707 mm a year on 183 rain days; the station 1,502 mm on 109 (1.80x)"),
    "PE": dict(
        station="Cusco", period="1991–2020",
        where="Alejandro Velasco Astete airport",
        agency="NOAA",
        page="en.wikipedia.org/wiki/Cusco",
        mm=[153.4, 132.1, 105.9, 38.4, 7.1, 3.3, 5.9, 6.6, 18, 54.5, 77.3, 125.2],
        days=[19.6, 17.2, 15.6, 7.3, 2.2, 1, 1.2, 1.9, 3.9, 9.3, 9.8, 17.1],
        days_rule="≥1.0 mm",
        why="Open-Meteo 1,214 mm a year on 195 rain days; the station 728 mm on 106 (1.67x)"),
    "PG": dict(
        station="Port Moresby", period="",
        where="Port Moresby",
        agency="World Meteorological Organization (World Weather Information Service; period not stated)",
        page="en.wikipedia.org/wiki/Port_Moresby",
        mm=[192.2, 140.6, 189.8, 105.2, 56.2, 21.6, 13.8, 12, 14.4, 15.2, 40, 97.8],
        days=None,
        days_rule="counted at ≥0.1 mm",
        why="Open-Meteo 1,825 mm a year on 216 rain days; the station 899 mm (2.03x)"),
    "PS": dict(
        station="Jerusalem", period="1991–2020",
        where="Jerusalem, 8 km from Bethlehem at the same height",
        agency="NOAA (Israel Meteorological Service station)",
        page="en.wikipedia.org/wiki/Jerusalem",
        mm=[136.8, 117.9, 67.2, 21.8, 7.1, 0.3, 0, 0, 0.7, 10.3, 51.1, 112.3],
        days=[9.2, 8.5, 6.2, 2.4, 0.8, 0, 0, 0, 0.2, 1.9, 4.7, 7.7],
        days_rule="≥1 mm",
        why="Open-Meteo 260 mm a year on 50 rain days; the station 526 mm on 42 (0.49x)"),
    "SA": dict(
        station="Jeddah", period="1991–2020",
        where="Jeddah",
        agency="NOAA / Jeddah Regional Climate Center",
        page="en.wikipedia.org/wiki/Jeddah",
        mm=[12.5, 3.4, 2.6, 1.9, 0.1, 0.1, 0.5, 0.6, 0.1, 1.5, 27.1, 9.1],
        days=[1.1, 0.3, 0.4, 0.2, 0.1, 0, 0.1, 0.2, 0, 0.4, 1.9, 0.7],
        days_rule="≥1.0 mm",
        why="Open-Meteo 128 mm a year on 19 rain days; the station 60 mm on 5 (2.15x)"),
    "SD": dict(
        station="Khartoum", period="1991–2020",
        where="Khartoum",
        agency="World Meteorological Organization",
        page="en.wikipedia.org/wiki/Khartoum",
        mm=[0, 0, 0, 0.4, 4.7, 3.4, 24.9, 53.1, 24.5, 9.1, 0.3, 0],
        days=[0, 0, 0, 0, 0.7, 0.6, 2.8, 4.8, 2.3, 1.1, 0, 0],
        days_rule="WMO 1991–2020 normals, threshold not stated (WMO's standard is ≥1 mm)",
        why="Open-Meteo 58 mm a year on 12 rain days; the station 120 mm on 12 (0.48x)"),
    "SS": dict(
        station="Juba", period="1991–2020",
        where="Juba",
        agency="World Meteorological Organization",
        page="en.wikipedia.org/wiki/Juba",
        mm=[4.3, 11, 36.1, 111.3, 129, 117.1, 143, 148.1, 116.1, 180.3, 71.1, 8.1],
        days=[0, 1, 3, 8, 10, 13, 15, 15, 13, 11, 5, 0],
        days_rule="≥1 mm",
        why="Open-Meteo 669 mm a year on 93 rain days; the station 1,075 mm on 94 (0.62x)"),
    "TF": dict(
        station="Port-aux-Français", period="1991–2020",
        where="Port-aux-Français",
        agency="Météo-France",
        page="en.wikipedia.org/wiki/Port-aux-Français",
        mm=[52.2, 44.4, 59, 64.2, 70.4, 69.1, 69.4, 60.7, 56.3, 46.1, 50.7, 51.8],
        days=[7.7, 7.1, 9, 9.5, 11.8, 10.5, 11.9, 9.5, 8.9, 7.9, 8.2, 8.9],
        days_rule="≥1.0 mm",
        why="Open-Meteo 1,484 mm a year on 205 rain days; the station 694 mm on 111 (2.14x)"),
    "TL": dict(
        station="Dili", period="1991–2020",
        where="Presidente Nicolau Lobato airport",
        agency="BMKG / Timor-Leste Directorate General of Meteorology and Geophysics",
        page="en.wikipedia.org/wiki/Dili",
        mm=[175.2, 143.1, 114.4, 64.1, 29.5, 18.4, 11.2, 6.5, 5.2, 15.5, 53.4, 142.1],
        days=[14.2, 12.4, 11.2, 6.5, 3.6, 2.4, 1.8, 1.1, 0.9, 2.1, 5.4, 12.8],
        days_rule="≥1.0 mm",
        why="Open-Meteo 1,535 mm a year on 204 rain days; the station 779 mm on 74 (1.97x)"),
    "TT": dict(
        station="Piarco", period="1991–2020",
        where="Piarco International Airport, 25 km east of Port of Spain",
        agency="NOAA",
        page="en.wikipedia.org/wiki/Port_of_Spain",
        mm=[79.6, 48.6, 40.6, 51.6, 109.4, 243.4, 228.8, 255.3, 179.1, 192.9, 222.9, 149],
        days=[11.2, 8.3, 6.1, 6.1, 10.9, 19, 19.4, 18.4, 14.5, 15.3, 16.9, 15],
        days_rule="≥1 mm",
        why="Open-Meteo 1,049 mm a year on 231 rain days; the station 1,801 mm on 161 (0.58x)"),
}


def station_label(st):
    """The words the month table's caption uses for a STATION_RAIN entry:
    "Paro station normals 1996–2017"."""
    return st.get("label") or ("%s station normals %s" % (st["station"], st.get("period") or "")).strip()


def _half_up(x):
    return int(math.floor(x + 0.5))


def station_series(st):
    """(rain_mm, rain_days) as a climate.json row carries them for a
    STATION_RAIN entry: whole millimetres and days, rounded half up; days
    None where the station doesn't count them at RAIN_DAY_MM."""
    return ([_half_up(x) for x in st["mm"]],
            [_half_up(x) for x in st["days"]] if st.get("days") else None)


def rain_reference(iso):
    """(mm a year, whose) the row's rain is checked against: STATION_RAIN's
    total or RAIN_REF's, None for neither (Antarctica)."""
    st = STATION_RAIN.get(iso)
    if st:
        return sum(station_series(st)[0]), station_label(st)
    return RAIN_REF.get(iso)


def rain_ratio(iso, row):
    """The row's yearly rain over its reference, or None (no reference, or
    not twelve months of rain)."""
    ref = rain_reference(iso)
    rain = [x for x in row.get("rain_mm") or [] if x is not None]
    return sum(rain) / ref[0] if ref and ref[0] and len(rain) == 12 else None


def point_warnings(row, iso=None):
    """Why a climate.json row needs a look by hand: its point sits above
    HIGH_M or its best month scores under LOW_BEST; and, given its iso, its
    yearly rain is over RAIN_RATIO from the station's either way, or its rain
    source isn't the one STATION_RAIN says. [] when none."""
    out = []
    if (row.get("elev") or 0) > HIGH_M:
        out.append("point at %d m (over %d m)" % (row["elev"], HIGH_M))
    scores = [x for x in row.get("scores") or [] if x is not None]
    if scores and max(scores) < LOW_BEST:
        out.append("best month scores %d (under %d)" % (max(scores), LOW_BEST))
    if iso:
        st = STATION_RAIN.get(iso)
        if st and row.get("rain_src") != station_label(st):
            out.append("rain isn't STATION_RAIN's (python3 -m fxtracker.build_climate --station %s)" % iso)
        elif not st and row.get("rain_src"):
            out.append("rain from %s, which STATION_RAIN no longer lists (rebuild: python3 -m "
                       "fxtracker.build_climate %s)" % (row["rain_src"], iso))
        r = rain_ratio(iso, row)
        if r and not 1 / RAIN_RATIO <= r <= RAIN_RATIO:
            out.append("rain %d mm a year, %.2f times the %d mm on record (%s)"
                       % (sum(row["rain_mm"]), r, rain_reference(iso)[0], rain_reference(iso)[1]))
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


def monthly_climate(lat, lon, station=None):
    """(scores, temps, rain_mm, rain_days, elev): twelve of each of the first
    four — comfort 0-100, mean °C, the month's rain total in mm and its days
    with more than RAIN_DAY_MM, both averaged over the window's years — and
    the point's elevation in metres as Open-Meteo resolves it (None if the
    answer carries none). station: a STATION_RAIN entry, whose monthly rain
    replaces Open-Meteo's in rain_mm and in the scores, and whose days
    replace rain_days (None for a station without comparable days)."""
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
    st_mm, st_days = station_series(station) if station else (None, None)
    for m in range(1, 13):
        at = sum(mt[m]) / len(mt[m]) if mt[m] else None
        tr = (sum(mr[m].values()) / len(mr[m])) if mr[m] else 0
        if station:
            tr = st_mm[m - 1]
        scores.append(comfort(at, tr))
        temps.append(round(at) if at is not None else None)  # avg °C, shown in the guide
        rain_mm.append(round(tr) if mr[m] or station else None)
        rain_days.append(round(sum(md[m].values()) / len(md[m])) if md[m] else None)
    if station:
        rain_days = st_days
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


def main(only=None, rain_only=False, elev_only=False, station_only=False):
    """Rebuild every country, or only the ISO codes in `only`. rain_only writes
    rain_mm, rain_days and window onto the rows already committed and nothing
    else: a full run rewrites scores, temps and best, and best feeds every
    guide's description, its best-time sentence and guide-facts.json. It
    reports any country whose scores or temps would have come out different.
    elev_only writes only "elev" (the point's elevation) onto committed rows.
    station_only puts STATION_RAIN onto committed rows, offline (main_station).
    Every run ends with the point warnings (point_warnings) for the rows it
    touched, marking those REVIEWED has already looked at."""
    if elev_only:
        return main_elev(only)
    if station_only:
        return main_station(only)
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
            st = STATION_RAIN.get(iso)
            scores, temps, rain_mm, rain_days, elev = monthly_climate(lat, lon, st)
            rain = {"rain_mm": rain_mm, "rain_days": rain_days, "window": WINDOW}
            if st:
                rain["rain_src"] = station_label(st)
            at = sample_place(iso, pt)
            if rain_only:
                p = previous[iso]
                if (scores, temps, best_months(scores, iso), at) != (p.get("scores"), p.get("temps"),
                                                                      p.get("best"), p.get("at")):
                    moved.append(iso)
                if not _reproduces(scores, temps, p):
                    old = centroid(f["geometry"])
                    s2, t2, rain_mm, rain_days, _e = (monthly_climate(old[1], old[0], st) if old[0] is not None
                                                      else (None, None, None, None, None))
                    if not _reproduces(s2, t2, p):
                        unmatched.append(iso)
                        print("  [{0}/{1}] {2} {3} no rain: neither point reproduces its committed "
                              "numbers".format(i + 1, len(feats), iso, name))
                        continue
                    at_old.append(iso)
                    rain = dict(rain, rain_mm=rain_mm, rain_days=rain_days)
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
        # Likewise the rain's source: a row this run measured carries it only
        # when its rain is a station's.
        prev.pop("rain_src", None)
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
        w = point_warnings(table.get(iso) or {}, iso)
        if not w:
            continue
        seen = REVIEWED.get(iso)
        new += not seen
        print("  WARNING {0} ({1}): {2} — {3}".format(
            iso, (table[iso].get("at") or "geometric point"), "; ".join(w),
            "reviewed: " + seen if seen else "NOT REVIEWED: check the point by hand, then add it to REVIEWED"))
    print("point warnings: {0} not reviewed".format(new))


def _temp_for(score, temp, rain, exact=False):
    """The unrounded monthly mean temperature a committed score was computed
    from, as near as the row pins it: the middle of the temperatures that
    round to `temp` (°C) and give `score` with `rain` (mm) under comfort().
    Open-Meteo's rain is stored rounded, so it may be up to half a mm either
    way; a station's (exact) is the whole mm the score was computed from.
    Inside the comfort band any of them gives the same score; `temp` itself
    if none matches."""
    rains = (rain,) if exact else (rain - 0.49, rain, rain + 0.49)
    hits = [t for t in (temp - 0.5 + k / 200 for k in range(200))
            if any(comfort(t, r) == score for r in rains)]
    return (hits[0] + hits[-1]) / 2 if hits else temp


def with_station_rain(iso, row):
    """The committed row with STATION_RAIN's rain in place of the rain it
    has, its scores recomputed by comfort() from that rain and the month's
    temperature (recovered from the row: _temp_for), its best months by
    best_months (and "curated" with them), and "rain_src" naming the
    station. Nothing else changes.
    Running it on a row that already carries the station's rain gives the
    same row back."""
    st = STATION_RAIN[iso]
    mm, days = station_series(st)
    exact = bool(row.get("rain_src"))     # its rain is already a station's whole mm
    temps = [_temp_for(s, t, r, exact) for s, t, r in zip(row["scores"], row["temps"], row["rain_mm"])]
    scores = [comfort(t, r) for t, r in zip(temps, mm)]
    return dict(row, scores=scores, rain_mm=mm, rain_days=days, rain_src=station_label(st),
                best=best_months(scores, iso), curated=iso in CURATED)


def main_station(only=None):
    """Offline: put STATION_RAIN's rain onto the committed rows (all of it,
    or the ISO codes in `only`) with with_station_rain, so no Open-Meteo
    request is made. Prints each row's yearly rain, best months and best
    score before and after, then the point warnings."""
    with open(OUT, encoding="utf-8") as f:
        table = json.load(f)
    done = []
    for iso in sorted(STATION_RAIN):
        if only and iso not in only:
            continue
        row = table.get(iso)
        if not row or any(len(row.get(k) or []) != 12 or None in row[k] for k in ("scores", "temps", "rain_mm")):
            print("  %s: no committed row with twelve months of scores, temps and rain — skipped" % iso)
            continue
        new = with_station_rain(iso, row)
        print("  %s: rain %d -> %d mm a year (%s); best %s -> %s, best score %d -> %d" % (
            iso, sum(row["rain_mm"]), sum(new["rain_mm"]), new["rain_src"], row.get("best"), new["best"],
            max(row["scores"]), max(new["scores"])))
        table[iso] = new
        done.append(iso)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(table, f, separators=(",", ":"), sort_keys=True)
    print("wrote station rain for {0} countries -> {1}".format(len(done), OUT))
    report_warnings(table, done)


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
    main(set(a.upper() for a in args if a not in ("--rain", "--elev", "--station")) or None,
         rain_only="--rain" in args, elev_only="--elev" in args, station_only="--station" in args)
