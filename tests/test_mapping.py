from desktop_agent.actions import map_point


def test_map_point_1920_1080():
    x, y = map_point(500, 500, width=1920, height=1080, base=1000)
    assert x == 960
    assert y == 540


def test_map_point_clamps():
    x, y = map_point(-100, 1300, width=1366, height=768, base=1000)
    assert x == 0
    assert y == 767
