from exhibit_validator.layers.match_layer import score_pair

def test_identical_coordinates_high_score():
    rec_a = {"name": "Apple 西湖", "address": "平海路100号", "latitude": 30.254206, "longitude": 120.163571}
    rec_b = {"name": "Apple 西湖", "address": "平海路100号", "latitude": 30.254118, "longitude": 120.163491}
    score = score_pair(rec_a, rec_b)
    assert score > 0.9 

def test_completely_different_places_low_score():
    rec_a = {"name": "西湖", "address": "南山路", "latitude": 30.24, "longitude": 120.14}
    rec_b = {"name": "雷峰塔", "address": "南山路", "latitude": 30.23, "longitude": 120.14}
    score = score_pair(rec_a, rec_b)
    assert score < 0.6 