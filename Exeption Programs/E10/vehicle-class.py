WEIGHT_RANGE_INDEXES = [
    (7500, 1, "Car"),
    (12000, 2, "LCV"),
    (18500, 3, "Truck"),
    (31000, 4, "Truck3X"),
    (60000, 5, "MAV"),
]


def get_vehicle_class_from_weight(weight):
    try:
        # Convert weight to numeric
        weight_value = float(weight)
        
        # Apply weight class logic
        if weight_value < 100:
            return "NA"
        for upper_bound, _, label in WEIGHT_RANGE_INDEXES:
            if weight_value <= upper_bound:
                return label
        if weight_value > 60000:
            return "OSV"
        return "NA"
    
    except (ValueError, TypeError):
        # If weight is not a valid number (N/A, Error, etc.)
        return "Unknown"