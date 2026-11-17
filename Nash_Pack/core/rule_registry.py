"""Complete rule registry for SIH26034.

This registry is deliberately broader than the image-checkable rules.  Every
numbered rule in the current consolidated 2011 framework is represented so
that the report can distinguish label checks from administrative/physical
checks instead of silently skipping provisions.
"""

RULE_REGISTRY = [
    {"id":"Rule 1", "group":"SCOPE", "title":"Short title and commencement", "mode":"ADMINISTRATIVE"},
    {"id":"Rule 2", "group":"SCOPE", "title":"Definitions", "mode":"CLASSIFICATION"},
    {"id":"Rule 3", "group":"APPLICABILITY", "title":"Application of Chapter II", "mode":"CONTEXT"},
    {"id":"Rule 4", "group":"APPLICABILITY", "title":"Regulation for pre-packing and sale of commodities in packaged form", "mode":"IMAGE_AND_CONTEXT"},
    {"id":"Rule 4 — Explanation 2 (2026)", "group":"APPLICABILITY", "title":"Mandatory declarations at specified bonded warehouses for AEO Tier-2/Tier-3 importers; complete declarations before exit", "mode":"CONTEXT"},
    {"id":"Rule 5", "group":"LEGACY", "title":"Specific commodities to be packed in recommended standard packages", "mode":"OMITTED"},
    {"id":"Rule 6", "group":"DECLARATIONS", "title":"Declarations to be made on every package", "mode":"IMAGE_AND_CONTEXT"},
    {"id":"Rule 6(1)(a)", "group":"DECLARATIONS", "title":"Manufacturer / packer / importer name and address", "mode":"IMAGE"},
    {"id":"Rule 6(1)(aa)", "group":"DECLARATIONS", "title":"Country of origin/manufacture/assembly for imported products", "mode":"IMAGE"},
    {"id":"Rule 6(1)(b)", "group":"DECLARATIONS", "title":"Common or generic name; multi-product contents", "mode":"IMAGE"},
    {"id":"Rule 6(1)(c)", "group":"DECLARATIONS", "title":"Net quantity / number in standard units", "mode":"IMAGE"},
    {"id":"Rule 6(1)(d)", "group":"DECLARATIONS", "title":"Month and year of manufacture", "mode":"IMAGE_OR_SECTOR_RULE"},
    {"id":"Rule 6(1)(da)", "group":"DECLARATIONS", "title":"Best before / use by where applicable", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 6(1)(e)", "group":"DECLARATIONS", "title":"Retail sale price / MRP inclusive of all taxes", "mode":"IMAGE"},
    {"id":"Rule 6(1)(f)", "group":"DECLARATIONS", "title":"Consumer care contact details", "mode":"IMAGE"},
    {"id":"Rule 6(10)", "group":"E_COMMERCE", "title":"Mandatory declarations on e-commerce network", "mode":"CONTEXT"},
    {"id":"Rule 6(10A)", "group":"E_COMMERCE", "title":"Imported-product country-of-origin filter on e-commerce listings (effective 1 July 2027)", "mode":"CONTEXT"},
    {"id":"Rule 6(11)", "group":"DECLARATIONS", "title":"Unit sale price", "mode":"IMAGE_AND_CALCULATION"},
    {"id":"Rule 7", "group":"PRESENTATION", "title":"Principal display panel / lettering and numerals", "mode":"PARTIAL_IMAGE"},
    {"id":"Rule 8", "group":"PRESENTATION", "title":"Where declarations are to appear", "mode":"PARTIAL_IMAGE"},
    {"id":"Rule 9", "group":"PRESENTATION", "title":"Manner in which declaration shall be made", "mode":"PARTIAL_IMAGE"},
    {"id":"Rule 10", "group":"DECLARATIONS", "title":"Name and address of manufacturer etc.", "mode":"IMAGE"},
    {"id":"Rule 11", "group":"QUANTITY", "title":"Declaration of quantity", "mode":"IMAGE_AND_CLASSIFICATION"},
    {"id":"Rule 12", "group":"QUANTITY", "title":"Permitted qualification / dimensions / additional quantity information", "mode":"IMAGE_AND_CLASSIFICATION"},
    {"id":"Rule 13", "group":"QUANTITY", "title":"Statement of units of weight, measure or number", "mode":"IMAGE_AND_CALCULATION"},
    {"id":"Rule 14", "group":"COMMODITY_SPECIFIC", "title":"Dimensions of certain commodities", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 15", "group":"COMMODITY_SPECIFIC", "title":"Dimensions and weight where related to price", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 16", "group":"COMMODITY_SPECIFIC", "title":"Number of usable sheets and dimensions", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 17", "group":"COMMODITY_SPECIFIC", "title":"Additional commodity-specific declaration requirement", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 18", "group":"INSPECTION", "title":"Verification / enforcement of package declarations", "mode":"CONTEXT"},
    {"id":"Rule 19", "group":"INSPECTION", "title":"Inspection of quantity and error at manufacturer/packer premises", "mode":"PHYSICAL"},
    {"id":"Rule 20", "group":"INSPECTION", "title":"Action on completion of inspection", "mode":"PHYSICAL"},
    {"id":"Rule 21", "group":"INSPECTION", "title":"Inspection at wholesale / retail dealer premises", "mode":"PHYSICAL"},
    {"id":"Rule 22", "group":"PHYSICAL_VERIFICATION", "title":"Maximum permissible error / actual quantity verification", "mode":"PHYSICAL"},
    {"id":"Rule 23", "group":"PHYSICAL_VERIFICATION", "title":"Deceptive package", "mode":"CONTEXT_AND_PHYSICAL"},
    {"id":"Rule 24", "group":"WHOLESALE", "title":"Declarations on every wholesale package", "mode":"CONDITIONAL_IMAGE"},
    {"id":"Rule 25", "group":"EXPORT", "title":"Restrictions on sale of export packages in India", "mode":"CONTEXT"},
    {"id":"Rule 26", "group":"EXEMPTIONS", "title":"Exemption in respect of certain packages", "mode":"CLASSIFICATION"},
    {"id":"Rule 27", "group":"REGISTRATION", "title":"Registration of manufacturer / packer / importer", "mode":"EXTERNAL_RECORD"},
    {"id":"Rule 27(2)(d) (2026)", "group":"REGISTRATION", "title":"Director responsible for violations (company cases)", "mode":"EXTERNAL_RECORD"},
    {"id":"Rule 28", "group":"REGISTRATION", "title":"Registration of shorter address", "mode":"EXTERNAL_RECORD"},
    {"id":"Rule 29", "group":"REGISTRATION", "title":"Register of manufacturers and packers", "mode":"EXTERNAL_RECORD"},
    {"id":"Rule 30", "group":"REGISTRATION", "title":"Compilation of registered manufacturer / packer lists", "mode":"ADMINISTRATIVE"},
    {"id":"Rule 31", "group":"ADVERTISING", "title":"Advertisements mentioning retail sale price", "mode":"CONTEXT"},
    {"id":"Rule 32", "group":"ENFORCEMENT", "title":"Fine for contravention of rules", "mode":"ADMINISTRATIVE"},
    {"id":"Rule 32-A", "group":"ENFORCEMENT", "title":"Compounding of offences", "mode":"ADMINISTRATIVE"},
    {"id":"Rule 33", "group":"RELAXATION", "title":"Power to relax", "mode":"EXTERNAL_RECORD"},
    {"id":"Rule 34", "group":"SAVINGS", "title":"Repeal and savings", "mode":"ADMINISTRATIVE"},
]

RULE_IDS = {item["id"] for item in RULE_REGISTRY}
