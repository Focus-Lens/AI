import pytest
from google.genai import errors

from study_chatbot.gemini_client import with_retry


def err(code, message="error"):
    return errors.APIError(code, {"error": {"message": message}})


def no_sleep(_):
    pass


def test_retries_503_then_succeeds():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise err(503)
        return "ok"

    assert with_retry(fn, sleep=no_sleep) == "ok"
    assert len(calls) == 3


def test_gives_up_after_last_delay():
    calls = []

    def fn():
        calls.append(1)
        raise err(429, "per minute")

    with pytest.raises(errors.APIError):
        with_retry(fn, sleep=no_sleep)
    assert len(calls) == 4


@pytest.mark.parametrize("e", [err(400, "API key not valid"), err(429, "Generate content requests per day limit exceeded")])
def test_does_not_retry_bad_key_or_daily_quota(e):
    calls = []

    def fn():
        calls.append(1)
        raise e

    with pytest.raises(errors.APIError):
        with_retry(fn, sleep=no_sleep)
    assert len(calls) == 1
