from night_crawler.domain.ports.browser_agent_recorder import AgentFinalResult
from night_crawler.infrastructure.external.browser_use_history import (
    get_step_start_times,
    get_stop_error,
    map_final_result,
    map_steps,
)

FINAL_URL = "https://shows.example/search?page=2#done"


def test_steps_keep_the_action_its_target_and_the_url_after_it(load_history):
    steps = map_steps(load_history(), FINAL_URL)

    assert [0, 1, 2, 3] == [step.index for step in steps]
    assert ["navigate", "click", "input", "done"] == [step.action for step in steps]
    assert {"url": "http://shows.example/start", "new_tab": False} == steps[0].params
    assert [None, "html/body/main/button[2]", None, None] == [
        step.target_xpath for step in steps
    ]
    assert [
        "https://shows.example/search",
        "https://shows.example/search?page=2",
        "https://shows.example/search?page=2",
        FINAL_URL,
    ] == [step.url for step in steps]


def test_a_run_that_never_stepped_has_no_steps(load_history):
    assert () == map_steps(load_history(0), None)


def test_a_failed_step_keeps_its_error(load_history):
    steps = map_steps(load_history(), FINAL_URL)

    assert [True, True, False, True] == [step.is_success for step in steps]
    assert "Element index 7 not available" == steps[2].error
    assert None is steps[0].error


def test_step_start_times_come_from_the_metadata(load_history):
    assert [100.0, 101.0, 102.0, 103.0] == get_step_start_times(load_history())


def test_the_final_result_is_parsed_json(load_history):
    assert AgentFinalResult(
        data=[{"item_id": "1", "name": "Comedy night"}], is_success=True
    ) == map_final_result(load_history())


def test_a_run_without_an_answer_has_no_data(load_history):
    assert AgentFinalResult(data=None, is_success=False) == map_final_result(
        load_history(2)
    )


def test_an_answer_that_is_not_json_stays_text(load_history):
    history = load_history()
    history.history[-1].result[-1].extracted_content = "No shows today."

    assert AgentFinalResult(
        data="No shows today.", is_success=True
    ) == map_final_result(history)


def test_a_run_that_stopped_on_an_error_reports_it(load_history):
    assert "Element index 7 not available" == get_stop_error(load_history(3))
    assert None is get_stop_error(load_history())
    assert None is get_stop_error(load_history(2))
