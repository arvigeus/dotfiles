"""Native store content labels. Missing or malformed labels remain unknown."""


def steam(raw, app_id):
    entry = raw.get(str(app_id)) if isinstance(raw, dict) else None
    data = entry.get('data') if isinstance(entry, dict) else None
    if (
        not entry
        or entry.get('success') is not True
        or not isinstance(data, dict)
        or str(data.get('steam_appid')) != str(app_id)
    ):
        return None
    descriptors = data.get('content_descriptors')
    ids = descriptors.get('ids') if isinstance(descriptors, dict) else None
    if not isinstance(ids, list) or any(type(value) is not int for value in ids):
        return None
    # Valve: Adult Only Sexual Content / Frequent Nudity or Sexual Content.
    # Some nudity (1), violence (2) and general mature content (5) don't qualify.
    if {3, 4}.intersection(ids):
        return True
    return False if set(ids).issubset({1, 2, 5}) else None


def gog(raw, product_id):
    embedded = raw.get('_embedded') if isinstance(raw, dict) else None
    product = embedded.get('product') if isinstance(embedded, dict) else None
    if not isinstance(product, dict) or str(product.get('id')) != str(product_id):
        return None
    properties = embedded.get('properties')
    if not isinstance(properties, list) or any(
        not isinstance(row, dict) or not isinstance(row.get('slug'), str)
        for row in properties
    ):
        return None
    # The v2 API calls store tags "properties"; "tags" contains genres instead.
    return any(row['slug'] == 'nsfw' for row in properties)
