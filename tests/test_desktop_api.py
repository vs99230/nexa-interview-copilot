from desktop import WindowApi


def test_native_window_is_not_exposed_through_javascript_api():
    api = WindowApi()
    public_attributes = {name for name in dir(api) if not name.startswith("_")}

    assert "window" not in public_attributes
    assert "_window" in vars(api)
