from server.config import account_defaults, public_config, validate_config


def test_existing_account_defaults_to_duration_mode_without_losing_configuration():
    old = account_defaults()
    old["study"].pop("study_mode")
    old["study"].pop("replay_completed")
    old["course_keys"] = ["course:class"]
    old["study"]["speed"] = 1.5
    visible = public_config(old)
    assert visible["study"]["study_mode"] == "duration"
    assert visible["study"]["replay_completed"] is True
    saved = validate_config({"study": {"jobs": 2}}, old)
    assert saved["study"]["speed"] == 1.5
    assert saved["study"]["study_mode"] == "duration"
    assert saved["course_keys"] == ["course:class"]
