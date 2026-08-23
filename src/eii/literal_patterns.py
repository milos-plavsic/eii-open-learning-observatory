"""Auditable literal patterns shared by deterministic course comparisons."""

import re

# Units are intentionally allow-listed. Capturing arbitrary letters after a
# number turns translated nouns and conjunctions into false unit drift.
_UNIT = (
    r"%|‰|°(?:C|F)?|mm|cm|dm|m|km|mg|g|kg|ml|cl|dl|l|ms|s|min|h|Hz|kHz|MHz|GHz|"
    r"B|KB|MB|GB|TB|KiB|MiB|GiB|TiB|V|mV|kV|A|mA|W|kW|MW|J|kJ|N|Pa|kPa|MPa|"
    r"mol|lb|lbs|oz|ft|yd|mi|gal|px|dpi|rpm|kbps|Mbps|Gbps"
)

NUMBER_PATTERN = re.compile(rf"(?<!\w)(?:[$€£¥₹]\s*)?[+-]?\d+(?:[.,]\d+)?(?:\s*(?:{_UNIT})(?!\w))?")
