def normalize_record(record: dict) -> dict:
    """
    Maps heterogeneous JSON fields to standard internal keys:
    'name', 'address', 'typecode'
    """
    if not isinstance(record, dict):
        return {}

    norm = record.copy()
    
    # 1. Map Name
    if not norm.get("name"):
        for key in ["title", "poi_name", "venue_name", "display_name", "name_zh"]:
            if key in record and record[key]:
                norm["name"] = str(record[key])
                break

    # 2. Map Address
    if not norm.get("address"):
        for key in ["location_text", "full_address", "addr", "address_line", "location"]:
            if key in record and record[key] and isinstance(record[key], str):
                norm["address"] = record[key]
                break

    # 3. Map Typecode
    if not norm.get("typecode"):
        for key in ["category_id", "type_code", "category", "type"]:
            if key in record and record[key]:
                norm["typecode"] = str(record[key])
                break
                
    if not norm.get("id"):
        import uuid
        norm["id"] = f"gen_{uuid.uuid4().hex[:8]}"

    return norm