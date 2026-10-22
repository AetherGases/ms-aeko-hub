"""Outbound HTTP paths, Climatiq API settings, and profile field names."""

AUTH_MS_LOGIN_PATH = "/api/auth/login"
CLOUDINARY_UPLOAD_SIGNATURE_PATH = "/api/cloudinary/upload-signature"
INVENTORY_CREATE_PATH = "/api/inventories"
PROFILE_MS_PATH = "/api/profile"

_TOOL_PROFILE_KEYS = (
    "id",
    "email",
    "name",
    "image",
    "enterprise",
    "unit",
)

CLIMATIQ_BASE_URL = "https://api.climatiq.io/data/v1"
CLIMATIQ_SEARCH_URL = f"{CLIMATIQ_BASE_URL}/search"
CLIMATIQ_ESTIMATE_URL = f"{CLIMATIQ_BASE_URL}/estimate"
CLIMATIQ_DATA_VERSION = "^37"
CLIMATIQ_REQUEST_TIMEOUT = 60.0
CLIMATIQ_RESULTS_PER_PAGE = 5

CLIMATIQ_SELECTOR_FIELDS = (
    "source",
    "source_dataset",
    "region",
    "region_fallback",
    "year",
    "year_fallback",
    "scope",
    "source_lca_activity",
    "calculation_method",
)

CLIMATIQ_ESTIMATE_FIELDS = ("apply_inflation_adjustment",)

CLIMATIQ_SEARCH_DESCRIPTION = (
    "Searches Climatiq's emission factor database for a material, product, "
    "fuel or activity. Input is the description in plain text (e.g. 'cimento "
    "portland'). Returns candidate emission factors, each with its "
    "'activity_id', its 'unit_type' (which says whether it is measured by "
    "weight, money, energy or distance), its region and its year. Use this "
    "first to find the right factor, then pass the chosen 'activity_id' to "
    "climatiq_estimate to get the emissions."
)
CLIMATIQ_ESTIMATE_DESCRIPTION = (
    "Calculates the carbon emissions of an activity, using an emission factor "
    "found with climatiq_search. Input is a JSON object string with "
    '"activity_id" (from the search results) and "parameters" (how much of '
    "the activity, as the value and its unit) — for example "
    '\'{"activity_id": "building_materials-type_cement", "parameters": '
    '{"weight": 100, "weight_unit": "t"}}\'. The parameter name must match the '
    "factor's unit_type: weight/weight_unit, money/money_unit, "
    'energy/energy_unit or distance/distance_unit. Optional: "region", '
    '"year", "source", "region_fallback", "year_fallback". Returns kg CO2e '
    "together with the emission factor that produced it."
)
